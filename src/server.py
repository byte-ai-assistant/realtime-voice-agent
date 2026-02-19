"""
Real-Time Voice AI Agent - Main Server
Handles Twilio voice calls with WebSocket streaming
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
import uvicorn
from dotenv import load_dotenv

from voice_handler import VoiceHandler
from ai_agent import AIAgent
from knowledge_base import KnowledgeBase
from tools import AppointmentManager, EscalationHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Real-Time Voice AI Agent",
    description="Production-ready voice AI for phone calls",
    version="1.0.0"
)

# Global instances
knowledge_base: Optional[KnowledgeBase] = None
active_calls: Dict[str, Dict] = {}


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    global knowledge_base

    # Track server start time for uptime metrics
    app.state.start_time = datetime.utcnow()

    logger.info("Starting Real-Time Voice AI Agent...")

    # Initialize knowledge base
    try:
        kb_path = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge/sample_kb.json")
        knowledge_base = KnowledgeBase()
        await knowledge_base.initialize(kb_path)
        logger.info(f"Knowledge base initialized with {knowledge_base.document_count} documents")
    except Exception as e:
        logger.error(f"Failed to initialize knowledge base: {e}")
        raise

    logger.info("Server ready to accept calls!")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Real-Time Voice AI Agent",
        "version": "1.0.0",
        "active_calls": len(active_calls),
        "knowledge_base_ready": knowledge_base is not None
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            "knowledge_base": knowledge_base is not None,
            "active_calls": len(active_calls),
            "api_keys": {
                "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
                "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY")),
                "deepgram": bool(os.getenv("DEEPGRAM_API_KEY")),
                "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID"))
            }
        }
    }


@app.post("/test/chat")
async def test_chat(request: Request):
    """
    Text-based test endpoint for the AI agent.
    Tests Claude + RAG + tool calling without any audio.
    Enable via ENABLE_TEST_ENDPOINTS=true env var.

    Usage: curl -X POST http://localhost:8000/test/chat \
           -H "Content-Type: application/json" \
           -d '{"text": "What are your prices?"}'
    """
    if not os.getenv("ENABLE_TEST_ENDPOINTS", "").lower() in ("true", "1", "yes"):
        return {"error": "Test endpoints disabled. Set ENABLE_TEST_ENDPOINTS=true"}

    try:
        body = await request.json()
        user_text = body.get("text", "")
        if not user_text:
            return {"error": "Missing 'text' field in request body"}

        # Create a temporary AI agent with the shared knowledge base
        ai_agent = AIAgent(knowledge_base=knowledge_base)
        await ai_agent.send_greeting()

        # Collect the full response
        response_text = ""
        tool_results = []

        async for chunk in ai_agent.process_message(user_text):
            if chunk.get("type") == "text":
                response_text += chunk["content"]
            elif chunk.get("type") == "tool_call":
                tool_results.append({
                    "tool": chunk["name"],
                    "input": chunk["input"],
                    "result": chunk["result"]
                })
            elif chunk.get("type") == "error":
                response_text += chunk["content"]

        return {
            "user": user_text,
            "response": response_text,
            "tool_calls": tool_results if tool_results else None,
            "conversation_history_length": len(ai_agent.conversation_history)
        }

    except Exception as e:
        logger.error(f"Test chat error: {e}", exc_info=True)
        return {"error": str(e)}


@app.post("/webhook/voice")
async def voice_webhook(request: Request):
    """
    Twilio webhook endpoint for incoming calls
    Returns TwiML to establish WebSocket connection
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")

    logger.info(f"Incoming call: {call_sid} from {from_number}")

    # Get WebSocket URL (use public URL in production)
    ws_url = os.getenv("WEBSOCKET_URL", f"wss://{request.url.hostname}/ws/media")

    # Return TwiML to connect call to WebSocket
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="callSid" value="{call_sid}"/>
        </Stream>
    </Connect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


