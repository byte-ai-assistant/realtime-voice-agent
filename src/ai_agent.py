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
from anthropic.types import MessageStreamEvent

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
        self.model = "claude-sonnet-4-20250514"
        
        # Knowledge base
        self.knowledge_base = knowledge_base
        
        # Conversation history
        self.conversation_history: List[Dict] = []
        
        # Tools
        self.appointment_manager = AppointmentManager()
        self.escalation_handler = EscalationHandler()
        
        # System prompt
        self.system_prompt = """You are a helpful AI assistant for ByteAI customer support.

Your role:
- Answer customer questions clearly and concisely
- Use the provided knowledge base to give accurate information
- Help customers book appointments, check status, or escalate issues
- Be friendly, professional, and empathetic
- Keep responses SHORT (1-2 sentences) - this is a phone call, not a chat
- Speak naturally, like a human would on the phone

Important guidelines:
- If you don't know something, say so and offer to connect them with support
- Always confirm actions before executing them
- Use the customer's name if they provide it
- End the call politely if the customer has no more questions

Available tools:
- book_appointment: Schedule appointments
- check_appointment: Look up existing appointments
- escalate_to_human: Transfer to human support"""
        
        logger.info("✅ AIAgent initialized")
    
    async def send_greeting(self):
        """Send initial greeting"""
        greeting = "Hello! Thanks for calling ByteAI. I'm your AI assistant. How can I help you today?"
        logger.info(f"🤖 AI: {greeting}")
        # Note: Actual audio will be handled by the server
        return greeting
    
    async def process_message(self, user_message: str) -> AsyncIterator[Dict[str, Any]]:
        """
        Process user message and generate AI response
        Yields chunks as they're generated (streaming)
        """
        try:
            # Add user message to history
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })
            
            # Retrieve relevant knowledge
            context = ""
            if self.knowledge_base:
                relevant_docs = await self.knowledge_base.search(user_message, top_k=3)
                if relevant_docs:
                    context = "\n\nRelevant information from knowledge base:\n"
                    for doc in relevant_docs:
                        context += f"- {doc['answer']}\n"
            
            # Prepare messages with context
            messages = self.conversation_history.copy()
            if context:
                # Inject context into the last user message
                messages[-1]["content"] = f"{user_message}{context}"
            
            # Define tools
            tools = [
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
            
            # Stream response from Claude
            response_text = ""
            tool_calls = []
            
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=1024,
                temperature=0.7,
                system=self.system_prompt,
                messages=messages,
                tools=tools
            ) as stream:
                async for event in stream:
                    # Handle text chunks
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            chunk_text = event.delta.text
                            response_text += chunk_text
                            
                            # Yield text chunk
                            yield {
                                "type": "text",
                                "content": chunk_text
                            }
                    
                    # Handle tool use
                    elif event.type == "content_block_start":
                        if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                            tool_calls.append({
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input": {}
                            })
                    
                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "partial_json"):
                            # Accumulate tool input
                            if tool_calls:
                                tool_calls[-1]["input"] = json.loads(
                                    event.delta.partial_json or "{}"
                                )
            
            # Execute tools if any were called
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call["name"]
                    tool_input = tool_call["input"]
                    
                    logger.info(f"🔧 Executing tool: {tool_name} with input: {tool_input}")
                    
                    # Execute tool
                    tool_result = await self._execute_tool(tool_name, tool_input)
                    
                    # Yield tool execution result
                    yield {
                        "type": "tool_call",
                        "name": tool_name,
                        "input": tool_input,
                        "result": tool_result
                    }
                    
                    # Add tool result to history
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_call["id"],
                                "name": tool_name,
                                "input": tool_input
                            }
                        ]
                    })
                    
                    self.conversation_history.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call["id"],
                                "content": json.dumps(tool_result)
                            }
                        ]
                    })
                    
                    # Generate follow-up response
                    async with self.client.messages.stream(
                        model=self.model,
                        max_tokens=512,
                        temperature=0.7,
                        system=self.system_prompt,
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
                        
                        response_text += " " + follow_up_text
            
            # Add assistant response to history
            if response_text:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response_text
                })
                
                logger.info(f"🤖 AI: {response_text}")
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            yield {
                "type": "error",
                "content": "I'm sorry, I'm having trouble processing that. Could you please repeat?"
            }
    
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
        logger.info("✅ AIAgent cleaned up")
