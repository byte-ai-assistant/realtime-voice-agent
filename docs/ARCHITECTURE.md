# Technical Architecture

Detailed technical architecture for the Real-Time Voice AI Agent.

---

## System Overview

The voice agent is a **real-time streaming system** that processes audio bidirectionally with minimal latency. Every component is optimized for speed and uses streaming APIs wherever possible.

### Core Principles

1. **Stream Everything** - Never wait for complete responses
2. **Parallel Processing** - Run tasks concurrently when possible
3. **Fail Gracefully** - Degrade functionality rather than crash
4. **Optimize for Latency** - Every millisecond counts

---

## Component Architecture

### 1. Server Layer (`server.py`)

**Technology:** FastAPI + Uvicorn + WebSockets

**Responsibilities:**
- Handle Twilio webhooks (TwiML generation)
- Manage WebSocket connections for audio streaming
- Coordinate between voice handler, AI agent, and Twilio
- Health checks and metrics

**Key Features:**
- Async/await throughout (non-blocking I/O)
- Multiple concurrent call handling
- Graceful shutdown and cleanup

**API Endpoints:**
```python
POST /webhook/voice       # Twilio TwiML endpoint
WebSocket /ws/media       # Bidirectional audio streaming
GET /health               # Health check
GET /metrics              # Prometheus metrics
```

### 2. Voice Handler (`voice_handler.py`)

**Technology:** Deepgram SDK, ElevenLabs SDK

**Responsibilities:**
- Receive audio from Twilio (μ-law, 8kHz)
- Stream audio to Deepgram for transcription
- Convert AI text responses to speech via ElevenLabs
- Stream audio back to Twilio

**Audio Pipeline:**
```
Twilio (μ-law) → Buffer → Deepgram (streaming) → Transcript Queue
                                                       ↓
Response Text → ElevenLabs (streaming) → Audio Chunks → Twilio
```

