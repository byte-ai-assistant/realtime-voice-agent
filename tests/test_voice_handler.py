"""
Unit tests for VoiceHandler
"""

import pytest
import asyncio
from src.voice_handler import VoiceHandler


@pytest.mark.asyncio
async def test_voice_handler_initialization():
    """Test VoiceHandler can be initialized"""
    handler = VoiceHandler()
    assert handler is not None
    assert handler.audio_buffer is not None
    assert handler.transcript_queue is not None
    await handler.cleanup()


@pytest.mark.asyncio
async def test_audio_buffering():
    """Test audio buffering"""
    handler = VoiceHandler()
    
    # Add audio to buffer
    test_audio = b'\x00' * 160  # 20ms of silence
    await handler.process_incoming_audio(test_audio)
    
    # Check buffer has data
    assert not handler.audio_buffer.empty()
    
    await handler.cleanup()


@pytest.mark.asyncio
async def test_cleanup():
    """Test cleanup doesn't raise errors"""
    handler = VoiceHandler()
    await handler.cleanup()
    # Should not raise any exceptions