@app.websocket("/ws/media")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time audio streaming
    Handles bidirectional audio with Twilio
    """
    await websocket.accept()

    call_sid = None
    stream_sid = None
    voice_handler = None
    ai_agent = None
    is_agent_speaking = False

    try:
        logger.info("WebSocket connection established")

        # Create handler instances
        voice_handler = VoiceHandler()
        ai_agent = AIAgent(knowledge_base=knowledge_base)

        async def send_audio_to_twilio(audio_chunk: bytes):
            """Encode and send an audio chunk to Twilio"""
            nonlocal stream_sid
            if not stream_sid:
                return
            payload = base64.b64encode(audio_chunk).decode("utf-8")
            await websocket.send_json({
                "event": "media",
                "streamSid": stream_sid,
                "media": {
                    "payload": payload
                }
            })

        async def clear_twilio_audio():
            """Send clear event to stop Twilio audio playback (for interrupts)"""
            nonlocal stream_sid
            if not stream_sid:
                return
            await websocket.send_json({
                "event": "clear",
                "streamSid": stream_sid,
            })

        async def send_mark(name: str):
            """Send a mark event to Twilio to track audio playback position"""
            nonlocal stream_sid
            if not stream_sid:
                return
            await websocket.send_json({
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": name}
            })

        async def synthesize_and_send(text: str):
            """Synthesize text to speech and stream to Twilio"""
            nonlocal is_agent_speaking
            is_agent_speaking = True
            async for audio_chunk in voice_handler.synthesize_speech(text):
                await send_audio_to_twilio(audio_chunk)

        async def receive_audio():
            """Receive audio and control events from Twilio"""
            nonlocal call_sid, stream_sid, is_agent_speaking

            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")

                    if event == "start":
                        call_sid = data["start"]["callSid"]
                        stream_sid = data["start"]["streamSid"]
                        logger.info(f"Stream started: {stream_sid} for call: {call_sid}")
                        active_calls[call_sid] = {
                            "stream_sid": stream_sid,
                            "started_at": datetime.utcnow().isoformat()
                        }

                        # Synthesize and send greeting audio to caller
                        greeting_text = await ai_agent.send_greeting()
                        await synthesize_and_send(greeting_text)
                        await send_mark("greeting_end")

                    elif event == "media":
                        # Decode audio from Twilio (base64 mu-law)
                        payload = data["media"]["payload"]
                        audio_data = base64.b64decode(payload)

                        # Process audio through voice handler
                        await voice_handler.process_incoming_audio(audio_data)

                    elif event == "mark":
                        # Audio playback completed for this mark
                        mark_name = data.get("mark", {}).get("name", "")
                        logger.debug(f"Mark received: {mark_name}")
                        if mark_name.startswith("response_end") or mark_name == "greeting_end":
                            is_agent_speaking = False

                    elif event == "stop":
                        logger.info(f"Stream stopped: {call_sid}")
                        if call_sid in active_calls:
                            del active_calls[call_sid]
                        break

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client")
            except Exception as e:
                logger.error(f"Error receiving audio: {e}", exc_info=True)

        async def process_speech():
            """Process speech-to-text and generate AI responses with sentence buffering"""
            nonlocal is_agent_speaking
            response_counter = 0

            try:
                async for transcript in voice_handler.transcribe_stream():
                    if not transcript.strip():
                        continue

                    logger.info(f"User: {transcript}")

                    # Handle interrupts: if user speaks while agent is talking
                    if is_agent_speaking:
                        logger.info(f"Interrupt detected: {transcript}")
                        await clear_twilio_audio()
                        is_agent_speaking = False

                    # Buffer for sentence-level TTS
                    sentence_buffer = ""

                    async for response_chunk in ai_agent.process_message(transcript):
                        if response_chunk.get("type") == "text":
                            text = response_chunk["content"]
                            sentence_buffer += text

                            # Check for sentence boundaries and synthesize complete sentences
                            while True:
                                boundary = _find_sentence_boundary(sentence_buffer)
                                if boundary == -1:
                                    break

                                # Extract and synthesize the complete sentence
                                sentence = sentence_buffer[:boundary].strip()
                                sentence_buffer = sentence_buffer[boundary:]

                                if sentence:
                                    await synthesize_and_send(sentence)

                        elif response_chunk.get("type") == "tool_call":
                            tool_name = response_chunk["name"]
                            logger.info(f"Executing tool: {tool_name}")

                        elif response_chunk.get("type") == "error":
                            error_msg = response_chunk["content"]
                            await synthesize_and_send(error_msg)

                    # Flush remaining buffer (last sentence may not end with punctuation)
                    if sentence_buffer.strip():
                        await synthesize_and_send(sentence_buffer.strip())

                    # Mark end of this response for interrupt tracking
                    response_counter += 1
                    await send_mark(f"response_end_{response_counter}")

            except asyncio.CancelledError:
                logger.info("Speech processing cancelled")
            except Exception as e:
                logger.error(f"Error processing speech: {e}", exc_info=True)

        # Run both tasks concurrently
        tasks = [
            asyncio.create_task(receive_audio()),
            asyncio.create_task(process_speech())
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)

    finally:
        if call_sid and call_sid in active_calls:
            del active_calls[call_sid]

        if voice_handler:
            await voice_handler.cleanup()

        if ai_agent:
            await ai_agent.cleanup()

        logger.info(f"WebSocket connection closed: {call_sid}")


def _find_sentence_boundary(text: str) -> int:
    """
    Find the position of the first sentence boundary in text.
    Returns the index just past the boundary, or -1 if no boundary found.
    Handles common sentence endings followed by space or newline.
    """
    for punct in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
        idx = text.find(punct)
        if idx != -1:
            return idx + len(punct)
    return -1


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint"""
    return {
        "active_calls": len(active_calls),
        "total_documents": knowledge_base.document_count if knowledge_base else 0,
        "uptime_seconds": (datetime.utcnow() - app.state.start_time).total_seconds() if hasattr(app.state, "start_time") else 0
    }


if __name__ == "__main__":
    # Run server
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
