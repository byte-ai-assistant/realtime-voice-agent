# Testing Guide

Comprehensive testing guide for the Real-Time Voice AI Agent.

---

## Testing Levels

1. **Unit Tests** - Test individual components
2. **Integration Tests** - Test component interactions
3. **End-to-End Tests** - Test complete call flow
4. **Load Tests** - Test performance under load
5. **Manual Tests** - Real phone call testing

---

## Unit Tests

### Running Unit Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_tools.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

### Test Structure

```
tests/
├── test_voice_handler.py    # Audio streaming tests
├── test_ai_agent.py          # AI/Claude tests
├── test_knowledge_base.py    # RAG tests
├── test_tools.py             # Function calling tests
└── test_server.py            # API endpoint tests
```

### Writing Tests

**Example: Testing Appointment Booking**

```python
import pytest
from src.tools import AppointmentManager

@pytest.mark.asyncio
async def test_book_appointment():
    manager = AppointmentManager()
    
    result = await manager.book_appointment(
        date="2025-02-20",
        time="14:00",
        name="John Doe",
        phone="+1234567890"
    )
    
    assert result["success"] is True
    assert "appointment_id" in result
```

---

## Integration Tests

### Test WebSocket Connection

```python
import pytest
from fastapi.testclient import TestClient
from src.server import app

def test_websocket():
    client = TestClient(app)
    
    with client.websocket_connect("/ws/media") as websocket:
        # Send start event
        websocket.send_json({
            "event": "start",
            "start": {
                "callSid": "TEST_CALL",
                "streamSid": "TEST_STREAM"
            }
        })
        
        # Should receive acknowledgment
        data = websocket.receive_json()
        assert data is not None
```

### Test RAG Pipeline

```bash
# Create test script
cat > test_rag.py << 'EOF'
import asyncio
from src.knowledge_base import KnowledgeBase

async def test():
    kb = KnowledgeBase()
    await kb.initialize("./knowledge/sample_kb.json")
    
    results = await kb.search("How much does ByteAI cost?")
    print(f"Found {len(results)} results:")
    for doc in results:
        print(f"  - {doc['question']}")
        print(f"    {doc['answer'][:100]}...")

asyncio.run(test())
EOF

python test_rag.py
```

---

## End-to-End Tests

### Simulated Call Flow

```python
# test_e2e.py
import pytest
import asyncio
from src.voice_handler import VoiceHandler
from src.ai_agent import AIAgent
from src.knowledge_base import KnowledgeBase

@pytest.mark.asyncio
async def test_full_conversation():
    """Simulate a complete conversation"""
    
    # Initialize components
    kb = KnowledgeBase()
    await kb.initialize("./knowledge/sample_kb.json")
    
    ai_agent = AIAgent(knowledge_base=kb)
    voice_handler = VoiceHandler()
    
    # Simulate user message
    user_message = "How much does ByteAI cost?"
    
    # Get AI response
    response_chunks = []
    async for chunk in ai_agent.process_message(user_message):
        if chunk.get("type") == "text":
            response_chunks.append(chunk["content"])
    
    response = "".join(response_chunks)
    
    # Verify response mentions pricing
    assert "$99" in response or "pricing" in response.lower()
    
    # Cleanup
    await voice_handler.cleanup()
    await ai_agent.cleanup()
```

Run:
```bash
pytest test_e2e.py -v -s
```

---

## Manual Testing

### Test Checklist

#### 1. Basic Conversation

- [ ] **Call connects** - Hear greeting within 2 seconds
- [ ] **AI responds** - Answers "What can you help me with?"
- [ ] **Latency acceptable** - Response within 2 seconds
- [ ] **Voice quality good** - Clear, natural voice
- [ ] **No audio glitches** - No stuttering or dropouts

#### 2. Knowledge Base

- [ ] **Pricing question** - "How much does ByteAI cost?"
- [ ] **Features question** - "What can ByteAI do?"
- [ ] **Support question** - "How do I get help?"
- [ ] **Out-of-scope question** - "What's the weather?" (should gracefully decline)

#### 3. Appointment Booking

**Happy Path:**
```
You: "I'd like to book an appointment"
AI: "I can help with that. What date and time?"
You: "Tomorrow at 2pm"
AI: "May I have your name?"
You: "John Doe"
AI: "And your phone number?"
You: "+1234567890"
AI: "Great! I've booked your appointment..." ✅
```

