#!/usr/bin/env python3
"""
WebSocket Test Client - Simulates Twilio's Media Stream protocol.

Tests the full audio pipeline (Deepgram → Claude → ElevenLabs) locally
without needing a phone number, Twilio account, or ngrok.

Usage:
    # Start the server first:
    ENABLE_TEST_ENDPOINTS=true python src/server.py

    # Then run this script:
    python scripts/test_call.py                     # Listen for greeting, then interactive text input
    python scripts/test_call.py --audio sample.wav  # Send a pre-recorded WAV file
    python scripts/test_call.py --save output.raw   # Save received audio to file

    # Or test without any audio (just AI + RAG + tools):
    curl -X POST http://localhost:8000/test/chat \\
         -H "Content-Type: application/json" \\
         -d '{"text": "What are your prices?"}'

Full phone test (Twilio + ngrok):
    1. Fill in .env with API keys (Twilio, Deepgram, ElevenLabs, Anthropic)
    2. python src/server.py
    3. ngrok http 8000
    4. Set Twilio webhook: https://<ngrok-url>/webhook/voice (HTTP POST)
    5. Call your Twilio number
"""

import argparse
import asyncio
import base64
import json
import struct
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Error: websockets package required. Install with: pip install websockets")
    sys.exit(1)


# mu-law encoding table for converting linear PCM to mu-law
def linear_to_mulaw(sample: int) -> int:
    """Convert a 16-bit linear PCM sample to 8-bit mu-law"""
    MULAW_MAX = 0x1FFF
    MULAW_BIAS = 33
    sign = 0

    if sample < 0:
        sample = -sample
        sign = 0x80

    sample = min(sample + MULAW_BIAS, MULAW_MAX)

    exponent = 7
    for exp_val in [0x4000, 0x2000, 0x1000, 0x0800, 0x0400, 0x0200, 0x0100]:
        if sample >= exp_val:
            break
        exponent -= 1

    mantissa = (sample >> (exponent + 3)) & 0x0F
    mulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
    return mulaw_byte


def generate_silence_mulaw(duration_ms: int, sample_rate: int = 8000) -> bytes:
    """Generate silence in mu-law format"""
    num_samples = int(sample_rate * duration_ms / 1000)
    # mu-law silence is 0xFF (linear zero maps to 0xFF in mu-law)
    return bytes([0xFF] * num_samples)


def wav_to_mulaw(wav_path: str) -> bytes:
    """Read a WAV file and convert to mu-law 8kHz mono"""
    import wave

    with wave.open(wav_path, 'rb') as wf:
        if wf.getnchannels() != 1:
            print(f"Warning: WAV has {wf.getnchannels()} channels, using first channel only")
        if wf.getframerate() != 8000:
            print(f"Warning: WAV sample rate is {wf.getframerate()}, expected 8000 Hz")
            print("Audio may sound distorted. Resample with: ffmpeg -i input.wav -ar 8000 -ac 1 output.wav")

        frames = wf.readframes(wf.getnframes())
        sample_width = wf.getsampwidth()

    # Convert to 16-bit samples
    if sample_width == 1:
        samples = [(b - 128) * 256 for b in frames]
    elif sample_width == 2:
        samples = list(struct.unpack(f'<{len(frames)//2}h', frames))
    else:
        print(f"Unsupported sample width: {sample_width}")
        return b''

    # Convert each sample to mu-law
    mulaw_bytes = bytes([linear_to_mulaw(s) for s in samples])
    return mulaw_bytes


