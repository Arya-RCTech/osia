"""
test_03_tag_parsing.py — Server-side + client-side tag parsing round-trip
════════════════════════════════════════════════════════════════════════

Risk area #2 from test brief: two independent parsers must agree.
Server: stream_processor.py extracts <think>, wraps Gemini reasoning into
<|channel>thought...<channel|>, strips scratchpad/thread_title/timestamps.
Client: chat_provider.dart regex (tested here as equivalent Python regex).

Also covers the 'tag split across SSE chunks' failure mode.
"""

import os
import sys
import re
import time
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call


# ─────────────────────────────────────────────────────────────────────────────
# Unit: StreamProcessor._strip_hidden_thinking
# ─────────────────────────────────────────────────────────────────────────────

class TestStripHiddenThinking:
    """Verify that _strip_hidden_thinking removes all reasoning traces."""

    def setup_method(self):
        from stream_processor import StreamProcessor
        self.strip = StreamProcessor._strip_hidden_thinking

    def test_strip_ollama_think_tags(self):
        """<think>...</think> blocks must be fully removed."""
        raw = "Hello <think>internal reasoning here</think> world!"
        r = timed_call(self.strip, raw)
        assert "<think>" not in r.value
        assert "internal reasoning" not in r.value
        assert "Hello" in r.value and "world!" in r.value
        print(f"  ✓ <think> tags stripped  ({r.elapsed_ms:.2f}ms)")

    def test_strip_gemma_channel_tags(self):
        """<|channel>thought...<channel|> blocks must be fully removed."""
        raw = "Visible text <|channel>thought\nI'm reasoning deeply\n<channel|>assistant more visible"
        r = timed_call(self.strip, raw)
        assert "<|channel>" not in r.value
        assert "reasoning deeply" not in r.value
        assert "Visible text" in r.value
        print(f"  ✓ <|channel>thought tags stripped  ({r.elapsed_ms:.2f}ms)")

    def test_strip_unclosed_think_tag(self):
        """An unclosed <think> at end of response (stream cutoff) must still be removed."""
        raw = "Hello <think>partial reasoning never closed"
        r = timed_call(self.strip, raw)
        assert "<think>" not in r.value
        assert "partial reasoning" not in r.value
        print(f"  ✓ Unclosed <think> stripped  ({r.elapsed_ms:.2f}ms)")

    def test_strip_multiple_think_blocks(self):
        """Multiple <think> blocks in one response must all be removed."""
        raw = "<think>first</think>A<think>second</think>B<think>third</think>C"
        r = timed_call(self.strip, raw)
        assert r.value == "ABC"
        print(f"  ✓ Multiple <think> blocks stripped  ({r.elapsed_ms:.2f}ms)")

    def test_strip_case_insensitive(self):
        """Tags must be matched case-insensitively."""
        raw = "text <THINK>UPPER CASE</THINK> more text"
        r = timed_call(self.strip, raw)
        assert "UPPER CASE" not in r.value
        print(f"  ✓ Case-insensitive stripping  ({r.elapsed_ms:.2f}ms)")

    def test_no_tags_passthrough(self):
        """Text without any tags must pass through unchanged."""
        raw = "Just a normal response with no special tags."
        r = timed_call(self.strip, raw)
        assert r.value == raw.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Unit: StreamProcessor._extract_scratchpad
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractScratchpad:
    """Verify scratchpad extraction, state mutation, and tag stripping."""

    def setup_method(self):
        from stream_processor import StreamProcessor
        self.extract = StreamProcessor._extract_scratchpad

    def _make_mock_state(self, initial_scratchpad="No current internal notes."):
        """Create a minimal state-like object with a mutable scratchpad."""
        class MockState:
            def __init__(self):
                self.scratchpad = initial_scratchpad
        return MockState()

    def test_scratchpad_extracted_and_hidden(self):
        """<scratchpad>...</scratchpad> must be extracted and removed from visible output."""
        state = self._make_mock_state()
        raw = "Hello user! <scratchpad>User seems happy. Goal: help with code.</scratchpad>"
        r = timed_call(self.extract, state, raw)
        visible, internal = r.value
        assert "<scratchpad>" not in visible
        assert "Hello user!" in visible
        assert internal == "User seems happy. Goal: help with code."
        print(f"  ✓ Scratchpad extracted  ({r.elapsed_ms:.2f}ms)")

    def test_scratchpad_updates_state(self):
        """Extracted scratchpad content must update state.scratchpad."""
        state = self._make_mock_state("No current internal notes.")
        raw = "Reply <scratchpad>New observation.</scratchpad>"
        self.extract(state, raw)
        assert state.scratchpad == "New observation."

    def test_scratchpad_appends_when_existing(self):
        """If scratchpad already has content, new content must append with '- ' prefix."""
        state = self._make_mock_state("Existing note.")
        raw = "Reply <scratchpad>Additional note.</scratchpad>"
        self.extract(state, raw)
        assert "Existing note." in state.scratchpad
        assert "- Additional note." in state.scratchpad

    def test_thread_title_stripped(self):
        """<thread_title>...</thread_title> must be stripped from visible output."""
        state = self._make_mock_state()
        raw = "Hello! <scratchpad>note</scratchpad> <thread_title>My Cool Thread</thread_title>"
        visible, _ = self.extract(state, raw)
        assert "<thread_title>" not in visible
        assert "My Cool Thread" not in visible

    def test_thread_naming_stripped(self):
        """<thread_naming>...</thread_naming> must be stripped from visible output."""
        state = self._make_mock_state()
        raw = "Hello! <thread_naming>some directive</thread_naming>"
        visible, _ = self.extract(state, raw)
        assert "<thread_naming>" not in visible

    def test_just_now_timestamp_stripped(self):
        """[Just now] markers must be stripped from visible output."""
        state = self._make_mock_state()
        raw = "[Just now] Hello user!"
        visible, _ = self.extract(state, raw)
        assert "[Just now]" not in visible
        assert "Hello user!" in visible

    def test_iso_timestamp_prefix_stripped(self):
        """ISO timestamp prefixes like [2026-01-01T...] ASSISTANT: must be stripped."""
        state = self._make_mock_state()
        raw = "[2026-08-30T12:00:00+00:00] ASSISTANT: Here is my response."
        visible, _ = self.extract(state, raw)
        assert "2026-08-30" not in visible
        assert "ASSISTANT:" not in visible
        assert "Here is my response." in visible

    def test_gemma_channel_thought_takes_priority_as_internal_note(self):
        """If <|channel>thought content is present, it should be used as internal_note over <scratchpad>."""
        state = self._make_mock_state()
        raw = "<|channel>thought\nI'm thinking about the problem\n<channel|>Visible reply <scratchpad>fallback note</scratchpad>"
        visible, internal = self.extract(state, raw)
        # Gemma channel thought takes priority
        assert internal == "I'm thinking about the problem"
        assert "<|channel>" not in visible

    def test_empty_response(self):
        """Empty input must not crash."""
        state = self._make_mock_state()
        visible, internal = self.extract(state, "")
        assert visible == ""
        assert internal is None


