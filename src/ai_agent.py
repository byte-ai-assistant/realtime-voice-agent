"""
AI Agent - Claude integration with streaming and tool calling
Manages conversation, RAG, and function execution
"""

import os
import logging
import json
from typing import AsyncIterator, Dict, List, Optional, Any
from datetime import datetime

from anthropic import AsyncAnthropic

from knowledge_base import KnowledgeBase
from tools import AppointmentManager, EscalationHandler

logger = logging.getLogger(__name__)


class AIAgent:
    """AI Agent powered by Claude with RAG and tool calling"""

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None):
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        # Initialize Claude client
        self.client = AsyncAnthropic(api_key=self.anthropic_api_key)
        self.model = "claude-haiku-4-5-20251001"

        # Knowledge base
        self.knowledge_base = knowledge_base

        # Conversation history
        self.conversation_history: List[Dict] = []

        # Tools
        self.appointment_manager = AppointmentManager()
        self.escalation_handler = EscalationHandler()

        # System prompt optimized for voice conversations
        self.system_prompt = """Eres Ana, recepcionista del Centro de Medicina Regenerativa (CMR), hablando en una llamada telefónica en vivo. SIEMPRE responde en español.

REGLA MÁS IMPORTANTE: Sé BREVE. Máximo 1-2 oraciones por respuesta. Responde solo lo que se preguntó, sin información extra ni explicaciones largas. Si el paciente quiere más detalles, los pedirá.

Tu estilo:
- Clara, directa y amable — no demasiado formal ni robótica
- Habla como una recepcionista real: natural, eficiente, con buenos modales
- Habla de usted al paciente
- Nunca uses markdown, viñetas ni formato — esto se lee en voz alta
- Si no sabes algo, dilo y ofrece conectarlos con un doctor

Herramientas disponibles:
- book_appointment: Agendar citas (necesita fecha, hora, nombre, teléfono)
- check_appointment: Consultar citas existentes (necesita número de teléfono)
- escalate_to_human: Transferir a soporte humano (necesita motivo)"""

        # Embed entire knowledge base in system prompt to eliminate per-query
        # RAG search latency (~876ms saved: OpenAI embedding + ChromaDB query)
        if self.knowledge_base and hasattr(self.knowledge_base, 'get_all_documents_text'):
            kb_text = self.knowledge_base.get_all_documents_text()
            if kb_text:
                self.system_prompt += kb_text

        # Pre-build the system prompt with cache_control for Anthropic prompt caching.
        # The system prompt (including embedded KB) is identical across all turns in a
        # conversation. Caching it avoids re-processing ~500+ tokens on every request,
        # reducing TTFT by ~100-150ms on the 2nd+ message.
        self._cached_system = [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        logger.info("AIAgent initialized")

    async def send_greeting(self) -> str:
        """Send initial greeting and add to conversation history"""
        greeting = "Hola, ha llamado al Centro de Medicina Regenerativa. Habla con Ana, ¿cómo puedo ayudarle?"
        logger.info(f"AI greeting: {greeting}")

        # Add greeting to conversation history so Claude knows what was said
        self.conversation_history.append({
            "role": "assistant",
            "content": greeting
        })

        return greeting

    async def process_message(self, user_message: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Process user message and generate AI response.
        Yields chunks as they're generated (streaming).
        Handles tool calls with proper conversation history management.
        """
        try:
            # Add user message to history
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })

            # KB is embedded in system prompt - no per-query search needed
            messages = self.conversation_history.copy()

            # Define tools for Claude
            tools = self._get_tool_definitions()

            # Stream response from Claude
            response_text = ""
            tool_calls = []
            tool_input_json_buffer = ""

            async with self.client.messages.stream(
                model=self.model,
                max_tokens=100,
                temperature=0.3,
                system=self._cached_system,
                messages=messages,
                tools=tools
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                            tool_calls.append({
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": {}
                            })
                            tool_input_json_buffer = ""

                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            # Text content from Claude
                            chunk_text = event.delta.text
                            response_text += chunk_text
                            yield {
                                "type": "text",
                                "content": chunk_text
                            }
                        elif hasattr(event.delta, "partial_json"):
                            # Accumulate tool input JSON fragments
                            # Do NOT parse each fragment individually
                            tool_input_json_buffer += event.delta.partial_json or ""

                    elif event.type == "content_block_stop":
                        # Parse accumulated JSON when tool_use block closes
                        if tool_calls and tool_input_json_buffer:
                            try:
                                tool_calls[-1]["input"] = json.loads(tool_input_json_buffer)
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse tool input JSON: {e}")
                                tool_calls[-1]["input"] = {}
                            tool_input_json_buffer = ""

            # Handle tool calls with proper history management
            if tool_calls:
                # Build the assistant message with text + all tool_use blocks
                assistant_content = []
                if response_text.strip():
                    assistant_content.append({
                        "type": "text",
                        "text": response_text
                    })
                for tc in tool_calls:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["input"]
                    })

                self.conversation_history.append({
                    "role": "assistant",
                    "content": assistant_content
                })

                # Execute all tools and collect results
                tool_results_content = []
                for tool_call in tool_calls:
                    tool_name = tool_call["name"]
                    tool_input = tool_call["input"]

                    logger.info(f"Executing tool: {tool_name} with input: {tool_input}")
                    tool_result = await self._execute_tool(tool_name, tool_input)

                    yield {
                        "type": "tool_call",
                        "name": tool_name,
                        "input": tool_input,
                        "result": tool_result
                    }

                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": json.dumps(tool_result)
                    })

                # Add all tool results as a single user message
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results_content
                })

                # Generate follow-up response after tool execution
                async with self.client.messages.stream(
                    model=self.model,
                    max_tokens=100,
                    temperature=0.3,
                    system=self._cached_system,
                    messages=self.conversation_history
                ) as follow_up_stream:
                    follow_up_text = ""
                    async for event in follow_up_stream:
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                chunk = event.delta.text
                                follow_up_text += chunk
                                yield {
                                    "type": "text",
                                    "content": chunk
                                }

                # Add follow-up to history
                if follow_up_text:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": follow_up_text
                    })
                    logger.info(f"AI (after tool): {follow_up_text}")

            else:
                # No tool calls - simple text response
                if response_text:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": response_text
                    })
                    logger.info(f"AI: {response_text}")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": "Lo siento, estoy teniendo problemas para procesar eso. ¿Podrías repetirlo por favor?"
            }

    def _get_tool_definitions(self) -> List[Dict]:
        """Return tool definitions for Claude API"""
        return [
            {
                "name": "book_appointment",
                "description": "Book an appointment for a customer. Requires date, time, customer name, and phone number.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Appointment date in YYYY-MM-DD format"
                        },
                        "time": {
                            "type": "string",
                            "description": "Appointment time in HH:MM format (24-hour)"
                        },
                        "name": {
                            "type": "string",
                            "description": "Customer name"
                        },
                        "phone": {
                            "type": "string",
                            "description": "Customer phone number"
                        }
                    },
                    "required": ["date", "time", "name", "phone"]
                }
            },
            {
                "name": "check_appointment",
                "description": "Check appointment status for a customer by phone number.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "phone": {
                            "type": "string",
                            "description": "Customer phone number"
                        }
                    },
                    "required": ["phone"]
                }
            },
            {
                "name": "escalate_to_human",
                "description": "Escalate the call to a human support agent. Use when the customer needs help beyond your capabilities.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Reason for escalation"
                        },
                        "callback_number": {
                            "type": "string",
                            "description": "Customer callback number"
                        }
                    },
                    "required": ["reason"]
                }
            }
        ]

    async def _execute_tool(self, tool_name: str, tool_input: Dict) -> Dict:
        """Execute a tool and return the result"""
        try:
            if tool_name == "book_appointment":
                return await self.appointment_manager.book_appointment(**tool_input)

            elif tool_name == "check_appointment":
                return await self.appointment_manager.check_appointment(**tool_input)

            elif tool_name == "escalate_to_human":
                return await self.escalation_handler.escalate(**tool_input)

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return {"error": str(e)}

    async def cleanup(self):
        """Clean up resources"""
        logger.info("AIAgent cleaned up")