class TwilioSimulator:
    """Simulates Twilio's Media Stream WebSocket protocol"""

    def __init__(self, server_url: str = "ws://localhost:8000/ws/media",
                 save_path: str = None):
        self.server_url = server_url
        self.save_path = save_path
        self.call_sid = f"TEST_CALL_{int(time.time())}"
        self.stream_sid = f"TEST_STREAM_{int(time.time())}"
        self.ws = None
        self.received_audio = bytearray()
        self.is_connected = False
        self.greeting_received = asyncio.Event()

    async def connect(self):
        """Connect to the WebSocket server"""
        print(f"\nConnecting to {self.server_url}...")
        self.ws = await websockets.connect(self.server_url)
        self.is_connected = True
        print(f"Connected! Call SID: {self.call_sid}")

    async def send_start(self):
        """Send the Twilio 'start' event"""
        start_event = {
            "event": "start",
            "start": {
                "callSid": self.call_sid,
                "streamSid": self.stream_sid
            }
        }
        await self.ws.send(json.dumps(start_event))
        print("Sent 'start' event - waiting for greeting...")

    async def send_audio(self, audio_data: bytes, chunk_size: int = 160):
        """Send audio data as Twilio media events (160 bytes = 20ms at 8kHz)"""
        total_chunks = len(audio_data) // chunk_size
        print(f"Sending {len(audio_data)} bytes of audio ({total_chunks} chunks, ~{total_chunks * 20}ms)...")

        for i in range(0, len(audio_data), chunk_size):
            chunk = audio_data[i:i + chunk_size]
            payload = base64.b64encode(chunk).decode("utf-8")

            media_event = {
                "event": "media",
                "media": {
                    "payload": payload
                }
            }
            await self.ws.send(json.dumps(media_event))

            # Simulate real-time: 20ms per chunk
            await asyncio.sleep(0.02)

        print("Audio sent!")

    async def send_stop(self):
        """Send the Twilio 'stop' event"""
        stop_event = {"event": "stop"}
        await self.ws.send(json.dumps(stop_event))
        print("Sent 'stop' event")

    async def receive_messages(self):
        """Receive and process messages from the server"""
        audio_chunk_count = 0

        try:
            async for message in self.ws:
                data = json.loads(message)
                event = data.get("event")

                if event == "media":
                    # Decode and save audio
                    payload = data.get("media", {}).get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)
                        self.received_audio.extend(audio_bytes)
                        audio_chunk_count += 1

                        if audio_chunk_count % 50 == 0:
                            duration_ms = len(self.received_audio) / 8  # 8000 Hz = 8 bytes/ms
                            print(f"  Receiving audio... ({duration_ms:.0f}ms so far)")

                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name", "")
                    duration_ms = len(self.received_audio) / 8
                    print(f"  Mark: '{mark_name}' (total audio: {duration_ms:.0f}ms)")

                    if mark_name == "greeting_end":
                        self.greeting_received.set()

                elif event == "clear":
                    print("  Clear: Server cleared audio queue (interrupt)")

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            if self.is_connected:
                print(f"  Receive error: {e}")

        self.is_connected = False

    async def save_audio(self):
        """Save received audio to file"""
        if self.received_audio and self.save_path:
            Path(self.save_path).write_bytes(self.received_audio)
            duration_s = len(self.received_audio) / 8000
            print(f"\nSaved {len(self.received_audio)} bytes ({duration_s:.1f}s) to {self.save_path}")
            print(f"Play with: ffplay -f mulaw -ar 8000 -ac 1 {self.save_path}")
        elif self.received_audio:
            duration_s = len(self.received_audio) / 8000
            print(f"\nReceived {len(self.received_audio)} bytes of audio ({duration_s:.1f}s)")
            print("Use --save output.raw to save it")

    async def close(self):
        """Close the connection"""
        self.is_connected = False
        if self.ws:
            await self.ws.close()


