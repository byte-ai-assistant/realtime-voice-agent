"""
Real-Time Voice AI Agent - Main Server
Handles Twilio voice calls with WebSocket streaming
"""

import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
import uvicorn
from dotenv import load_dotenv

from websockets.exceptions import ConnectionClosedError as WsClosedError
from voice_handler import VoiceHandler
from ai_agent import AIAgent
from knowledge_base import KnowledgeBase
from tools import AppointmentManager, EscalationHandler

# ---------------------------------------------------------------------------
# Voice Activity Detection (VAD) for instant interrupt detection.
# Decodes mu-law audio and checks RMS energy — runs on raw Twilio frames,
# bypassing Deepgram's 200-350ms pipeline entirely (~60ms latency).
# ---------------------------------------------------------------------------
_MULAW_DECODE = [0] * 256
for _i in range(256):
    _v = ~_i & 0xFF
    _sign = _v & 0x80
    _exp = (_v >> 4) & 0x07
    _man = _v & 0x0F
    _mag = ((_man << 3) + 0x84) << _exp
    _mag -= 0x84
    _MULAW_DECODE[_i] = -_mag if _sign else _mag

_VAD_THRESHOLD = 500       # RMS energy threshold (16-bit linear PCM scale)
_VAD_FRAMES_REQUIRED = 3   # Consecutive frames needed (~60ms at 20ms/frame)


def _audio_rms(data: bytes) -> float:
    """RMS energy of a mu-law audio frame."""
    if not data:
        return 0.0
    sq_sum = sum(_MULAW_DECODE[b] ** 2 for b in data)
    return (sq_sum / len(data)) ** 0.5


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
    app.state.start_time = datetime.now(timezone.utc)

    logger.info("Starting Real-Time Voice AI Agent...")

    # Initialize knowledge base
    try:
        kb_path = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge/sample_kb.json")
        knowledge_base = KnowledgeBase()
        await knowledge_base.initialize(kb_path)
        logger.info(f"Knowledge base initialized with {knowledge_base.document_count} documents")
    except Exception as e:
        logger.warning(f"Knowledge base initialization failed: {e}")
        logger.warning("Server will run without RAG - AI agent will use its built-in knowledge only")
        knowledge_base = None

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


