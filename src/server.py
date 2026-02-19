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
    
    logger.info("🚀 Starting Real-Time Voice AI Agent...")
    
    # Initialize knowledge base
    try:
        kb_path = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge/sample_kb.json")
        knowledge_base = KnowledgeBase()
        await knowledge_base.initialize(kb_path)
        logger.info(f"✅ Knowledge base initialized with {knowledge_base.document_count} documents")
    except Exception as e:
        logger.error(f"❌ Failed to initialize knowledge base: {e}")
        raise
    
    logger.info("✅ Server ready to accept calls!")


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


@app.post("/webhook/voice")
async def voice_webhook(request: Request):
    """
    Twilio webhook endpoint for incoming calls
    Returns TwiML to establish WebSocket connection
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    from_number = form_data.get("From")
    
    logger.info(f"📞 Incoming call: {call_sid} from {from_number}")
    
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
    voice_handler = None
    ai_agent = None
    
    try:
        logger.info("🔌 WebSocket connection established")
        
        # Create handler instances
        voice_handler = VoiceHandler()
        ai_agent = AIAgent(knowledge_base=knowledge_base)
        
        # Start background tasks
        tasks = []
        
        async def receive_audio():
            """Receive audio from Twilio"""
            nonlocal call_sid
            
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")
                    
                    if event == "start":
                        call_sid = data["start"]["callSid"]
                        stream_sid = data["start"]["streamSid"]
                        logger.info(f"📡 Stream started: {stream_sid}")
                        active_calls[call_sid] = {
                            "stream_sid": stream_sid,
                            "started_at": datetime.utcnow().isoformat()
                        }
                        
                        # Send greeting
                        await ai_agent.send_greeting()
                        
                    elif event == "media":
                        # Decode audio from Twilio (base64 μ-law)
                        payload = data["media"]["payload"]
                        audio_data = base64.b64decode(payload)
                        
                        # Process audio through voice handler
                        await voice_handler.process_incoming_audio(audio_data)
                        
                    elif event == "stop":
                        logger.info(f"📡 Stream stopped: {call_sid}")
                        if call_sid in active_calls:
                            del active_calls[call_sid]
                        break
                        
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client")
            except Exception as e:
                logger.error(f"Error receiving audio: {e}", exc_info=True)
        
        async def process_speech():
            """Process speech-to-text and generate AI responses"""
            try:
                async for transcript in voice_handler.transcribe_stream():
                    if not transcript.strip():
                        continue
                    
                    logger.info(f"👤 User: {transcript}")
                    
                    # Get AI response
                    async for response_chunk in ai_agent.process_message(transcript):
                        if response_chunk.get("type") == "text":
                            text = response_chunk["content"]
                            
                            # Convert text to speech
                            async for audio_chunk in voice_handler.synthesize_speech(text):
                                # Encode audio for Twilio (μ-law, base64)
                                payload = base64.b64encode(audio_chunk).decode("utf-8")
                                
                                # Send audio to Twilio
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": active_calls[call_sid]["stream_sid"],
                                    "media": {
                                        "payload": payload
                                    }
                                })
                        
                        elif response_chunk.get("type") == "tool_call":
                            tool_name = response_chunk["name"]
                            logger.info(f"🔧 Executing tool: {tool_name}")
                            
            except Exception as e:
                logger.error(f"Error processing speech: {e}", exc_info=True)
        
        # Run both tasks concurrently
        tasks = [
            asyncio.create_task(receive_audio()),
            asyncio.create_task(process_speech())
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}", exc_info=True)
    
    finally:
        if call_sid and call_sid in active_calls:
            del active_calls[call_sid]
        
        if voice_handler:
            await voice_handler.cleanup()
        
        if ai_agent:
            await ai_agent.cleanup()
        
        logger.info(f"🔌 WebSocket connection closed: {call_sid}")


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint"""
    return {
        "active_calls": len(active_calls),
        "total_documents": knowledge_base.document_count if knowledge_base else 0,
        "uptime_seconds": (datetime.utcnow() - app.state.start_time).total_seconds() if hasattr(app.state, "start_time") else 0
    }


if __name__ == "__main__":
    # Store start time
    app.state.start_time = datetime.utcnow()
    
    # Run server
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"🚀 Starting server on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )
