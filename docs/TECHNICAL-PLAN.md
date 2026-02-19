# Real-Time Voice AI Agent - Technical Plan

## Executive Summary

Building a production-ready voice AI agent with sub-2-second response latency that handles phone calls, uses a knowledge base, executes tools, and deploys to Google Cloud.

**Target Latency Budget: 1500-2000ms end-to-end**

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PHONE CALL (Customer)                        │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                         ┌───────▼────────┐
                         │  TWILIO CLOUD  │
                         │  (Voice API)   │
                         └───────┬────────┘
                                 │ WebSocket (bidirectional audio)
                                 │ μ-law 8kHz PCM
                         ┌───────▼────────────────────────────────────┐
                         │      VOICE SERVER (FastAPI + WebSocket)   │
                         │         Running on GCP VM                  │
                         └───────┬────────────────────────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
        ┌───────▼────────┐  ┌───▼────┐  ┌───────▼────────┐
        │  DEEPGRAM STT  │  │ AUDIO  │  │ ELEVENLABS TTS │
        │  (Streaming)   │  │ BUFFER │  │  (Streaming)   │
        └───────┬────────┘  └────────┘  └───────▲────────┘
                │                               │
                │ Transcribed text              │ AI response text
                │                               │
        ┌───────▼───────────────────────────────┴────────┐
        │           AI ORCHESTRATION ENGINE              │
        │  ┌──────────────────────────────────────────┐  │
        │  │  CLAUDE SONNET 4.5 (Streaming)          │  │
        │  │  - Conversation management               │  │
        │  │  - Tool calling                          │  │
        │  │  - Context management                    │  │
        │  └──────────────┬───────────────────────────┘  │
        │                 │                               │
        │  ┌──────────────▼───────────────────────────┐  │
        │  │  RAG PIPELINE                            │  │
        │  │  - Vector DB (ChromaDB)                  │  │
        │  │  - OpenAI Embeddings                     │  │
        │  │  - Semantic search                       │  │
        │  └──────────────────────────────────────────┘  │
        │                                                 │
        │  ┌──────────────────────────────────────────┐  │
        │  │  FUNCTION CALLING TOOLS                  │  │
        │  │  - Book appointment                      │  │
        │  │  - Check appointment                     │  │
        │  │  - Escalate to human                     │  │
        │  └──────────────────────────────────────────┘  │
        └─────────────────────────────────────────────────┘
```

---

## Technology Stack

### 1. Voice Infrastructure
**Twilio Voice API**
- ✅ Production-ready telephony
- ✅ WebSocket media streams
- ✅ Global phone numbers
- ✅ Built-in recording/logging
- Latency: ~50-100ms

### 2. Speech-to-Text
**Deepgram Nova-2**
- ✅ Best-in-class latency (~300ms)
- ✅ Streaming API
- ✅ High accuracy
- ✅ Punctuation + formatting
- Cost: $0.0043/min
- Alternative: AssemblyAI (~400ms latency)

### 3. Text-to-Speech
**ElevenLabs Turbo v2.5**
- ✅ Ultra-low latency (~250ms first byte)
- ✅ Streaming output
- ✅ Natural voices
- ✅ Emotion control
- Cost: $0.18/1K characters
- Voice recommendation: "Rachel" (professional, clear)

### 4. AI/LLM
**Claude Sonnet 4.5**
- ✅ Fast streaming responses
- ✅ Function calling support
- ✅ 200K context window
- ✅ High quality reasoning
- Cost: $3/$15 per million tokens
- Latency: ~200-400ms first token

### 5. Knowledge Base
**ChromaDB + OpenAI Embeddings**
- ✅ Fast vector search (<50ms)
- ✅ Persistent storage
- ✅ Simple API
- ✅ Runs in-memory or persistent
- Embedding cost: $0.02/million tokens

### 6. Backend Framework
**FastAPI + Python 3.11**
- ✅ Native async/await
- ✅ WebSocket support
- ✅ Type safety
- ✅ Auto-generated docs
- ✅ High performance

### 7. Deployment
**Google Cloud Compute Engine**
- VM: e2-standard-2 (2 vCPU, 8GB RAM)
- Region: us-central1 (low latency to Twilio)
- OS: Ubuntu 22.04 LTS
- Docker + Docker Compose
- Estimated cost: ~$50/month

---

## Data Flow & Latency Budget

### Inbound Call Flow (Customer → AI)

```
1. Customer speaks (1-3 seconds)
   ↓
2. Audio → Twilio → WebSocket (50ms)
   ↓
3. Audio → Deepgram STT (300ms streaming)
   ↓
4. Text → RAG retrieval (50ms)
   ↓
5. Context + Text → Claude (200ms first token, 400ms streaming)
   ↓
6. Response → ElevenLabs TTS (250ms first audio chunk)
   ↓
7. Audio → Twilio → Customer (50ms)

Total latency: ~900ms (from end of speech to start of response)
```

### Optimization Strategies

**Parallel Processing:**
- While STT is streaming, start RAG retrieval on partial transcripts
- While Claude is generating, buffer first tokens and start TTS immediately
- While TTS is generating, stream first audio chunks to Twilio

**Caching:**
- Cache common embeddings
- Cache frequent RAG results (TTL: 5 min)
- Preload system prompts

**Streaming:**
- Stream all components: STT → LLM → TTS → Audio
- Use sentence-level buffering (not word-level, too choppy)
- Buffer 2-3 words before sending to TTS

**Infrastructure:**
- WebSocket connection pooling
- Keep-alive connections to all APIs
- Regional deployment close to Twilio

---

## Component Design

### 1. Server Architecture (`server.py`)

```python
FastAPI application with:
- /webhook/voice → Twilio TwiML endpoint
- /ws/media → WebSocket for audio streaming
- /health → Health check endpoint
- /metrics → Prometheus metrics

Async event loop with:
- Audio receiver task (Twilio → Buffer)
- STT processor task (Buffer → Deepgram → Text)
- AI orchestrator task (Text → Claude → Response)
- TTS generator task (Response → ElevenLabs → Audio)
- Audio sender task (Audio → Twilio)
```

### 2. Voice Handler (`voice_handler.py`)

```python
class VoiceHandler:
    - Audio format conversion (μ-law ↔ PCM)
    - Buffering and chunking
    - VAD (Voice Activity Detection) for turn-taking
    - Silence detection
    - Interrupt handling
```

### 3. AI Agent (`ai_agent.py`)

```python
class AIAgent:
    - Claude API integration (streaming)
    - Conversation history management
    - Function calling orchestration
    - RAG integration
    - Response formatting for TTS
```

### 4. Knowledge Base (`knowledge_base.py`)

```python
class KnowledgeBase:
    - ChromaDB initialization
    - Document ingestion
    - Vector search
    - Relevance scoring
    - Context assembly
```

### 5. Tools (`tools.py`)

```python
@tool("book_appointment")
async def book_appointment(date: str, time: str, name: str, phone: str) -> dict:
    """Books appointment, returns confirmation"""
    
@tool("check_appointment")
async def check_appointment(phone: str) -> dict:
    """Looks up appointment by phone"""
    
@tool("escalate_to_human")
async def escalate_to_human(reason: str, callback: str) -> dict:
    """Creates support ticket, initiates transfer"""
```

---

## Sample Knowledge Base

**Business Context: "ByteAI Customer Support"**

Topics:
1. Product features (AI assistants, automation, integrations)
2. Pricing ($99/mo Pro, $299/mo Business)
3. Technical requirements (API keys, setup)
4. Common troubleshooting (connection issues, API limits)
5. Account management (billing, upgrades, cancellation)

Format: 50+ FAQ pairs in JSON:
```json
{
  "documents": [
    {
      "id": "faq-001",
      "category": "pricing",
      "question": "How much does ByteAI cost?",
      "answer": "ByteAI has two plans: Pro at $99/month with 10,000 API calls, and Business at $299/month with unlimited calls. Both include 24/7 support."
    },
    ...
  ]
}
```

---

## Conversation Flow Design

### Greeting
```
AI: "Hello! Thanks for calling ByteAI. I'm your AI assistant. How can I help you today?"
```

### Active Listening Cues
While processing:
- "Let me check that for you..."
- "One moment please..."
- "I'm looking that up now..."

### Tool Execution
```
Customer: "I'd like to book an appointment for tomorrow at 2pm"
AI: [Calls book_appointment tool]
AI: "Great! I've scheduled your appointment for tomorrow, February 20th at 2pm. 
     You'll receive a confirmation text shortly. Is there anything else?"
```

### Fallback to Human
```
AI: "I want to make sure you get the best help. Let me connect you with 
     one of our specialists who can assist you further. Please hold..."
