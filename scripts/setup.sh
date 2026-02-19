#!/bin/bash
# Real-Time Voice AI Agent - Setup Script

set -e

echo "🚀 Setting up Real-Time Voice AI Agent..."
echo ""

# Check Python version
echo "📋 Checking Python version..."
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
required_version="3.11"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11 or higher."
    exit 1
fi

echo "✅ Python $python_version found"
echo ""

# Create virtual environment
echo "🔧 Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Virtual environment created"
else
    echo "ℹ️  Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate
echo "✅ Virtual environment activated"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Dependencies installed"
echo ""

# Create directories
echo "📁 Creating directories..."
mkdir -p data/chroma
mkdir -p data/recordings
mkdir -p logs
echo "✅ Directories created"
echo ""

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your API keys!"
    echo ""
else
    echo "ℹ️  .env file already exists"
    echo ""
fi

# Verify API keys
echo "🔑 Checking API keys..."
source .env

missing_keys=()

if [ -z "$ANTHROPIC_API_KEY" ]; then
    missing_keys+=("ANTHROPIC_API_KEY")
fi

if [ -z "$ELEVENLABS_API_KEY" ]; then
    missing_keys+=("ELEVENLABS_API_KEY")
fi

if [ -z "$DEEPGRAM_API_KEY" ]; then
    missing_keys+=("DEEPGRAM_API_KEY")
fi

if [ ${#missing_keys[@]} -gt 0 ]; then
    echo "⚠️  Missing API keys:"
    for key in "${missing_keys[@]}"; do
        echo "   - $key"
    done
    echo ""
    echo "Please add these keys to your .env file and run setup again."
    echo ""
else
    echo "✅ All required API keys found"
    echo ""
fi

# Test imports
echo "🧪 Testing Python imports..."
python3 -c "
import fastapi
import anthropic
import elevenlabs
from deepgram import DeepgramClient
import chromadb
print('✅ All imports successful')
"
echo ""

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your API keys (if not done already)"
echo "2. Run './scripts/run.sh' to start the server"
echo "3. Configure Twilio webhook to point to your server"
echo "4. Make a test call!"
echo ""
