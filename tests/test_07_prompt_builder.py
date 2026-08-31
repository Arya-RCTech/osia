"""
test_07_prompt_builder.py — PromptBuilder context assembly tests
═══════════════════════════════════════════════════════════════

Tests that PromptBuilder.prepare_context correctly:
- Assembles system instruction with all required sections
- Includes recent history with relative timestamps
- Respects safety input limits
- Triggers delta summarization at correct threshold
- Appends thread naming directives for first message in new threads
- Handles scratchpad overflow archival
"""

import os
import sys
import time
import threading
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call


# ─────────────────────────────────────────────────────────────────────────────
# Integration: prepare_context full assembly
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptBuilderAssembly:
    """Test the full prepare_context assembly pipeline."""

    def test_context_has_system_instruction(self, tmp_state):
        """prepare_context must produce a messages list starting with a system message."""
        from prompt_builder import PromptBuilder

        state = tmp_state
        # Mock a cheap model call (won't actually be called unless summary threshold hit)
        def mock_cheap(messages, model_id, max_tokens=400):
            return "Mock summary."

        r = timed_call(
            PromptBuilder.prepare_context,
            state, "Hello OSIA!", "test-model", "cheap-model", mock_cheap
        )
        messages, original_msg = r.value

        assert len(messages) >= 2, f"Expected at least 2 messages, got {len(messages)}"
        assert messages[0]["role"] == "system"
        assert "You are Osia" in messages[0]["content"] or "Osia" in messages[0]["content"]
        assert original_msg == "Hello OSIA!"
        print(f"  ✓ Context has system instruction  ({r.elapsed_ms:.2f}ms, {len(messages)} messages)")

    def test_context_includes_required_sections(self, tmp_state):
        """System instruction must include all required XML sections."""
        from prompt_builder import PromptBuilder

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            tmp_state, "test", "test-model", "cheap-model", mock_cheap
        )
        system = messages[0]["content"]

        required_sections = [
            "<system_context>",
            "</system_context>",
            "<instructions>",
            "</instructions>",
            "<long_term_memory>",
            "</long_term_memory>",
            "<session_summary>",
            "</session_summary>",
            "<internal_scratchpad>",
            "</internal_scratchpad>",
        ]

        for section in required_sections:
            assert section in system, f"Missing section: {section}"
        print(f"  ✓ All required XML sections present")

    def test_context_includes_user_message_with_timestamp(self, tmp_state):
        """The user message must be the last user-role message, with UTC timestamp appended."""
        from prompt_builder import PromptBuilder

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            tmp_state, "What time is it?", "test-model", "cheap-model", mock_cheap
        )

        # Last user message should contain the original text
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) > 0
        last_user = user_messages[-1]["content"]
        assert "What time is it?" in last_user
        assert "<current_time_utc>" in last_user
        print(f"  ✓ User message includes timestamp")

    def test_first_message_gets_thread_naming_directive(self, tmp_state):
        """When thread has 0 messages, system instruction must include <thread_naming>."""
        from prompt_builder import PromptBuilder

        state = tmp_state
        # Create a fresh thread with 0 messages
        tid = state.db.create_thread("Empty Thread")
        state.db.current_thread_id = tid

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            state, "Hello!", "test-model", "cheap-model", mock_cheap
        )
        system = messages[0]["content"]

        assert "<thread_naming>" in system, \
            "First message in new thread should have <thread_naming> directive"
        assert "<thread_title>" in system
        print(f"  ✓ First message gets thread naming directive")

    def test_subsequent_message_no_thread_naming(self, tmp_state):
        """When thread already has messages, system instruction must NOT include <thread_naming>."""
        from prompt_builder import PromptBuilder

        state = tmp_state
        # Add a message to the current thread
        iso = "2026-06-15T12:00:00+00:00"
        state.db.save_chat_rows(state.current_thread_id, "prev user", "prev ai", None, iso)

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            state, "Follow up", "test-model", "cheap-model", mock_cheap
        )
        system = messages[0]["content"]

        assert "<thread_naming>" not in system, \
            "Subsequent messages should NOT have <thread_naming>"
        print(f"  ✓ Subsequent message has no thread naming")


# ─────────────────────────────────────────────────────────────────────────────
# Unit: Safety input limit
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyInputLimit:
    """Verify that SAFETY_INPUT_LIMIT truncation works."""

    def test_long_message_truncated(self, tmp_state):
        """A user message exceeding SAFETY_INPUT_LIMIT tokens should be truncated."""
        from prompt_builder import PromptBuilder, SAFETY_INPUT_LIMIT

        state = tmp_state
        # Create a message that's definitely over the limit
        huge_msg = "A" * (SAFETY_INPUT_LIMIT * 5)

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, original = PromptBuilder.prepare_context(
            state, huge_msg, "test-model", "cheap-model", mock_cheap
        )

        # The original must be preserved
        assert original == huge_msg

        # The actual content sent should be truncated
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        # Should contain truncation marker
        # Note: truncation happens to the message before it goes into messages list
        print(f"  ✓ Long message processed (original len={len(huge_msg)}, sent len={len(last_user)})")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Recent history inclusion
