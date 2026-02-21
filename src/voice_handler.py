"""
Voice Handler - Audio streaming, STT, and TTS
Manages bidirectional audio streaming with Deepgram and ElevenLabs
"""

import asyncio
import os
import logging
from typing import AsyncIterator, Optional
from io import BytesIO

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from elevenlabs.client import ElevenLabs
import websockets as ws_lib
import base64 as b64_lib
import json as json_lib

logger = logging.getLogger(__name__)


class VoiceHandler:
    """Handles audio streaming, speech-to-text, and text-to-speech"""

    def __init__(self):
        self.deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
        self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

        if not self.deepgram_api_key:
            raise ValueError("DEEPGRAM_API_KEY not set")
        if not self.elevenlabs_api_key:
            raise ValueError("ELEVENLABS_API_KEY not set")

        # Initialize clients
        self.deepgram_client = DeepgramClient(
            self.deepgram_api_key,
            config=DeepgramClientOptions(options={"keepalive": "true"})
        )
        self.elevenlabs_client = ElevenLabs(api_key=self.elevenlabs_api_key)

        # Audio buffers
        self.audio_buffer = asyncio.Queue()
        self.transcript_queue = asyncio.Queue()

        # Fires on ANY detected speech (interim or final) for instant interrupts.
        # Much faster than waiting for final transcripts (~100ms vs ~400ms).
        self.speech_detected = asyncio.Event()

        # Deepgram connection
        self.dg_connection = None
        self.is_transcribing = False

        logger.info("VoiceHandler initialized")

    async def process_incoming_audio(self, audio_data: bytes):
        """
        Process incoming audio from Twilio
        Audio format: mu-law, 8kHz, mono
        """
        try:
            # Add to buffer for STT
            await self.audio_buffer.put(audio_data)

            # Start transcription if not already running
            # Set flag BEFORE creating task to prevent race condition
            if not self.is_transcribing:
                self.is_transcribing = True
                asyncio.create_task(self._start_transcription())

        except Exception as e:
            logger.error(f"Error processing audio: {e}")

    async def _start_transcription(self):
        """Start Deepgram streaming transcription"""
        try:
            # Configure Deepgram options
            options = LiveOptions(
                model="nova-2",
                language="es",
                punctuate=True,
                interim_results=True,
                endpointing=300,  # Balance between fast finalization and avoiding mid-sentence splits
                utterance_end_ms=1000,  # Detect end-of-utterance for multi-sentence input
                smart_format=True,
                encoding="mulaw",
                sample_rate=8000,
                channels=1
            )

            # Create connection
            self.dg_connection = self.deepgram_client.listen.asynclive.v("1")

            # Capture outer self for closure - avoids parameter shadowing bug
            handler = self

            async def on_message(_self, result, **kwargs):
                """Handle transcription results from Deepgram"""
                try:
                    sentence = result.channel.alternatives[0].transcript
                    if sentence.strip():
                        # Signal speech immediately (interim or final) for interrupt detection
                        handler.speech_detected.set()
                        # Only enqueue final results for AI processing
                        if result.is_final:
                            await handler.transcript_queue.put(sentence)
                            logger.info(f"Transcript (final): {sentence}")
                        else:
                            logger.debug(f"Transcript (interim): {sentence}")
                except Exception as e:
                    logger.error(f"Transcription callback error: {e}")

            async def on_error(_self, error, **kwargs):
                """Handle Deepgram errors"""
                logger.error(f"Deepgram error: {error}")

            self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
            self.dg_connection.on(LiveTranscriptionEvents.Error, on_error)

            # Start connection
            if not await self.dg_connection.start(options):
                logger.error("Failed to start Deepgram connection")
                return

            logger.info("Deepgram streaming started")

            # Stream audio to Deepgram
            try:
                while self.is_transcribing:
                    try:
                        # Get audio from buffer with timeout
                        audio_chunk = await asyncio.wait_for(
                            self.audio_buffer.get(),
                            timeout=5.0
                        )

                        # Send to Deepgram
                        await self.dg_connection.send(audio_chunk)

                    except asyncio.TimeoutError:
                        # Keep connection alive during silence
                        await self.dg_connection.keep_alive()
                        continue

            except Exception as e:
                logger.error(f"Error streaming to Deepgram: {e}")
            finally:
                # Close connection
                await self.dg_connection.finish()

        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
        finally:
            self.is_transcribing = False

    async def transcribe_stream(self) -> AsyncIterator[str]:
        """
        Yield transcribed text as it becomes available
        """
        try:
            while True:
                # Get transcript from queue
                transcript = await self.transcript_queue.get()
                yield transcript

        except asyncio.CancelledError:
            logger.info("Transcription stream cancelled")
        except Exception as e:
            logger.error(f"Error in transcribe stream: {e}")

    async def synthesize_speech(self, text: str) -> AsyncIterator[bytes]:
        """
        Convert text to speech using ElevenLabs
        Returns audio chunks in mu-law format for Twilio
        """
        try:
            logger.info(f"Synthesizing: {text[:80]}...")

            # Generate audio with ElevenLabs streaming API (v1.x SDK)
            audio_stream = self.elevenlabs_client.text_to_speech.convert_as_stream(
                text=text,
                voice_id=self.voice_id,
                model_id="eleven_turbo_v2_5",
                output_format="ulaw_8000",
                optimize_streaming_latency="4",
            )

            # Stream audio chunks without artificial delay
            for chunk in audio_stream:
                if chunk:
                    yield chunk

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            # Return silence on error
            yield b'\x00' * 160

    def create_tts_stream(self) -> "ElevenLabsInputStreamer":
        """Create a new ElevenLabs WebSocket-based input streamer for lowest latency TTS"""
        return ElevenLabsInputStreamer(
            api_key=self.elevenlabs_api_key,
            voice_id=self.voice_id,
        )

    async def cleanup(self):
        """Clean up resources"""
        try:
            self.is_transcribing = False

            if self.dg_connection:
                await self.dg_connection.finish()

            logger.info("VoiceHandler cleaned up")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")