**Error Cases:**
- [ ] Past date - "I want an appointment yesterday" (should reject)
- [ ] Invalid time - "I want an appointment at 8pm" (outside hours)
- [ ] Missing info - Doesn't provide name/phone (should ask)

#### 4. Appointment Checking

```
You: "Check my appointment status"
AI: "May I have your phone number?"
You: "+1234567890"
AI: "Found appointment for John Doe on..." ✅
```

- [ ] Existing appointment found
- [ ] No appointment found (graceful message)

#### 5. Escalation

```
You: "I need to speak with a human"
AI: "I'd be happy to connect you. Let me transfer you..." ✅
```

- [ ] Escalation triggered
- [ ] Ticket ID provided
- [ ] Support number mentioned

#### 6. Edge Cases

- [ ] **Long silence** - AI waits patiently
- [ ] **Unclear speech** - "I didn't catch that..."
- [ ] **Background noise** - Still transcribes correctly
- [ ] **Overlapping speech** - Handles interruption
- [ ] **Call hangup** - Server handles disconnect gracefully

---

## Performance Testing

### Latency Benchmarks

Create benchmark script:

```python
# benchmark.py
import time
import asyncio
from src.ai_agent import AIAgent
from src.knowledge_base import KnowledgeBase

async def benchmark():
    kb = KnowledgeBase()
    await kb.initialize("./knowledge/sample_kb.json")
    
    agent = AIAgent(knowledge_base=kb)
    
    messages = [
        "How much does ByteAI cost?",
        "What features do you have?",
        "I want to book an appointment",
        "How do I get support?"
    ]
    
    latencies = []
    
    for msg in messages:
        start = time.time()
        
        async for chunk in agent.process_message(msg):
            if chunk.get("type") == "text":
                # Time to first token
                first_token_time = time.time() - start
                latencies.append(first_token_time)
                break
        
        print(f"Query: {msg[:50]}")
        print(f"Time to first token: {first_token_time*1000:.0f}ms\n")
    
    avg_latency = sum(latencies) / len(latencies)
    print(f"Average latency: {avg_latency*1000:.0f}ms")
    print(f"Target: <500ms ({'✅ PASS' if avg_latency < 0.5 else '❌ FAIL'})")

asyncio.run(benchmark())
```

Run:
```bash
python benchmark.py
```

**Expected Results:**
```
Time to first token: 200-400ms ✅
```

### Load Testing

**Test Concurrent Calls:**

```python
# load_test.py
import asyncio
import aiohttp
from datetime import datetime

async def simulate_call(call_id: int):
    """Simulate a single call"""
    start = datetime.now()
    
    try:
        async with aiohttp.ClientSession() as session:
            # Connect WebSocket
            async with session.ws_connect(
                "ws://localhost:8000/ws/media"
            ) as ws:
                # Send start event
                await ws.send_json({
                    "event": "start",
                    "start": {
                        "callSid": f"CALL_{call_id}",
                        "streamSid": f"STREAM_{call_id}"
                    }
                })
                
                # Wait for response
                await asyncio.sleep(5)
                
                # Close
                await ws.send_json({"event": "stop"})
        
        duration = (datetime.now() - start).total_seconds()
        return {"call_id": call_id, "success": True, "duration": duration}
        
    except Exception as e:
        return {"call_id": call_id, "success": False, "error": str(e)}

async def load_test(concurrent_calls: int = 10):
    """Test with concurrent calls"""
    print(f"🔥 Starting load test with {concurrent_calls} concurrent calls...")
    
    tasks = [simulate_call(i) for i in range(concurrent_calls)]
    results = await asyncio.gather(*tasks)
    
    successful = sum(1 for r in results if r["success"])
    failed = concurrent_calls - successful
    avg_duration = sum(r.get("duration", 0) for r in results) / concurrent_calls
    
    print(f"\n📊 Results:")
    print(f"  Successful: {successful}/{concurrent_calls}")
    print(f"  Failed: {failed}")
    print(f"  Avg duration: {avg_duration:.2f}s")
    print(f"  Pass: {'✅' if failed == 0 else '❌'}")

if __name__ == "__main__":
    asyncio.run(load_test(concurrent_calls=10))
```

Run:
```bash
python load_test.py
```

**Target:** 10 concurrent calls with 0 failures ✅

---

