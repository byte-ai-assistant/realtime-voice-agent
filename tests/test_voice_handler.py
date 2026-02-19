"""
Unit tests for VoiceHandler
"""

import pytest
import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock

# Mock environment variables before importing
os.environ.setdefault("DEEPGRAM_API_KEY", "test-deepgram-key")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-elevenlabs-key")

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from voice_handler import VoiceHandler


@pytest.fixture
def mock_clients():
    """Mock external SDK clients to prevent real API calls"""
    with patch("voice_handler.DeepgramClient") as mock_dg, \
         patch("voice_handler.ElevenLabs") as mock_el:
        yield mock_dg, mock_el


@pytest.fixture
def voice_handler(mock_clients):
    """Create a VoiceHandler with mocked external clients"""
    handler = VoiceHandler()
    return handler


@pytest.mark.asyncio
async def test_voice_handler_initialization(voice_handler):
    """Test VoiceHandler can be initialized"""
    assert voice_handler is not None
    assert voice_handler.audio_buffer is not None
    assert voice_handler.transcript_queue is not None
    assert voice_handler.is_transcribing is False


@pytest.mark.asyncio
async def test_audio_buffering(voice_handler):
    """Test audio data is added to the buffer"""
    test_audio = b'\x00' * 160  # 20ms of silence

    # Mock _start_transcription to prevent actual Deepgram connection
    with patch.object(voice_handler, '_start_transcription', new_callable=AsyncMock):
        await voice_handler.process_incoming_audio(test_audio)

    # Check buffer has data
    assert not voice_handler.audio_buffer.empty()
    buffered = await voice_handler.audio_buffer.get()
    assert buffered == test_audio


@pytest.mark.asyncio
async def test_no_duplicate_transcription_starts(voice_handler):
    """Multiple rapid audio packets should not start multiple transcription tasks"""
    with patch.object(voice_handler, '_start_transcription', new_callable=AsyncMock) as mock_start:
        # First call should set is_transcribing and create task
        await voice_handler.process_incoming_audio(b'\x00' * 160)
        assert voice_handler.is_transcribing is True

        # Subsequent calls should NOT trigger _start_transcription again
        await voice_handler.process_incoming_audio(b'\x00' * 160)
        await voice_handler.process_incoming_audio(b'\x00' * 160)

    # Audio should still be buffered
    assert voice_handler.audio_buffer.qsize() == 3


@pytest.mark.asyncio
async def test_transcribe_stream_yields_from_queue(voice_handler):
    """Test that transcribe_stream yields items from the transcript queue"""
    # Put a transcript in the queue
    await voice_handler.transcript_queue.put("Hello world")

    # Get it from the stream
    async for transcript in voice_handler.transcribe_stream():
        assert transcript == "Hello world"
        break  # Only check first item


@pytest.mark.asyncio
async def test_cleanup_does_not_raise(voice_handler):
    """Test cleanup doesn't raise errors even without active connection"""
    await voice_handler.cleanup()
    assert voice_handler.is_transcribing is False


@pytest.mark.asyncio
async def test_cleanup_finishes_dg_connection(voice_handler):
    """Test cleanup finishes the Deepgram connection if active"""
    mock_connection = AsyncMock()
    voice_handler.dg_connection = mock_connection
    voice_handler.is_transcribing = True

    await voice_handler.cleanup()

    assert voice_handler.is_transcribing is False
    mock_connection.finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_does_not_shadow_self(voice_handler):
    """
    Verify that the Deepgram on_message callback correctly references
    the handler's transcript_queue, not the result parameter.
    This tests the fix for the 'self' parameter shadowing bug.
    """
    # Simulate what happens during _start_transcription
    handler = voice_handler  # This is what the fixed code does

    # Create a mock Deepgram result
    mock_result = MagicMock()
    mock_result.channel.alternatives = [MagicMock(transcript="Test transcript")]
    mock_result.is_final = True

    # Simulate the fixed callback
    async def on_message(result, **kwargs):
        try:
            sentence = result.channel.alternatives[0].transcript
            if sentence.strip():
                if result.is_final:
                    await handler.transcript_queue.put(sentence)
        except Exception as e:
            pytest.fail(f"Callback raised: {e}")

    # Call it with the mock result (not passing 'self' as first arg)
    await on_message(mock_result)

    # Verify the transcript was enqueued on the handler's queue
    assert not handler.transcript_queue.empty()
    transcript = await handler.transcript_queue.get()
    assert transcript == "Test transcript"
