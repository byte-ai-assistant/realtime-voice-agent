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
                language="en-US",
                punctuate=True,
                interim_results=True,
                endpointing=300,
                smart_format=True,
                encoding="mulaw",
                sample_rate=8000,
                channels=1
            )

            # Create connection
            self.dg_connection = self.deepgram_client.listen.asynclive.v("1")

            # Capture outer self for closure - avoids parameter shadowing bug
            handler = self

            async def on_message(result, **kwargs):
                """Handle transcription results from Deepgram"""
                try:
                    sentence = result.channel.alternatives[0].transcript
                    if sentence.strip():
                        # Only enqueue final results for AI processing
                        if result.is_final:
                            await handler.transcript_queue.put(sentence)
                            logger.info(f"Transcript (final): {sentence}")
                        else:
                            logger.debug(f"Transcript (interim): {sentence}")
                except Exception as e:
                    logger.error(f"Transcription callback error: {e}")

            async def on_error(error, **kwargs):
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

            # Stream audio chunks
            for chunk in audio_stream:
                if chunk:
                    yield chunk
                    # Small delay to avoid overwhelming the WebSocket
                    await asyncio.sleep(0.01)

        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            # Return silence on error
            yield b'\x00' * 160

    async def cleanup(self):
        """Clean up resources"""
        try:
            self.is_transcribing = False

            if self.dg_connection:
                await self.dg_connection.finish()

            logger.info("VoiceHandler cleaned up")

        except Exception as e:
            logger.error(f"Cleanup error: {e}")