@app.post("/")
async def root_voice_webhook(request: Request):
    """
    Handle Twilio incoming call webhooks at the root path.
    Twilio is often configured to POST to the root URL (e.g. ngrok URL).
    Delegates to the same logic as /webhook/voice.
    """
    return await voice_webhook(request)


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
            vad_frames = 0  # consecutive high-energy frames

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
                            "started_at": datetime.now(timezone.utc).isoformat()
                        }

                        # Synthesize and send greeting audio to caller
                        greeting_text = await ai_agent.send_greeting()
                        await synthesize_and_send(greeting_text)
                        await send_mark("greeting_end")

                    elif event == "media":
                        # Decode audio from Twilio (base64 mu-law)
                        payload = data["media"]["payload"]
                        audio_data = base64.b64decode(payload)

                        # --- VAD: instant interrupt detection on raw audio ---
                        if is_agent_speaking:
                            if _audio_rms(audio_data) > _VAD_THRESHOLD:
                                vad_frames += 1
                                if vad_frames >= _VAD_FRAMES_REQUIRED:
                                    logger.info("VAD interrupt: caller speech detected")
                                    await clear_twilio_audio()
                                    voice_handler.speech_detected.set()
                                    is_agent_speaking = False
                                    vad_frames = 0
                            else:
                                vad_frames = 0
                        else:
                            vad_frames = 0

                        # Process audio through voice handler (always, for STT)
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
            """
            Process speech-to-text and generate AI responses.

            Architecture: the response runs as a background task so we can
            continuously monitor the transcript queue.  If the user speaks
            while the agent is still responding, the response task is
            cancelled immediately, Twilio audio is cleared, conversation
            history is rolled back, and the new transcript is processed.
            """
            nonlocal is_agent_speaking
            response_counter = 0

            # Pre-warm a TTS WebSocket so it's ready for the first transcript
            pending_tts_stream = None
            try:
                pending_tts_stream = voice_handler.create_tts_stream()
                await pending_tts_stream.connect()
            except Exception as e:
                logger.debug(f"TTS pre-warm failed (will retry inline): {e}")
                pending_tts_stream = None

            try:
                while True:
                    # Wait for a final transcript
                    transcript = await voice_handler.transcript_queue.get()
                    if not transcript.strip():
                        continue

                    logger.info(f"User: {transcript}")

                    # If agent is still speaking (greeting or previous response
                    # still playing in Twilio buffer), interrupt immediately.
                    if is_agent_speaking:
                        logger.info(f"Interrupt during playback: {transcript}")
                        await clear_twilio_audio()
                        is_agent_speaking = False

                    voice_handler.speech_detected.clear()
                    is_agent_speaking = True
                    history_checkpoint = len(ai_agent.conversation_history)

                    # Use the pre-warmed TTS connection if available, otherwise connect now
                    tts_stream = None
                    use_input_streaming = True

                    if pending_tts_stream and pending_tts_stream.ws and pending_tts_stream.ws.open:
                        tts_stream = pending_tts_stream
                        pending_tts_stream = None
                    else:
                        if pending_tts_stream:
                            await pending_tts_stream.close()
                            pending_tts_stream = None
                        try:
                            tts_stream = voice_handler.create_tts_stream()
                            await tts_stream.connect()
                        except Exception as e:
                            logger.warning(f"ElevenLabs WS connect failed, using REST fallback: {e}")
                            use_input_streaming = False

                    if use_input_streaming and tts_stream:
                        # Speculative execution: check queue before first audio
                        # reaches caller to catch Deepgram split-utterances.
                        extra_parts = []
                        audio_started = False

                        async def send_audio_guarded(chunk):
                            nonlocal audio_started
                            if not audio_started:
                                while not voice_handler.transcript_queue.empty():
                                    try:
                                        part = voice_handler.transcript_queue.get_nowait()
                                        if part.strip():
                                            extra_parts.append(part)
                                    except asyncio.QueueEmpty:
                                        break
                                if extra_parts:
                                    raise _TranscriptExtended()
                                audio_started = True
                            await send_audio_to_twilio(chunk)

                        async def do_full_response():
                            """Run the full response pipeline (retriable on stale TTS)."""
                            nonlocal transcript, tts_stream
                            try:
                                await _process_with_input_streaming(
                                    ai_agent, transcript, tts_stream,
                                    send_audio_guarded
                                )
                            except _TranscriptExtended:
                                ai_agent.conversation_history = ai_agent.conversation_history[:history_checkpoint]
                                transcript += " " + " ".join(extra_parts)
                                logger.info(f"Transcript extended before audio sent, reprocessing: {transcript}")
                                await tts_stream.close()
                                tts_stream = voice_handler.create_tts_stream()
                                await tts_stream.connect()
                                await _process_with_input_streaming(
                                    ai_agent, transcript, tts_stream,
                                    send_audio_to_twilio
                                )
                                return
                            except WsClosedError:
                                logger.warning("TTS WebSocket closed mid-stream, retrying with fresh connection")
                                ai_agent.conversation_history = ai_agent.conversation_history[:history_checkpoint]
                                await tts_stream.close()
                                tts_stream = voice_handler.create_tts_stream()
                                await tts_stream.connect()
                                await _process_with_input_streaming(
                                    ai_agent, transcript, tts_stream,
                                    send_audio_to_twilio
                                )
                                return

                        # Run response as a cancellable background task so we
                        # can monitor the transcript queue for interrupts.
                        response_task = asyncio.create_task(do_full_response())

                        # Race: response completion vs user speaking (interrupt).
                        # Uses speech_detected (fires on interim results) for
                        # near-instant reaction (~100ms) instead of waiting for
                        # final transcripts (~400ms).
                        interrupted = False

                        while not response_task.done():
                            speech_waiter = asyncio.create_task(
                                voice_handler.speech_detected.wait()
                            )
                            done, _ = await asyncio.wait(
                                {response_task, speech_waiter},
                                return_when=asyncio.FIRST_COMPLETED,
                            )

                            if speech_waiter in done and response_task not in done:
                                # User started speaking — stop audio IMMEDIATELY,
                                # then cancel the response task.
                                interrupted = True
                                await clear_twilio_audio()
                                voice_handler.speech_detected.clear()
                                response_task.cancel()
                                try:
                                    await response_task
                                except (asyncio.CancelledError, Exception):
                                    pass
                                break

                            if response_task in done:
                                if not speech_waiter.done():
                                    speech_waiter.cancel()
                                    try:
                                        await speech_waiter
                                    except asyncio.CancelledError:
                                        pass
                                # Propagate response errors
                                if not response_task.cancelled():
                                    try:
                                        response_task.result()
                                    except Exception as e:
                                        logger.error(f"Response error: {e}", exc_info=True)
                                break

                        if interrupted:
                            logger.info("Interrupt: user spoke during response generation")
                            ai_agent.conversation_history = ai_agent.conversation_history[:history_checkpoint]
                            is_agent_speaking = False
                            try:
                                await tts_stream.close()
                            except Exception:
                                pass
                            # Don't re-queue — final transcript arrives via queue naturally
                            continue

                        await tts_stream.close()
                    else:
                        # Fallback: sentence-by-sentence REST TTS
                        await _process_with_sentence_buffering(
                            ai_agent, transcript, synthesize_and_send
                        )

                    # Response generation finished — audio is still playing in
                    # Twilio's buffer.  Send a mark so we know when playback
                    # ends, then monitor for user interrupts in the meantime.
                    response_counter += 1
                    await send_mark(f"response_end_{response_counter}")

                    # Monitor for interrupts while Twilio plays the buffered audio.
                    # Uses speech_detected (interim results) for near-instant reaction.
                    # The mark handler in receive_audio sets is_agent_speaking=False
                    # once Twilio confirms playback is done.
                    while is_agent_speaking:
                        try:
                            await asyncio.wait_for(
                                voice_handler.speech_detected.wait(),
                                timeout=0.1
                            )
                            # User started speaking during playback — stop immediately
                            logger.info("Interrupt during Twilio playback")
                            voice_handler.speech_detected.clear()
                            await clear_twilio_audio()
                            is_agent_speaking = False
                            break
                        except asyncio.TimeoutError:
                            continue

                    is_agent_speaking = False

                    # Pre-warm the next TTS connection while idle
                    try:
                        pending_tts_stream = voice_handler.create_tts_stream()
                        await pending_tts_stream.connect()
                    except Exception:
                        pending_tts_stream = None

            except asyncio.CancelledError:
                logger.info("Speech processing cancelled")
            except Exception as e:
                logger.error(f"Error processing speech: {e}", exc_info=True)
            finally:
                if pending_tts_stream:
                    await pending_tts_stream.close()

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