# ─────────────────────────────────────────────────────────────────────────────
# Unit: StreamProcessor._extract_thread_title
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractThreadTitle:

    def setup_method(self):
        from stream_processor import StreamProcessor
        self.extract = StreamProcessor._extract_thread_title

    def test_basic_title_extraction(self):
        raw = "Hello! <thread_title>AI Memory Discussion</thread_title>"
        r = timed_call(self.extract, raw)
        assert r.value == "AI Memory Discussion"
        print(f"  ✓ Title extracted  ({r.elapsed_ms:.2f}ms)")

    def test_title_strips_quotes(self):
        """Titles wrapped in quotes must have quotes stripped."""
        raw = '<thread_title>"Quoted Title"</thread_title>'
        assert self.extract(raw) == "Quoted Title"

    def test_title_truncated_at_60_chars(self):
        """Titles longer than 60 chars must be truncated to 57 + '...'."""
        long_title = "A" * 80
        raw = f"<thread_title>{long_title}</thread_title>"
        result = self.extract(raw)
        assert len(result) <= 60
        assert result.endswith("...")

    def test_no_title_returns_none(self):
        assert self.extract("No title here") is None

    def test_empty_title_returns_none(self):
        assert self.extract("<thread_title></thread_title>") is None
        assert self.extract("<thread_title>   </thread_title>") is None


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Client-side regex (Dart chat_provider.dart) parity check
# ─────────────────────────────────────────────────────────────────────────────

