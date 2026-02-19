# Real-Time Voice AI Agent 🎤🤖

A production-ready voice AI agent that answers phone calls, talks to customers in real-time, and takes actions like booking appointments.

**Built with:** Claude Sonnet 4.5, Deepgram, ElevenLabs, Twilio, and FastAPI

---

## 🚀 Quick Start (5 minutes)

### Prerequisites

1. **Python 3.11+** installed
2. **API Keys** (free trials available):
   - [Anthropic](https://console.anthropic.com/) (Claude)
   - [ElevenLabs](https://elevenlabs.io/) (Text-to-Speech)
   - [Deepgram](https://deepgram.com/) (Speech-to-Text)
   - [Twilio](https://www.twilio.com/) (Phone calls)
   - [OpenAI](https://platform.openai.com/) (Embeddings - optional)

3. **Google Cloud account** (for deployment)

### Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/byte-ai-assistant/realtime-voice-agent.git
cd realtime-voice-agent

# 2. Run setup script
./scripts/setup.sh

# 3. Edit .env and add your API keys
nano .env  # or use your preferred editor

# 4. Start the server
./scripts/run.sh
```

Server will start on `http://localhost:8000`

### Configure Twilio

1. **Get a phone number** from Twilio console
2. **Configure webhook**: Set incoming call webhook to `http://YOUR_SERVER_IP:8000/webhook/voice`
3. **Make a test call** to your Twilio number!

---

## 📋 Features

- ✅ **Real-time voice conversations** - Natural, low-latency responses (<2s)
- ✅ **Knowledge base integration** - Answers questions using RAG
- ✅ **Function calling** - Books appointments, checks status, escalates to humans
- ✅ **Streaming AI** - Claude streams responses for minimal latency
- ✅ **Production-ready** - Error handling, logging, health checks
- ✅ **Easy deployment** - Docker + GCP one-click deploy

---

## 🏗️ Architecture

```
Phone Call → Twilio → WebSocket → Voice Agent
                          ↓
                    ┌─────┴─────┐
                    │  STT      │  Deepgram
                    │  AI       │  Claude
                    │  RAG      │  ChromaDB
                    │  Tools    │  Functions
                    │  TTS      │  ElevenLabs
                    └───────────┘
```

**Response Flow:**
1. Customer speaks (1-3s)
2. Deepgram transcribes (~300ms)
3. RAG retrieves context (~50ms)
4. Claude generates response (~400ms streaming)
5. ElevenLabs synthesizes speech (~250ms first chunk)
6. Audio streams back to customer

**Total latency: ~1500ms** ⚡

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

---

## 🛠️ Configuration

### Environment Variables

Create a `.env` file (use `.env.example` as template):

```bash
# Twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890

# Speech-to-Text
DEEPGRAM_API_KEY=your_deepgram_key

# Text-to-Speech
ELEVENLABS_API_KEY=your_elevenlabs_key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM  # Rachel (default)

# AI
ANTHROPIC_API_KEY=your_anthropic_key

# Embeddings (optional)
OPENAI_API_KEY=your_openai_key

# Server
WEBSOCKET_URL=wss://your-server.com/ws/media
```

### Customize Knowledge Base

Edit `knowledge/sample_kb.json` to add your own FAQs:

```json
{
  "documents": [
    {
      "id": "faq-001",
      "category": "pricing",
      "question": "How much does it cost?",
      "answer": "Our service costs $99/month..."
    }
  ]
}
```

---

## 🚀 Deployment

### Docker (Local)

```bash
# Build and run
docker-compose -f docker/docker-compose.yml up -d

# Check logs
docker-compose -f docker/docker-compose.yml logs -f

# Stop
docker-compose -f docker/docker-compose.yml down
```

### Google Cloud Platform

```bash
# Configure GCP project
export GCP_PROJECT_ID=your-project-id
export GCP_REGION=us-central1

# Deploy (creates VM, installs Docker, runs container)
./scripts/deploy-gcp.sh
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed instructions.

---

## 🧪 Testing

### Unit Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Run tests
pytest tests/ -v
```

### Manual Testing

1. **Health check:**
   ```bash
   curl http://localhost:8000/health
   ```

2. **Make a test call:**
   - Call your Twilio number
   - Say: "What can you help me with?"
   - Try: "I'd like to book an appointment for tomorrow at 2pm"
   - Try: "Check my appointment status"

See [docs/TESTING.md](docs/TESTING.md) for more tests.

---

## 📚 API Reference

### Endpoints

- `GET /` - Health check
- `GET /health` - Detailed health status
- `POST /webhook/voice` - Twilio webhook (TwiML)
- `WebSocket /ws/media` - Real-time audio streaming
- `GET /metrics` - Prometheus metrics

### Tools (Function Calling)

**book_appointment**
```python
{
  "date": "2025-02-20",
  "time": "14:00",
  "name": "John Doe",
  "phone": "+1234567890"
}
```

**check_appointment**
```python
{
  "phone": "+1234567890"
}
```

**escalate_to_human**
```python
{
  "reason": "Complex technical issue",
  "callback_number": "+1234567890"
}
```

---

## 🔧 Troubleshooting

### "ModuleNotFoundError"
Run `./scripts/setup.sh` to install dependencies.

### "ANTHROPIC_API_KEY not set"
Edit `.env` and add your API keys.

### "Connection refused" when calling
1. Check server is running: `curl http://localhost:8000/health`
2. Verify Twilio webhook URL is correct
3. Check firewall allows port 8000

### Poor voice quality
- Check internet connection
- Verify Deepgram/ElevenLabs API keys are valid
- Try a different ElevenLabs voice

### Slow responses
- Check server location (should be close to Twilio)
- Verify all API keys are working
- Check server resources (CPU/RAM)

---

## 💰 Cost Estimate

**100 calls/day, 3 minutes average:**

| Service | Monthly Cost |
|---------|--------------|
| Twilio | $27 |
| Deepgram | $39 |
| ElevenLabs | $81 |
| Claude | $75 |
| GCP VM | $50 |
| **Total** | **~$272/month** |

**Per-call cost: ~$0.90**

---

## 🗂️ Project Structure

```
realtime-voice-agent/
├── src/
│   ├── server.py              # Main FastAPI server
│   ├── voice_handler.py       # Audio streaming (STT/TTS)
│   ├── ai_agent.py            # Claude integration
│   ├── knowledge_base.py      # RAG pipeline
│   └── tools.py               # Function calling
├── knowledge/
│   └── sample_kb.json         # Sample FAQ database
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── scripts/
│   ├── setup.sh               # One-time setup
│   ├── run.sh                 # Start server
│   └── deploy-gcp.sh          # Deploy to GCP
├── tests/
│   └── test_*.py              # Unit tests
└── docs/
    ├── ARCHITECTURE.md        # Technical details
    ├── DEPLOYMENT.md          # Deployment guide
    └── TESTING.md             # Testing guide
```

---

## 🎯 Roadmap

- [ ] Add interrupt handling (let user interrupt AI)
- [ ] Multi-language support
- [ ] Custom voice training
- [ ] Call analytics dashboard
- [ ] Sentiment analysis
- [ ] Call recording + transcripts
- [ ] CRM integration
- [ ] Load balancing for high volume

---

## 📖 Documentation

- [Technical Architecture](docs/ARCHITECTURE.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Testing Guide](docs/TESTING.md)
- [Technical Plan](docs/TECHNICAL-PLAN.md)

---

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

---

## 📄 License

MIT License - see LICENSE file for details

---

## 🆘 Support

- **Issues:** [GitHub Issues](https://github.com/byte-ai-assistant/realtime-voice-agent/issues)
- **Discussions:** [GitHub Discussions](https://github.com/byte-ai-assistant/realtime-voice-agent/discussions)
- **Email:** support@byteai.com

---

## 🙏 Acknowledgments

Built with:
- [Anthropic Claude](https://www.anthropic.com/) - AI/LLM
- [Deepgram](https://deepgram.com/) - Speech-to-Text
- [ElevenLabs](https://elevenlabs.io/) - Text-to-Speech
- [Twilio](https://www.twilio.com/) - Telephony
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [ChromaDB](https://www.trychroma.com/) - Vector database

---

**Made with ❤️ by ByteAI**

Ready to build your voice AI? Star this repo and let's go! ⭐