class ElevenLabsInputStreamer:
    """
    WebSocket-based text input streaming for ElevenLabs TTS.

    Instead of sending complete sentences via REST (250ms+ per call),
    this streams text tokens directly to ElevenLabs as they arrive
    from the LLM. ElevenLabs begins audio synthesis immediately,
    producing audio output before the full text is available.

    Protocol:
    1. Connect to wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input
    2. Send BOS (beginning of stream) with voice settings
    3. Send text chunks as they arrive from LLM
    4. Send EOS (empty text) to signal completion
    5. Receive audio chunks throughout
    """

    def __init__(self, api_key: str, voice_id: str,
                 model_id: str = "eleven_turbo_v2_5"):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.ws = None
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self._receive_task = None

    async def connect(self):
        """Establish WebSocket connection to ElevenLabs streaming endpoint"""
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/"
            f"{self.voice_id}/stream-input"
            f"?model_id={self.model_id}"
            f"&output_format=ulaw_8000"
        )
        self.ws = await ws_lib.connect(url)

        # Send BOS (beginning of stream) message with voice config
        await self.ws.send(json_lib.dumps({
            "text": " ",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
            "generation_config": {
                # Aggressive schedule: minimum allowed by ElevenLabs is 50.
                # Smaller values get the first audio chunk generated sooner.
                "chunk_length_schedule": [50, 75, 100, 125, 150]
            },
            "xi_api_key": self.api_key,
        }))

        # Start receiving audio in background
        self._receive_task = asyncio.create_task(self._receive_audio())
        logger.info("ElevenLabs input streaming connected")

    async def send_text(self, text: str, try_trigger: bool = False):
        """
        Send a text chunk to ElevenLabs for synthesis.
        Set try_trigger=True at natural boundaries (punctuation) to
        encourage immediate audio generation.
        """
        if self.ws and text:
            msg = {"text": text}
            if try_trigger:
                msg["try_trigger_generation"] = True
            await self.ws.send(json_lib.dumps(msg))

    async def flush(self):
        """Send EOS (end of stream) to signal no more text is coming"""
        if self.ws:
            await self.ws.send(json_lib.dumps({"text": ""}))

    async def _receive_audio(self):
        """Receive audio chunks from ElevenLabs WebSocket"""
        try:
            async for message in self.ws:
                data = json_lib.loads(message)
                if data.get("audio"):
                    audio_bytes = b64_lib.b64decode(data["audio"])
                    await self.audio_queue.put(audio_bytes)
                if data.get("isFinal"):
                    break
        except ws_lib.exceptions.ConnectionClosed:
            logger.debug("ElevenLabs WS connection closed")
        except Exception as e:
            logger.error(f"ElevenLabs WS receive error: {e}")
        finally:
            await self.audio_queue.put(None)  # Signal end of audio

    async def get_audio_chunks(self):
        """Yield audio chunks as they arrive from ElevenLabs"""
        while True:
            chunk = await self.audio_queue.get()
            if chunk is None:
                break
            yield chunk

    async def close(self):
        """Close the WebSocket connection"""
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