**Latency Optimizations:**
- Streaming transcription (don't wait for silence)
- Parallel STT and TTS operations
- Audio chunk buffering (20ms chunks)
- Keep-alive connections to Deepgram

### 3. AI Agent (`ai_agent.py`)

**Technology:** Anthropic Claude SDK (async)

**Responsibilities:**
- Manage conversation history
- Process user messages with context
- Execute RAG retrieval
- Call tools/functions
- Stream responses

**Conversation Flow:**
```
1. User message received
2. RAG: Search knowledge base for context
3. Assemble prompt: system + history + context + message
4. Claude: Stream response (token by token)
5. Tool calls: Execute and get results
6. Claude: Generate follow-up with tool results
7. Return complete response
```

**Tool Execution:**
- Defined in OpenAPI schema format
- Claude decides when to call tools
- Async execution (non-blocking)
- Results injected back into conversation

### 4. Knowledge Base (`knowledge_base.py`)

**Technology:** ChromaDB + OpenAI Embeddings

**Responsibilities:**
- Load documents from JSON
- Generate embeddings
- Perform vector similarity search
- Return relevant context

**RAG Pipeline:**
```
Query → Generate Embedding → Vector Search → Top K Results → Format Context
```

**Storage:**
- Persistent ChromaDB (DuckDB backend)
- Stored in `./data/chroma/`
- Survives server restarts

**Search:**
- Semantic similarity search
- Configurable top_k (default: 3)
- Distance-based ranking

### 5. Tools (`tools.py`)

**Technology:** Pure Python (async)

**Responsibilities:**
- Book appointments (validation, storage)
- Check appointment status
- Escalate to human support
- Extensible for custom tools

**Appointment Manager:**
- JSON file storage (production: use database)
- Validates dates, times, business hours
- Stores appointment history
- Phone number lookup

**Escalation Handler:**
- Creates support tickets
- Stores in JSON (production: webhook to CRM)
- Returns ticket ID and next steps

---

## Data Flow

### Inbound Call Flow

```
1. Customer dials Twilio number
   ↓
2. Twilio sends webhook to /webhook/voice
   ↓
3. Server returns TwiML with WebSocket URL
   ↓
4. Twilio establishes WebSocket connection to /ws/media
   ↓
5. Server sends greeting via TTS
   ↓
6. Audio streaming begins (bidirectional)
```

### Message Processing Flow

```
Customer speaks
   ↓
Twilio → WebSocket → audio_buffer → Deepgram (streaming)
   ↓
transcript_queue receives text
   ↓
RAG searches knowledge base (parallel)
   ↓
Claude receives: context + history + message
   ↓
Claude streams response tokens
   ↓
ElevenLabs converts text to audio (streaming)
   ↓
Audio chunks → WebSocket → Twilio → Customer hears response
```

### Tool Call Flow

```
Claude detects tool call needed
   ↓
Yields tool_use block
   ↓
Server executes tool (e.g., book_appointment)
   ↓
Tool returns result
   ↓
Result added to conversation history
   ↓
Claude generates follow-up message
   ↓
Response sent to customer
```

---

## Latency Analysis

### Target Budget: <2000ms

| Component | Latency | Optimization |
|-----------|---------|--------------|
| Twilio routing | ~50ms | (inherent) |
| Deepgram STT | ~300ms | Streaming, nova-2 model |
| RAG retrieval | ~50ms | In-memory ChromaDB |
| Claude first token | ~200ms | Streaming API |
| Claude full response | ~400ms | Streaming (tokens arrive progressively) |
| ElevenLabs first audio | ~250ms | Turbo v2.5, max optimization |
| ElevenLabs full audio | ~600ms | Streaming (chunks arrive progressively) |
| Twilio playback | ~50ms | (inherent) |

**Critical Path (end-of-speech to start-of-response):**
```
50ms (Twilio) + 300ms (STT) + 50ms (RAG) + 200ms (Claude first token) 
+ 250ms (TTS first chunk) + 50ms (Twilio) = ~900ms ✅
```

**Perceived latency:** Customer hears first audio chunk in **~900ms** after stopping speech.

### Optimization Strategies

**1. Streaming Everything**
- Don't wait for complete transcription
- Don't wait for complete AI response
- Don't wait for complete TTS generation

**2. Parallel Processing**
```python
# While Deepgram is transcribing, start RAG search
# While Claude is generating, start TTS on first tokens
# While TTS is generating, stream first audio chunks
```

**3. Connection Pooling**
- Keep-alive WebSocket to Deepgram
- Reuse HTTP connections to APIs
- Pre-warm connections on server start

**4. Caching**
- Cache embeddings for common queries
- Cache frequent responses (with TTL)
- Preload system prompts

---

## Concurrency Model

### Async/Await Architecture

```python
async def websocket_endpoint():
    tasks = [
        receive_audio(),      # Receive from Twilio
        process_speech(),     # STT + AI + TTS
        send_audio()          # Send to Twilio
    ]
    await asyncio.gather(*tasks)
```

**Benefits:**
- Non-blocking I/O
- Handle multiple calls concurrently
- Efficient resource usage

### Task Management

- Each call gets its own WebSocket connection
- Each connection spawns 2-3 async tasks
- Tasks communicate via async queues
- Automatic cleanup on disconnect

---

## Error Handling

### Graceful Degradation

**STT Failure:**
```python
if transcription_error:
    say("I'm sorry, I didn't catch that. Could you repeat?")
    retry_count += 1
    if retry_count > 3:
        escalate_to_human()
```

**LLM Timeout:**
```python
async with timeout(10):  # 10 second timeout
    response = await claude.generate()
except TimeoutError:
    say("I'm having trouble. Let me connect you with support.")
    escalate_to_human()
```

**TTS Failure:**
```python
try:
    audio = await elevenlabs.synthesize(text)
except Exception:
    logger.error("TTS failed")
    # Fallback: pre-recorded audio or retry
    audio = get_fallback_audio()
```

### Retry Logic

- Exponential backoff for API failures
- Max 3 retries for transient errors
- Immediate escalation for critical failures

---

## Security

### API Key Management

```python
# Environment variables only
api_key = os.getenv("ANTHROPIC_API_KEY")

# Never log keys
logger.info(f"Using API key: {api_key[:8]}***")

# Production: use secret manager
from google.cloud import secretmanager
```

### Call Authentication

```python
# Verify Twilio signature
def verify_twilio_signature(request):
    signature = request.headers.get("X-Twilio-Signature")
    url = str(request.url)
    params = await request.form()
    
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    return validator.validate(url, params, signature)
```

### Data Privacy

- No PII in logs
- Optional call recording (off by default)
- Encrypted storage for recordings
- Auto-delete after 30 days

---

## Monitoring

### Key Metrics

**Latency:**
- p50, p95, p99 response times
- Time to first audio chunk
- End-to-end call duration

**Reliability:**
- Call success rate
- Error rate by component
- Retry attempts

**Usage:**
- Calls per hour
- Concurrent calls
- API quota consumption

### Logging

```python
logger.info(f"📞 Call started: {call_sid}")
logger.info(f"👤 User: {transcript}")
logger.info(f"🤖 AI: {response}")
logger.info(f"🔧 Tool executed: {tool_name}")
logger.error(f"❌ Error: {error}")
```

### Health Checks

```python
GET /health
{
  "status": "healthy",
  "checks": {
    "knowledge_base": true,
    "active_calls": 3,
    "api_keys": {
      "anthropic": true,
      "elevenlabs": true,
      "deepgram": true
    }
  }
}
```

---

## Scalability

### Current Capacity

- **Single VM:** 10 concurrent calls
- **Bottleneck:** TTS generation (most expensive)
- **Resource usage:** ~400MB RAM per call

### Scaling Strategies

**Horizontal Scaling:**
```
Load Balancer
  ↓
[VM 1] [VM 2] [VM 3] ... [VM N]
  ↓      ↓      ↓          ↓
ChromaDB (shared or replicated)
```

**Optimizations:**
- Use managed ChromaDB (Chroma Cloud)
- Cache common responses in Redis
- Pre-generate common TTS responses
- Queue system for high volume

---

## Technology Choices

### Why FastAPI?

- ✅ Native async/await
- ✅ WebSocket support
- ✅ Type safety
- ✅ Auto-generated docs
- ✅ High performance

### Why Deepgram?

- ✅ Best-in-class latency (~300ms)
- ✅ Streaming API
- ✅ High accuracy
- ✅ Cost-effective

### Why ElevenLabs?

- ✅ Ultra-low latency (~250ms first byte)
- ✅ Most natural voices
- ✅ Streaming output
- ✅ Supports μ-law format

### Why Claude?

- ✅ Fast streaming responses
- ✅ Excellent function calling
- ✅ Large context window
- ✅ High-quality reasoning

### Why ChromaDB?

- ✅ Simple Python API
- ✅ Fast vector search
- ✅ Persistent storage
- ✅ No external dependencies

---

## Future Enhancements

### Interrupt Handling

Detect when customer starts speaking mid-response:
```python
if voice_activity_detected() and ai_is_speaking:
    stop_tts()
    buffer_partial_transcript()
```

### Emotion Detection

Analyze customer tone:
```python
emotion = deepgram.analyze_emotion(audio)
if emotion == "frustrated":
    escalate_to_human()
```

### Multi-Language

```python
detected_language = deepgram.detect_language(audio)
claude_response = generate(language=detected_language)
elevenlabs_voice = get_voice_for_language(detected_language)
```

---

## Conclusion

This architecture prioritizes **speed** and **reliability** through streaming, parallelization, and graceful degradation. Every component is chosen for low latency and production readiness.

**Key takeaways:**
- Stream everything (STT, AI, TTS)
- Run tasks in parallel
- Fail gracefully
- Monitor everything
- Optimize the critical path

Total latency: **~900ms** from end-of-speech to start-of-response ⚡
