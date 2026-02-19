#!/bin/bash
# GCP VM Startup Script - Installs Docker and sets up the application

set -e

echo "🚀 Starting VM setup..."

# Update system
apt-get update
apt-get upgrade -y

# Install Docker
echo "🐳 Installing Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
rm get-docker.sh

# Install Docker Compose
echo "🐳 Installing Docker Compose..."
apt-get install -y docker-compose

# Create application directory
echo "📁 Creating application directory..."
mkdir -p /opt/voice-agent
cd /opt/voice-agent

# Clone repository (replace with actual repo URL)
echo "📦 Cloning repository..."
# git clone https://github.com/byte-ai-assistant/realtime-voice-agent.git .

# For now, we'll expect files to be uploaded manually or via deploy script

# Create .env file template
cat > .env << 'EOF'
# Server Configuration
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# Add your API keys here
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
WEBSOCKET_URL=
EOF

echo "✅ VM setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Upload application files to /opt/voice-agent"
echo "2. Edit /opt/voice-agent/.env and add API keys"
echo "3. Run: cd /opt/voice-agent && docker-compose up -d"
