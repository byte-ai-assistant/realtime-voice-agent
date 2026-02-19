"""
Shared test configuration and fixtures
"""

import os
import sys

# Ensure src directory is on the Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Set default environment variables for tests (prevents crashes from missing API keys)
os.environ.setdefault("DEEPGRAM_API_KEY", "test-deepgram-key")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-elevenlabs-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
