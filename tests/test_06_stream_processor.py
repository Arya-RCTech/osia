"""
test_06_stream_processor.py — StreamProcessor integration tests
═══════════════════════════════════════════════════════════════

Tests the real-time streaming pipeline with mocked transports.
Covers:
- Tag interception during streaming (16-char safety buffer)
- Scratchpad extraction from stream output
- Thread title extraction and rename trigger
- CancelledError partial save behavior
- Tool call request routing
"""

import os
import sys
import re
import time
import asyncio
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: Mock transport and state
# ─────────────────────────────────────────────────────────────────────────────

class MockState:
    """Minimal StateManager mock for stream tests."""
    def __init__(self):
        self.scratchpad = "No current internal notes."
        self.current_thread_id = 1
        self.saved_interactions = []
        self.renamed_threads = []

    def save_interaction(self, user_msg, ai_msg, internal_note=None):
        self.saved_interactions.append({
            "user_msg": user_msg,
            "ai_msg": ai_msg,
            "internal_note": internal_note,
        })

    def rename_thread(self, thread_id, new_name):
        self.renamed_threads.append((thread_id, new_name))


class MockTransport:
    """Mock LLMTransport that yields predefined chunks."""
    def __init__(self, chunks, provider="groq"):
        self._chunks = chunks
        self._provider = provider

    def call_stream(self, model_id, messages, thinking=False, tools=None):
        """Synchronous generator for non-ollama providers."""
        for chunk in self._chunks:
            yield chunk


class MockTransportAsync:
    """Mock LLMTransport that yields predefined chunks via async generator (ollama path)."""
    def __init__(self, chunks):
        self._chunks = chunks

    def call_stream(self, model_id, messages, thinking=False, tools=None):
        async def _gen():
            for chunk in self._chunks:
                yield chunk
        return _gen()


# ─────────────────────────────────────────────────────────────────────────────
# Helper to run async stream processor and collect results
# ─────────────────────────────────────────────────────────────────────────────

