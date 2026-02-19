"""
Unit tests for AIAgent - conversation history, tool handling, and streaming
"""

import pytest
import asyncio
import os
import sys
import json
from unittest.mock import patch, MagicMock, AsyncMock

# Mock environment variables before importing
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("DEEPGRAM_API_KEY", "test-deepgram-key")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-elevenlabs-key")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ai_agent import AIAgent


@pytest.fixture
def ai_agent():
    """Create an AIAgent with mocked Anthropic client"""
    with patch("ai_agent.AsyncAnthropic"):
        agent = AIAgent(knowledge_base=None)
        yield agent


class TestSendGreeting:
    """Tests for greeting flow"""

    @pytest.mark.asyncio
    async def test_greeting_returns_text(self, ai_agent):
        """Greeting should return a non-empty string"""
        greeting = await ai_agent.send_greeting()
        assert isinstance(greeting, str)
        assert len(greeting) > 0

    @pytest.mark.asyncio
    async def test_greeting_added_to_history(self, ai_agent):
        """Greeting should be added to conversation history"""
        assert len(ai_agent.conversation_history) == 0
        await ai_agent.send_greeting()
        assert len(ai_agent.conversation_history) == 1
        assert ai_agent.conversation_history[0]["role"] == "assistant"
        assert "ByteAI" in ai_agent.conversation_history[0]["content"]


class TestToolDefinitions:
    """Tests for tool definitions"""

    def test_tool_definitions_structure(self, ai_agent):
        """Tool definitions should be properly structured"""
        tools = ai_agent._get_tool_definitions()
        assert len(tools) == 3

        tool_names = [t["name"] for t in tools]
        assert "book_appointment" in tool_names
        assert "check_appointment" in tool_names
        assert "escalate_to_human" in tool_names

    def test_tool_definitions_have_schemas(self, ai_agent):
        """Each tool should have an input_schema"""
        tools = ai_agent._get_tool_definitions()
        for tool in tools:
            assert "input_schema" in tool
            assert "type" in tool["input_schema"]
            assert tool["input_schema"]["type"] == "object"


class TestConversationHistory:
    """Tests for conversation history management"""

    @pytest.mark.asyncio
    async def test_user_message_added_to_history(self, ai_agent):
        """User message should be appended to conversation history"""
        # Mock the stream to return immediately with no content
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = MagicMock(return_value=iter([]))
        ai_agent.client.messages.stream = MagicMock(return_value=mock_stream)

        async for _ in ai_agent.process_message("Hello"):
            pass

        # First message in history should be the user message
        assert ai_agent.conversation_history[0]["role"] == "user"
        assert ai_agent.conversation_history[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_greeting_then_message_history(self, ai_agent):
        """After greeting + user message, history should be: assistant, user"""
        await ai_agent.send_greeting()

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = MagicMock(return_value=iter([]))
        ai_agent.client.messages.stream = MagicMock(return_value=mock_stream)

        async for _ in ai_agent.process_message("Hi there"):
            pass

        assert ai_agent.conversation_history[0]["role"] == "assistant"
        assert ai_agent.conversation_history[1]["role"] == "user"


class TestToolExecution:
    """Tests for tool execution"""

    @pytest.mark.asyncio
    async def test_execute_book_appointment(self, ai_agent):
        """book_appointment tool should delegate to AppointmentManager"""
        with patch.object(ai_agent.appointment_manager, 'book_appointment',
                         new_callable=AsyncMock, return_value={"success": True}) as mock:
            result = await ai_agent._execute_tool("book_appointment", {
                "date": "2026-03-01", "time": "14:00",
                "name": "Test", "phone": "+1234567890"
            })
            mock.assert_awaited_once()
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_check_appointment(self, ai_agent):
        """check_appointment tool should delegate to AppointmentManager"""
        with patch.object(ai_agent.appointment_manager, 'check_appointment',
                         new_callable=AsyncMock, return_value={"success": True}) as mock:
            result = await ai_agent._execute_tool("check_appointment", {
                "phone": "+1234567890"
            })
            mock.assert_awaited_once()
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_escalate(self, ai_agent):
        """escalate_to_human tool should delegate to EscalationHandler"""
        with patch.object(ai_agent.escalation_handler, 'escalate',
                         new_callable=AsyncMock, return_value={"success": True}) as mock:
            result = await ai_agent._execute_tool("escalate_to_human", {
                "reason": "Complex issue"
            })
            mock.assert_awaited_once()
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, ai_agent):
        """Unknown tool should return an error"""
        result = await ai_agent._execute_tool("nonexistent_tool", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_tool_handles_exception(self, ai_agent):
        """Tool execution should handle exceptions gracefully"""
        with patch.object(ai_agent.appointment_manager, 'book_appointment',
                         new_callable=AsyncMock, side_effect=Exception("DB error")):
            result = await ai_agent._execute_tool("book_appointment", {
                "date": "2026-03-01", "time": "14:00",
                "name": "Test", "phone": "+1234567890"
            })
            assert "error" in result