class _TranscriptExtended(Exception):
    """Raised when additional transcript parts arrive before audio reaches the caller."""
    pass


async def _process_with_input_streaming(ai_agent, transcript, tts_stream, send_audio_fn):
    """
    Stream Claude tokens directly to ElevenLabs via WebSocket.
    Audio generation starts before the full response is available.
    Supports cancellation — the caller can cancel this coroutine's task
    and the internal audio_task will be cleaned up automatically.
    """
    # Forward audio from ElevenLabs WS to Twilio in background.
    # If send_audio_fn raises _TranscriptExtended, we set the aborted
    # event so the Claude streaming loop exits early instead of wasting tokens.
    aborted = asyncio.Event()

    async def forward_audio():
        try:
            async for audio_chunk in tts_stream.get_audio_chunks():
                await send_audio_fn(audio_chunk)
        except _TranscriptExtended:
            aborted.set()
            raise

    audio_task = asyncio.create_task(forward_audio())

    try:
        # Stream Claude tokens → ElevenLabs WS
        text_buffer = ""

        async for chunk in ai_agent.process_message(transcript):
            # If audio forwarding failed (e.g. _TranscriptExtended), stop streaming
            if aborted.is_set():
                break

            if chunk.get("type") == "text":
                text_buffer += chunk["content"]

                has_punct = any(p in text_buffer for p in '.,!?;:\n')
                if has_punct or len(text_buffer) >= 15:
                    await tts_stream.send_text(text_buffer, try_trigger=has_punct)
                    text_buffer = ""

            elif chunk.get("type") == "tool_call":
                if text_buffer:
                    await tts_stream.send_text(text_buffer, try_trigger=True)
                    text_buffer = ""
                logger.info(f"Executing tool: {chunk['name']}")

            elif chunk.get("type") == "error":
                await tts_stream.send_text(chunk["content"], try_trigger=True)

        if not aborted.is_set():
            if text_buffer:
                await tts_stream.send_text(text_buffer, try_trigger=True)
            await tts_stream.flush()

        # Wait for all audio to be forwarded to Twilio
        await audio_task

    except (asyncio.CancelledError, Exception):
        # On cancellation or any error, clean up the detached audio task
        if not audio_task.done():
            audio_task.cancel()
            try:
                await audio_task
            except (asyncio.CancelledError, _TranscriptExtended, Exception):
                pass
        raise


async def _process_with_sentence_buffering(ai_agent, transcript, synthesize_and_send_fn):
    """Fallback: sentence-by-sentence REST TTS (original approach)."""
    sentence_buffer = ""

    async for chunk in ai_agent.process_message(transcript):
        if chunk.get("type") == "text":
            sentence_buffer += chunk["content"]

            while True:
                boundary = _find_sentence_boundary(sentence_buffer)
                if boundary == -1:
                    break
                sentence = sentence_buffer[:boundary].strip()
                sentence_buffer = sentence_buffer[boundary:]
                if sentence:
                    await synthesize_and_send_fn(sentence)

        elif chunk.get("type") == "tool_call":
            logger.info(f"Executing tool: {chunk['name']}")

        elif chunk.get("type") == "error":
            await synthesize_and_send_fn(chunk["content"])

    if sentence_buffer.strip():
        await synthesize_and_send_fn(sentence_buffer.strip())


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
        "uptime_seconds": (datetime.now(timezone.utc) - app.state.start_time).total_seconds() if hasattr(app.state, "start_time") else 0
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