async def collect_stream(state, transport, user_msg="test", messages=None, model_id="test-model", thinking=False):
    """Run StreamProcessor.process_stream and collect all yielded chunks."""
    from stream_processor import StreamProcessor

    if messages is None:
        messages = [{"role": "user", "content": user_msg}]

    chunks = []
    async for chunk in StreamProcessor.process_stream(
        state, transport, user_msg, messages, model_id, thinking, time.time()
    ):
        chunks.append(chunk)
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Patch model_registry for tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_registry(monkeypatch):
    """Patch registry.provider_for to return 'groq' for test models."""
    from model_registry import registry
    original_provider_for = registry.provider_for

    def _patched_provider_for(model_id):
        if model_id.startswith("test"):
            return "groq"
        return original_provider_for(model_id)

    monkeypatch.setattr(registry, "provider_for", _patched_provider_for)


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Basic streaming flow
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamProcessorBasicFlow:

    @pytest.mark.asyncio
    async def test_simple_stream_produces_chunks_and_done(self):
        """A simple stream must yield chunk events and a final done event."""
        state = MockState()
        transport = MockTransport(["Hello ", "world!"])

        chunks = await collect_stream(state, transport)

        chunk_events = [c for c in chunks if isinstance(c, dict) and c.get("type") == "chunk"]
        done_events = [c for c in chunks if isinstance(c, dict) and c.get("type") == "done"]

        assert len(chunk_events) > 0, "No chunk events emitted"
        assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
        assert "latency" in done_events[0]
        print(f"  ✓ Simple stream: {len(chunk_events)} chunks + 1 done")

    @pytest.mark.asyncio
    async def test_stream_saves_interaction(self):
        """After streaming completes, save_interaction must be called with full response."""
        state = MockState()
        transport = MockTransport(["Hello ", "world!"])

        await collect_stream(state, transport, user_msg="Hi there")

        assert len(state.saved_interactions) == 1
        assert state.saved_interactions[0]["user_msg"] == "Hi there"
        assert "Hello" in state.saved_interactions[0]["ai_msg"]
        assert "world" in state.saved_interactions[0]["ai_msg"]
        print(f"  ✓ Stream saves interaction after completion")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Tag interception during streaming
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamTagInterception:

    @pytest.mark.asyncio
    async def test_scratchpad_not_emitted_to_client(self):
        """<scratchpad> content must be intercepted and NOT yielded as visible chunks."""
        state = MockState()
        transport = MockTransport([
            "Visible response. ",
            "<scratchpad>",
            "Internal thoughts here.",
            "</scratchpad>",
        ])

        chunks = await collect_stream(state, transport)

        # Concatenate all visible chunk content
        visible_text = ""
        for c in chunks:
            if isinstance(c, dict) and c.get("type") == "chunk":
                visible_text += c.get("content", "")

        assert "<scratchpad>" not in visible_text, \
            f"Scratchpad tag leaked to client: {visible_text!r}"
        assert "Internal thoughts here" not in visible_text
        assert "Visible response." in visible_text
        print(f"  ✓ Scratchpad intercepted during stream")

    @pytest.mark.asyncio
    async def test_thread_title_intercepted(self):
        """<thread_title> must be intercepted and trigger rename_thread."""
        state = MockState()
        transport = MockTransport([
            "Hello! ",
            "<scratchpad>note</scratchpad>",
            "<thread_title>My New Thread</thread_title>",
        ])

        chunks = await collect_stream(state, transport)

        # Check that rename was triggered
        assert len(state.renamed_threads) == 1
        assert state.renamed_threads[0][1] == "My New Thread"

        # Verify title not in visible output
        visible_text = "".join(
            c.get("content", "") for c in chunks
            if isinstance(c, dict) and c.get("type") == "chunk"
        )
        assert "My New Thread" not in visible_text
        print(f"  ✓ Thread title intercepted, rename triggered")

    @pytest.mark.asyncio
    async def test_16_char_safety_buffer(self):
        """
        The 16-char safety buffer prevents partial tag emission.
        A response ending mid-tag should still be handled correctly.
        """
        state = MockState()
        # "Hello world!" is 12 chars — less than 16-char buffer
        # So with the buffer, "Hello world!" shouldn't be emitted until more data arrives
        transport = MockTransport(["Hello world!"])

        chunks = await collect_stream(state, transport)

        visible_text = "".join(
            c.get("content", "") for c in chunks
            if isinstance(c, dict) and c.get("type") == "chunk"
        )
        # After stream ends, remaining buffer should be flushed
        assert "Hello world!" in visible_text
        print(f"  ✓ 16-char buffer flushes at stream end")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Scratchpad state mutation from stream
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamScratchpadMutation:

    @pytest.mark.asyncio
    async def test_scratchpad_updated_from_stream(self):
        """After stream with scratchpad, state.scratchpad must be updated."""
        state = MockState()
        transport = MockTransport([
            "Response here. ",
            "<scratchpad>User mood: happy. Goal: finish tests.</scratchpad>",
        ])

        await collect_stream(state, transport)

        assert "User mood: happy" in state.scratchpad
        print(f"  ✓ Scratchpad updated from stream  (new value: {state.scratchpad!r})")

    @pytest.mark.asyncio
    async def test_done_event_includes_scratchpad(self):
        """The done event must include the extracted scratchpad content."""
        state = MockState()
        transport = MockTransport([
            "Answer. ",
            "<scratchpad>Important observation.</scratchpad>",
        ])

        chunks = await collect_stream(state, transport)
        done = next(c for c in chunks if isinstance(c, dict) and c.get("type") == "done")

        assert done.get("scratchpad") == "Important observation."
        print(f"  ✓ Done event includes scratchpad")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Error handling
# ─────────────────────────────────────────────────────────────────────────────

class TestStreamErrorHandling:

    @pytest.mark.asyncio
    async def test_transport_error_yields_error_event(self):
        """If transport raises during streaming, an error event must be yielded."""
        state = MockState()

        class ErrorTransport:
            def call_stream(self, model_id, messages, thinking=False, tools=None):
                raise RuntimeError("Connection lost!")

        transport = ErrorTransport()
        chunks = await collect_stream(state, transport)

        error_events = [c for c in chunks if isinstance(c, dict) and c.get("type") == "error"]
        assert len(error_events) == 1
        assert "Connection lost" in error_events[0].get("error", "")
        print(f"  ✓ Transport error → error event")


# ─────────────────────────────────────────────────────────────────────────────
# Unit: Timestamp stripping
# ─────────────────────────────────────────────────────────────────────────────

class TestTimestampStripping:
    """Verify that [Just now] and ISO timestamps are stripped from final output."""

    def test_just_now_stripped_from_saved_response(self):
        from stream_processor import StreamProcessor
        
        class S:
            scratchpad = "No current internal notes."
        
        raw = "[Just now] Here is my response."
        visible, _ = StreamProcessor._extract_scratchpad(S(), raw)
        assert "[Just now]" not in visible
        assert "Here is my response." in visible

    def test_iso_with_role_prefix_stripped(self):
        from stream_processor import StreamProcessor
        
        class S:
            scratchpad = "No current internal notes."
        
        raw = "[2026-08-30T18:30:00+00:00] OSIA: Your answer is here."
        visible, _ = StreamProcessor._extract_scratchpad(S(), raw)
        assert "2026-08-30" not in visible
        assert "OSIA:" not in visible
        assert "Your answer is here." in visible
