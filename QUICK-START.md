# 🚀 Quick Start - Real-Time Voice AI Agent

**Repository:** https://github.com/byte-ai-assistant/realtime-voice-agent

---

## Get Started in 5 Minutes

### Step 1: Clone & Setup (2 min)

```bash
git clone https://github.com/byte-ai-assistant/realtime-voice-agent.git
cd realtime-voice-agent
./scripts/setup.sh
```

### Step 2: Get API Keys (2 min)

**Already Have:**
- ✅ Anthropic (Claude)
- ✅ ElevenLabs (TTS)

**Need:**
- Deepgram - https://deepgram.com/ (free trial)
- Twilio - https://www.twilio.com/ (free trial + phone number)

**Add to .env:**
```bash
cp .env.example .env
nano .env  # Add your keys
```

### Step 3: Run (1 min)

```bash
./scripts/run.sh
```

Server starts at `http://localhost:8000`

### Step 4: Test

**Option A: Use ngrok (fastest)**
```bash
brew install ngrok
ngrok http 8000
# Copy ngrok URL
```

**Option B: Deploy to GCP**
```bash
export GCP_PROJECT_ID=your-project
./scripts/deploy-gcp.sh
# Uses VM external IP
```

**Configure Twilio:**
1. Go to console.twilio.com
2. Your phone number → Voice webhook
3. Set to: `http://YOUR_URL:8000/webhook/voice`
4. Method: POST

**Make the call!** 📞

---

## What to Say

```
"What can you help me with?"
→ AI explains capabilities

"How much does ByteAI cost?"
→ AI answers from knowledge base

"I'd like to book an appointment for tomorrow at 2pm"
→ AI books appointment

"Check my appointment"
→ AI looks up your booking

"I need to speak with a human"
→ AI escalates to support
```

---

## Files You Care About

- **README.md** - Full quick start guide
- **HANDOFF.md** - Complete handoff document
- **docs/DEPLOYMENT.md** - GCP deployment guide
- **.env** - Your API keys go here
- **knowledge/sample_kb.json** - Edit to add your FAQs

---

## Common Issues

**"Dependencies failed"**
```bash
python3 --version  # Need 3.11+
./scripts/setup.sh
```

**"API key error"**
```bash
source .env
echo $ANTHROPIC_API_KEY  # Should show your key
```

**"No audio on call"**
- Check server logs
- Verify Twilio webhook URL
- Ensure port 8000 is open

---

## Next Steps

1. ✅ Make test call (5 minutes)
2. Deploy to GCP (15 minutes)
3. Customize knowledge base (30 minutes)
4. Go live! 🚀

---

**Full docs:** https://github.com/byte-ai-assistant/realtime-voice-agent

**Questions?** See HANDOFF.md or README.md

**LET'S GO!** 🎤🤖