[Calls escalate_to_human tool]
```

### Ending
```
AI: "Is there anything else I can help with today?"
Customer: "No, that's all."
AI: "Perfect! Thanks for calling ByteAI. Have a great day!"
[Hangs up after 2 seconds of silence]
```

---

## Error Handling & Resilience

### STT Failure
- Fallback: "I'm sorry, I didn't catch that. Could you repeat?"
- After 3 failures: Escalate to human

### LLM Timeout
- Timeout: 10 seconds
- Fallback: "I'm having trouble processing that. Let me connect you with support."

### TTS Failure
- Fallback: Pre-recorded audio messages
- Log error, continue conversation

### API Rate Limits
- Queue requests
- Show warning in logs
- Graceful degradation

### WebSocket Disconnect
- Auto-reconnect with exponential backoff
- Save conversation state
- Resume or gracefully end call

---

## Deployment Architecture

### Google Cloud Setup

```bash
# VM Specs
- Machine: e2-standard-2 (2 vCPU, 8GB RAM)
- Region: us-central1-a
- Disk: 20GB SSD
- Network: Allow HTTP/HTTPS/WebSocket
- Firewall: Open port 8000 (application)

# Security
- Service account with minimal permissions
- API keys in Secret Manager
- SSL/TLS for all connections
- Rate limiting (100 req/min per IP)
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y gcc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ /app/src/
COPY knowledge/ /app/knowledge/
WORKDIR /app
CMD ["python", "src/server.py"]
```

### Docker Compose

```yaml
services:
  voice-agent:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY}
      - DEEPGRAM_API_KEY=${DEEPGRAM_API_KEY}
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

---

## Testing Strategy

### 1. Unit Tests
- Audio format conversion
- RAG retrieval accuracy
- Tool execution
- Error handling

### 2. Integration Tests
- Mock Twilio WebSocket
- End-to-end flow simulation
- Latency benchmarking
- Concurrent call handling

### 3. Load Testing
- 10 concurrent calls
- Measure latency degradation
- Memory/CPU profiling

### 4. Manual Testing
- Real phone calls
- Test all conversation paths
- Verify tool execution
- Check voice quality

### 5. Monitoring
- Response time metrics (p50, p95, p99)
- Error rates by component
- API quota usage
- Call success rate

---

## Security & Privacy

1. **API Key Management**
   - Store in GCP Secret Manager
   - Rotate quarterly
   - Never log API keys

2. **Audio Recording**
   - Optional recording with consent
   - Encrypted at rest
   - Auto-delete after 30 days

3. **Data Privacy**
   - No PII in logs
   - Anonymize phone numbers
   - GDPR/CCPA compliant

4. **Rate Limiting**
   - 100 calls/hour per phone number
   - DDoS protection
   - Webhook signature verification

---

## Cost Estimation

### Monthly Costs (100 calls/day, 3 min avg)

| Service | Usage | Cost |
|---------|-------|------|
| Twilio | 9,000 minutes | $27 |
| Deepgram | 9,000 minutes | $39 |
| ElevenLabs | ~450K chars | $81 |
| Claude | ~15M tokens | $75 |
| OpenAI Embeddings | 1M tokens | $0.02 |
| GCP VM | 730 hours | $50 |
| **Total** | | **~$272/month** |

Per-call cost: ~$0.90

---

## Implementation Timeline

### Phase 1: Planning ✅ (30 min)
- Technical architecture
- Technology selection
- Cost analysis

### Phase 2: Core Implementation (3-4 hours)
- [ ] GitHub repo setup
- [ ] FastAPI server + WebSocket
- [ ] Twilio integration
- [ ] Deepgram STT integration
- [ ] ElevenLabs TTS integration
- [ ] Claude agent with streaming
- [ ] RAG pipeline
- [ ] Function calling tools
- [ ] Error handling

### Phase 3: Deployment (1 hour)
- [ ] Dockerfile
- [ ] GCP deployment scripts
- [ ] Twilio configuration
- [ ] End-to-end testing

### Phase 4: Documentation (1 hour)
- [ ] README with quick start
- [ ] Deployment guide
- [ ] Testing guide
- [ ] Troubleshooting guide

### Phase 5: Handoff
- [ ] GitHub push
- [ ] Live test call
- [ ] Handoff documentation

---

## Success Metrics

**Must-Have:**
- ✅ <2 second response latency (p95)
- ✅ >95% transcription accuracy
- ✅ >90% tool execution success
- ✅ Natural voice quality
- ✅ Handles 10 concurrent calls

**Nice-to-Have:**
- <1.5 second response latency
- Interrupt handling
- Emotion detection
- Multi-language support

---

## Next Steps

1. Create GitHub repository
2. Implement core server
3. Integrate all APIs
4. Deploy to GCP
5. Test with real phone calls
6. Iterate based on feedback

**LET'S BUILD IT!** 🚀
