"""
Unit tests for server utilities
"""

import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from server import _find_sentence_boundary


class TestFindSentenceBoundary:
    """Tests for the sentence boundary detection function"""

    def test_period_space(self):
        """Should find boundary at period followed by space"""
        assert _find_sentence_boundary("Hello world. How are you?") == 13

    def test_exclamation_space(self):
        """Should find boundary at exclamation followed by space"""
        assert _find_sentence_boundary("Great! Let me help.") == 7

    def test_question_space(self):
        """Should find boundary at question mark followed by space"""
        assert _find_sentence_boundary("How are you? I'm fine.") == 13

    def test_no_boundary(self):
        """Should return -1 when no sentence boundary found"""
        assert _find_sentence_boundary("Hello world") == -1

    def test_period_at_end_no_space(self):
        """Period at end without trailing space is not a boundary"""
        assert _find_sentence_boundary("Hello world.") == -1

    def test_empty_string(self):
        """Empty string should return -1"""
        assert _find_sentence_boundary("") == -1

    def test_multiple_sentences(self):
        """Should find the FIRST boundary"""
        text = "First sentence. Second sentence. Third."
        boundary = _find_sentence_boundary(text)
        assert boundary == 16
        # After extracting first sentence, should find the next
        remaining = text[boundary:]
        assert remaining == "Second sentence. Third."
        assert _find_sentence_boundary(remaining) == 17

    def test_period_newline(self):
        """Should find boundary at period followed by newline"""
        assert _find_sentence_boundary("Hello.\nWorld") == 7

    def test_exclamation_newline(self):
        """Should find boundary at exclamation followed by newline"""
        assert _find_sentence_boundary("Great!\nThanks") == 7