class TestClientServerTagParity:
    """
    Test brief §2: 'Cross-check test: for each provider, confirm server output
    → client regex round-trips into the correct thinkContent vs content split.'

    We replicate the Dart chat_provider.dart regex logic in Python and verify
    that server-produced output is correctly parsed by both sides.
    """

    @staticmethod
    def dart_extract_think_content(full_buffer):
        """
        Python equivalent of chat_provider.dart's thinking extraction regex.
        Extracts <think>...</think> and <|channel>thought...<channel|> blocks.
        """
        think_content = ""

        # Dart regex: RegExp(r'<think>(.*?)</think>', dotAll: true)
        for m in re.finditer(r"<think>(.*?)</think>", full_buffer, re.DOTALL):
            think_content += m.group(1).strip() + "\n"

        # Dart regex: RegExp(r'<\|channel>thought(.*?)<channel\|>', dotAll: true)
        for m in re.finditer(r"<\|channel>thought(.*?)<channel\|>", full_buffer, re.DOTALL):
            think_content += m.group(1).strip() + "\n"

        return think_content.strip()

    @staticmethod
    def dart_strip_tags(text):
        """
        Python equivalent of chat_provider.dart's tag stripping.
        Removes thinking tags, scratchpad, thread_title, and [Just now].
        """
        # Strip thinking
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|channel>thought.*?<channel\|>(?:assistant)?", "", text, flags=re.DOTALL)
        # Strip scratchpad
        text = re.sub(r"<scratchpad>.*?</scratchpad>", "", text, flags=re.DOTALL)
        # Strip thread title
        text = re.sub(r"<thread_title>.*?</thread_title>", "", text, flags=re.DOTALL)
        # Strip [Just now]
        text = re.sub(r"\[Just now\]", "", text, flags=re.IGNORECASE)
        return text.strip()

    def test_ollama_think_roundtrip(self):
        """Ollama-style <think> output must parse identically on server and client."""
        server_output = "<think>Reasoning about the question...</think>Here's my answer!"

        # Server-side
        from stream_processor import StreamProcessor
        server_visible = StreamProcessor._strip_hidden_thinking(server_output)

        # Client-side
        client_think = self.dart_extract_think_content(server_output)
        client_visible = self.dart_strip_tags(server_output)

        assert "Reasoning about the question" not in server_visible
        assert "Here's my answer!" in server_visible
        assert "Reasoning about the question" in client_think
        assert "Here's my answer!" in client_visible
        assert "Reasoning about the question" not in client_visible
        print(f"  ✓ Ollama <think> round-trip: server + client agree")

    def test_gemma_channel_roundtrip(self):
        """Gemma-style <|channel>thought output must parse identically on both sides."""
        server_output = "<|channel>thought\nDeep reasoning about context\n<channel|>The actual response."

        from stream_processor import StreamProcessor
        server_visible = StreamProcessor._strip_hidden_thinking(server_output)

        client_think = self.dart_extract_think_content(server_output)
        client_visible = self.dart_strip_tags(server_output)

        assert "Deep reasoning" not in server_visible
        assert "The actual response." in server_visible
        assert "Deep reasoning" in client_think
        assert "The actual response." in client_visible
        print(f"  ✓ Gemma <|channel>thought round-trip: server + client agree")

    def test_mixed_thinking_and_scratchpad(self):
        """A response with BOTH thinking and scratchpad must parse correctly."""
        server_output = (
            "<think>Let me think...</think>"
            "Here is my answer. "
            "<scratchpad>User seems confused about RAG.</scratchpad>"
            "<thread_title>RAG Discussion</thread_title>"
        )

        from stream_processor import StreamProcessor

        class MockState:
            scratchpad = "No current internal notes."

        state = MockState()
        server_visible, internal = StreamProcessor._extract_scratchpad(state, server_output)

        client_think = self.dart_extract_think_content(server_output)
        client_visible = self.dart_strip_tags(server_output)

        # Server: visible text should be clean
        assert "Let me think" not in server_visible
        assert "User seems confused" not in server_visible
        assert "RAG Discussion" not in server_visible
        assert "Here is my answer." in server_visible

        # Client: thinking extracted, visible clean
        assert "Let me think" in client_think
        assert "Here is my answer." in client_visible
        assert "User seems confused" not in client_visible
        print(f"  ✓ Mixed thinking+scratchpad+title: server + client agree")

    def test_no_special_tags_passthrough(self):
        """Plain text without tags must pass through identically on both sides."""
        plain = "Just a normal response, nothing special."

        from stream_processor import StreamProcessor
        server_visible = StreamProcessor._strip_hidden_thinking(plain)
        client_visible = self.dart_strip_tags(plain)

        assert server_visible == plain
        assert client_visible == plain

    def test_tag_split_across_chunks_accumulation(self):
        """
        Test brief §2: 'a stream where a tag is split across two SSE chunks
        (e.g. <thi + nk>) — regex-per-chunk is a classic place this breaks.'

        This tests that accumulating chunks into a full buffer before
        applying regex (as both server and client do) handles the split correctly.
        """
        # Simulate SSE chunks where tags are split
        chunks = [
            "Hello ",
            "<thi",
            "nk>Deep r",
            "easoning here</thi",
            "nk>",
            " Visible response.",
        ]

        # Both server and client accumulate into a buffer, then regex
        full_buffer = "".join(chunks)

        from stream_processor import StreamProcessor
        server_visible = StreamProcessor._strip_hidden_thinking(full_buffer)
        client_think = self.dart_extract_think_content(full_buffer)
        client_visible = self.dart_strip_tags(full_buffer)

        assert "Deep reasoning" not in server_visible
        assert "Hello" in server_visible
        assert "Visible response." in server_visible
        assert "Deep reasoning" in client_think
        print(f"  ✓ Tag split across chunks: accumulate-then-regex works")

    def test_channel_tag_split_across_chunks(self):
        """<|channel>thought split across chunks must be handled by buffer accumulation."""
        chunks = [
            "Start ",
            "<|chan",
            "nel>tho",
            "ught\nMy reasoning\n<cha",
            "nnel|>",
            " End.",
        ]
        full_buffer = "".join(chunks)

        from stream_processor import StreamProcessor
        server_visible = StreamProcessor._strip_hidden_thinking(full_buffer)
        client_think = self.dart_extract_think_content(full_buffer)

        assert "My reasoning" not in server_visible
        assert "My reasoning" in client_think
        print(f"  ✓ <|channel> split across chunks: handled correctly")