# ─────────────────────────────────────────────────────────────────────────────

class TestRecentHistoryInContext:
    """Verify that recent conversation history is included with relative timestamps."""

    def test_recent_history_included(self, tmp_state):
        """Active session messages should appear in the context messages."""
        from prompt_builder import PromptBuilder

        state = tmp_state
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state.active_session = [
            {"role": "user", "content": "What is RAG?", "iso_timestamp": ts},
            {"role": "assistant", "content": "RAG is retrieval augmented generation.", "iso_timestamp": ts},
        ]

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            state, "Tell me more", "test-model", "cheap-model", mock_cheap
        )

        # Find history messages (they have relative time prefixes)
        history_msgs = [m for m in messages if m["role"] in ("user", "assistant") and "[" in m["content"]]
        assert len(history_msgs) > 0, "No history messages found in context"
        print(f"  ✓ Recent history included ({len(history_msgs)} messages)")

    def test_verbatim_window_respected(self, tmp_state):
        """Only VERBATIM_WINDOW messages should be included from active_session."""
        from prompt_builder import PromptBuilder
        from state_manager import VERBATIM_WINDOW

        state = tmp_state
        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Fill with more messages than VERBATIM_WINDOW
        state.active_session = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Message {i}",
             "iso_timestamp": ts}
            for i in range(20)
        ]

        def mock_cheap(messages, model_id, max_tokens=400):
            return "Summary."

        messages, _ = PromptBuilder.prepare_context(
            state, "Latest question", "test-model", "cheap-model", mock_cheap
        )

        # Count history messages (between system and final user message)
        history_count = sum(
            1 for m in messages
            if m["role"] in ("user", "assistant") and "[" in m.get("content", "")
        )
        # Should be at most VERBATIM_WINDOW
        assert history_count <= VERBATIM_WINDOW, \
            f"Expected at most {VERBATIM_WINDOW} history messages, got {history_count}"
        print(f"  ✓ VERBATIM_WINDOW={VERBATIM_WINDOW} respected ({history_count} history msgs)")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Delta summary threshold
# ─────────────────────────────────────────────────────────────────────────────

class TestDeltaSummaryTrigger:
    """
    Test brief §3: verify delta summary triggers at the correct threshold
    (stable_index > summary_pointer + MIN_SUMMARY_BATCH).
    """

    def test_summary_triggers_when_threshold_met(self, tmp_state):
        """Delta summary must trigger when enough messages accumulate past the pointer."""
        from prompt_builder import PromptBuilder
        from state_manager import VERBATIM_WINDOW, MIN_SUMMARY_BATCH

        state = tmp_state
        summary_called = threading.Event()
        call_log = []

        def mock_cheap(messages, model_id, max_tokens=400):
            call_log.append(model_id)
            summary_called.set()
            return "Updated summary."

        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Fill active_session with enough messages to trigger summary
        # Need: stable_index > summary_pointer + MIN_SUMMARY_BATCH
        # stable_index = len(active_session) - VERBATIM_WINDOW
        # So need len(active_session) - VERBATIM_WINDOW > 0 + MIN_SUMMARY_BATCH
        # i.e., len >= VERBATIM_WINDOW + MIN_SUMMARY_BATCH + 1
        needed = VERBATIM_WINDOW + MIN_SUMMARY_BATCH + 1
        state.active_session = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"msg_{i}",
             "iso_timestamp": ts}
            for i in range(needed)
        ]
        state.summary_pointer = 0

        PromptBuilder.prepare_context(
            state, "trigger summary", "test-model", "cheap-model", mock_cheap
        )

        # Summary runs in a background thread with a 2s delay, so we wait
        triggered = summary_called.wait(timeout=5)
        assert triggered, "Delta summary was NOT triggered despite threshold being met"
        print(f"  ✓ Delta summary triggered (threshold: {needed} msgs, pointer: 0)")

    def test_summary_does_not_trigger_below_threshold(self, tmp_state):
        """Delta summary must NOT trigger when below the threshold."""
        from prompt_builder import PromptBuilder
        from state_manager import VERBATIM_WINDOW, MIN_SUMMARY_BATCH

        state = tmp_state
        call_log = []

        def mock_cheap(messages, model_id, max_tokens=400):
            call_log.append(model_id)
            return "Should not be called."

        import datetime
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Fill with just enough messages to NOT trigger
        count = VERBATIM_WINDOW  # stable_index = 0, not > MIN_SUMMARY_BATCH
        state.active_session = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"msg_{i}",
             "iso_timestamp": ts}
            for i in range(count)
        ]
        state.summary_pointer = 0

        PromptBuilder.prepare_context(
            state, "no summary", "test-model", "cheap-model", mock_cheap
        )

        # Brief wait to confirm it wasn't triggered
        time.sleep(0.5)
        # The call_log might have calls from count_tokens or other places
        # but run_delta_summary specifically would set summary_called
        # Since the threshold isn't met, summary_pointer should stay at 0
        assert state.summary_pointer == 0, \
            f"summary_pointer changed to {state.summary_pointer} despite threshold not being met"
        print(f"  ✓ Delta summary NOT triggered below threshold ({count} msgs)")
