#!/bin/bash
# Real-Time Voice AI Agent - Run Script

set -e

echo "🚀 Starting Real-Time Voice AI Agent..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run './scripts/setup.sh' first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Load environment variables
if [ -f ".env" ]; then
    source .env
else
    echo "❌ .env file not found. Run './scripts/setup.sh' first."
    exit 1
fi

# Check for required API keys
if [ -z "$ANTHROPIC_API_KEY" ] || [ -z "$ELEVENLABS_API_KEY" ] || [ -z "$DEEPGRAM_API_KEY" ]; then
    echo "❌ Missing required API keys in .env file"
    echo "Please ensure these are set:"
    echo "  - ANTHROPIC_API_KEY"
    echo "  - ELEVENLABS_API_KEY"
    echo "  - DEEPGRAM_API_KEY"
    exit 1
fi

# Start server
echo "✅ All checks passed"
echo "🎤 Starting voice agent server..."
echo ""

cd src && python server.py