# ─────────────────────────────────────────────────────────────────────────────
# Unit: LLM Transport history stripping
# ─────────────────────────────────────────────────────────────────────────────

class TestTransportHistoryStripping:
    """
    llm_transport.py strips past <|channel>thought...<channel|> blocks from
    conversation history before re-sending. This must work correctly to save
    context window budget.
    """

    def test_thought_blocks_stripped_from_history(self):
        """Past assistant messages with thought channels must have them stripped."""
        import re
        # This is the exact regex used in llm_transport.py
        pattern = r"<\|channel>thought.*?<channel\|>"

        assistant_msg = (
            "<|channel>thought\nI was thinking about the problem.\n<channel|>"
            "Here is my actual response."
        )
        cleaned = re.sub(pattern, "", assistant_msg, flags=re.DOTALL | re.IGNORECASE).strip()
        assert "<|channel>" not in cleaned
        assert "I was thinking" not in cleaned
        assert "Here is my actual response." in cleaned
        print(f"  ✓ Thought blocks stripped from history")

    def test_multiple_thought_blocks_stripped(self):
        """Multiple thought blocks in one message must all be stripped."""
        import re
        pattern = r"<\|channel>thought.*?<channel\|>"

        msg = (
            "<|channel>thought\nFirst thought\n<channel|>"
            "Response part 1 "
            "<|channel>thought\nSecond thought\n<channel|>"
            "Response part 2"
        )
        cleaned = re.sub(pattern, "", msg, flags=re.DOTALL | re.IGNORECASE).strip()
        assert "First thought" not in cleaned
        assert "Second thought" not in cleaned
        assert "Response part 1" in cleaned
        assert "Response part 2" in cleaned