async def run_audio_test(args):
    """Run a test with audio file input"""
    sim = TwilioSimulator(server_url=args.url, save_path=args.save)

    try:
        await sim.connect()

        # Start receiver task
        receiver = asyncio.create_task(sim.receive_messages())

        # Send start event
        await sim.send_start()

        # Wait for greeting
        print("Waiting for greeting audio...")
        try:
            await asyncio.wait_for(sim.greeting_received.wait(), timeout=15.0)
            print("Greeting received!")
        except asyncio.TimeoutError:
            print("Warning: No greeting received within 15s")

        # Send audio if provided
        if args.audio:
            print(f"\nSending audio from: {args.audio}")
            audio_data = wav_to_mulaw(args.audio)
            await sim.send_audio(audio_data)

            # Wait for response
            print("Waiting for AI response...")
            await asyncio.sleep(10)
        else:
            # Send silence to keep connection alive, wait for user
            print("\nNo audio file provided. Sending 2s of silence...")
            silence = generate_silence_mulaw(2000)
            await sim.send_audio(silence)
            await asyncio.sleep(5)

        # Stop
        await sim.send_stop()
        await asyncio.sleep(1)

        await sim.save_audio()

    except ConnectionRefusedError:
        print(f"\nError: Could not connect to {args.url}")
        print("Make sure the server is running: python src/server.py")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        await sim.close()


async def run_interactive(args):
    """Run interactive text mode - type messages, hear responses"""
    sim = TwilioSimulator(server_url=args.url, save_path=args.save)

    try:
        await sim.connect()

        # Start receiver task
        receiver = asyncio.create_task(sim.receive_messages())

        # Send start event
        await sim.send_start()

        # Wait for greeting
        print("Waiting for greeting audio...")
        try:
            await asyncio.wait_for(sim.greeting_received.wait(), timeout=15.0)
            print("Greeting received!")
        except asyncio.TimeoutError:
            print("Warning: No greeting received within 15s (server may need API keys)")

        print("\n" + "=" * 60)
        print("CONNECTION ACTIVE - Server is processing audio")
        print("The server expects audio input from Deepgram.")
        print("For text-only testing, use the /test/chat endpoint:")
        print("")
        print('  curl -X POST http://localhost:8000/test/chat \\')
        print('    -H "Content-Type: application/json" \\')
        print('    -d \'{"text": "What are your prices?"}\'')
        print("")
        print("Press Ctrl+C to end the call.")
        print("=" * 60 + "\n")

        # Keep connection alive
        try:
            while sim.is_connected:
                # Send keepalive silence every 5 seconds
                silence = generate_silence_mulaw(100)  # 100ms silence
                await sim.send_audio(silence)
                await asyncio.sleep(5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

        await sim.send_stop()
        await asyncio.sleep(1)
        await sim.save_audio()

    except ConnectionRefusedError:
        print(f"\nError: Could not connect to {args.url}")
        print("Make sure the server is running: python src/server.py")
    except KeyboardInterrupt:
        print("\n\nEnding call...")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        await sim.close()


def main():
    parser = argparse.ArgumentParser(
        description="Test the Voice AI Agent by simulating Twilio's WebSocket protocol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_call.py                         # Connect and listen for greeting
  python scripts/test_call.py --audio sample.wav      # Send audio file
  python scripts/test_call.py --save output.raw       # Save received audio

  # Play saved audio:
  ffplay -f mulaw -ar 8000 -ac 1 output.raw

  # Text-only test (no audio APIs needed):
  curl -X POST http://localhost:8000/test/chat \\
    -H "Content-Type: application/json" \\
    -d '{"text": "What are your prices?"}'

Full phone test (Twilio + ngrok):
  1. Fill in .env with API keys
  2. python src/server.py
  3. ngrok http 8000
  4. Set Twilio webhook: https://<ngrok-url>/webhook/voice
  5. Call your Twilio number
"""
    )

    parser.add_argument("--url", default="ws://localhost:8000/ws/media",
                        help="WebSocket server URL (default: ws://localhost:8000/ws/media)")
    parser.add_argument("--audio", type=str,
                        help="Path to WAV file to send (must be 8kHz mono)")
    parser.add_argument("--save", type=str,
                        help="Save received audio to file (mu-law raw format)")

    args = parser.parse_args()

    if args.audio:
        asyncio.run(run_audio_test(args))
    else:
        asyncio.run(run_interactive(args))


if __name__ == "__main__":
    main()