## Monitoring Tests

### Health Check

```bash
# Should return 200 OK
curl -f http://localhost:8000/health

# Should have all checks passing
curl http://localhost:8000/health | jq '.checks'
```

Expected:
```json
{
  "knowledge_base": true,
  "active_calls": 0,
  "api_keys": {
    "anthropic": true,
    "elevenlabs": true,
    "deepgram": true,
    "twilio": true
  }
}
```

### Metrics

```bash
# Check metrics endpoint
curl http://localhost:8000/metrics
```

Expected:
```json
{
  "active_calls": 0,
  "total_documents": 25,
  "uptime_seconds": 3600
}
```

---

## Debugging

### Enable Debug Logging

```bash
# In .env
LOG_LEVEL=DEBUG

# Restart server
./scripts/run.sh
```

### View Detailed Logs

```bash
# Real-time logs
tail -f logs/voice-agent.log

# Filter errors only
grep ERROR logs/voice-agent.log

# Show last 100 lines
tail -100 logs/voice-agent.log
```

### Test Individual Components

**Test Deepgram:**
```bash
curl -X POST "https://api.deepgram.com/v1/listen" \
  -H "Authorization: Token YOUR_KEY" \
  -H "Content-Type: audio/wav" \
  --data-binary @test.wav
```

**Test ElevenLabs:**
```bash
curl -X POST "https://api.elevenlabs.io/v1/text-to-speech/VOICE_ID" \
  -H "xi-api-key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"Hello world"}' \
  --output test.mp3
```

**Test Claude:**
```bash
curl -X POST "https://api.anthropic.com/v1/messages" \
  -H "x-api-key: YOUR_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

---

## CI/CD Testing

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.11
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run tests
      run: pytest tests/ -v --cov=src
      env:
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        ELEVENLABS_API_KEY: ${{ secrets.ELEVENLABS_API_KEY }}
        DEEPGRAM_API_KEY: ${{ secrets.DEEPGRAM_API_KEY }}
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

---

## Test Data

### Sample Phone Numbers (for testing)

Use Twilio test credentials:
- Account SID: `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`
- Auth Token: `test_token`
- Phone: `+15005550006` (valid test number)

### Sample Audio Files

Create test audio:
```bash
# Generate 3-second silence
sox -n -r 8000 -c 1 test_silence.wav trim 0 3

# Generate beep
sox -n -r 8000 -c 1 test_beep.wav synth 0.5 sine 1000
```

---

## Regression Testing

### Create Test Suite

```bash
# test_suite.sh
#!/bin/bash

echo "🧪 Running test suite..."

# 1. Unit tests
echo "1️⃣ Unit tests..."
pytest tests/test_tools.py -v

# 2. Integration tests
echo "2️⃣ Integration tests..."
pytest tests/test_e2e.py -v

# 3. Health check
echo "3️⃣ Health check..."
curl -f http://localhost:8000/health

# 4. Performance benchmark
echo "4️⃣ Performance benchmark..."
python benchmark.py

echo "✅ Test suite complete!"
```

Run before each release:
```bash
chmod +x test_suite.sh
./test_suite.sh
```

---

## Acceptance Criteria

Before marking the project complete, verify:

- [✅] All unit tests passing
- [✅] Integration tests passing
- [✅] Can make successful test call
- [✅] AI responds within 2 seconds
- [✅] Voice quality is good
- [✅] All 3 tools working (book, check, escalate)
- [✅] Knowledge base returns relevant answers
- [✅] Handles 10 concurrent calls
- [✅] Error handling works gracefully
- [✅] Documentation is complete

---

## Reporting Issues

When reporting bugs, include:

1. **Description** - What went wrong?
2. **Steps to reproduce** - How to trigger the bug
3. **Expected behavior** - What should happen
4. **Actual behavior** - What actually happened
5. **Logs** - Relevant error messages
6. **Environment** - OS, Python version, etc.

Example:
```
**Bug:** AI doesn't respond after booking appointment

**Steps:**
1. Call phone number
2. Say "book an appointment"
3. Provide all details
4. After confirmation, ask another question

**Expected:** AI responds to new question
**Actual:** Silence

**Logs:**
```
[ERROR] ai_agent.py: Conversation history overflow
```

**Environment:** Ubuntu 22.04, Python 3.11, latest code
```

---

**Testing complete! 🎉 Ready for production!**
