"""
test_02_db_thread_lifecycle.py — DBManager + thread CRUD + freeze/thaw
══════════════════════════════════════════════════════════════════════

Risk area #4 from test brief: persistence across model/thread swaps.
Freeze a thread, thaw it back — confirm rolling_summary, summary_pointer,
and scratchpad all round-trip exactly.

Tests are integration-style: they exercise real SQLite through DBManager
but in isolated temp directories.
"""

import os
import sys
import time
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call


# ─────────────────────────────────────────────────────────────────────────────
# Unit: DBManager CRUD basics
# ─────────────────────────────────────────────────────────────────────────────

class TestDBManagerCRUD:
    """Baseline correctness for thread and message operations."""

    def test_default_thread_exists(self, tmp_db):
        """DBManager boot must create the default thread (id=1)."""
        r = timed_call(tmp_db.get_threads)
        threads = r.value
        assert any(t[0] == 1 for t in threads), \
            f"Default thread (id=1) not found. Got: {threads}"
        print(f"  ✓ Default thread exists  ({r.elapsed_ms:.2f}ms)")

    def test_create_thread_returns_id(self, tmp_db):
        """create_thread must return a positive integer ID."""
        r = timed_call(tmp_db.create_thread, "Test Thread Alpha")
        assert isinstance(r.value, int) and r.value > 0, \
            f"create_thread returned {r.value!r}"
        print(f"  ✓ Created thread id={r.value}  ({r.elapsed_ms:.2f}ms)")

    def test_rename_thread(self, tmp_db):
        """rename_thread must succeed and persist the new name."""
        tid = tmp_db.create_thread("Original Name")
        r = timed_call(tmp_db.rename_thread, tid, "Renamed Thread")
        assert r.value is True
        threads = tmp_db.get_threads()
        names = {t[0]: t[1] for t in threads}
        assert names[tid] == "Renamed Thread", \
            f"Thread {tid} name is {names.get(tid)!r}, expected 'Renamed Thread'"
        print(f"  ✓ Renamed thread {tid}  ({r.elapsed_ms:.2f}ms)")

    def test_delete_thread_removes_history(self, tmp_db):
        """Deleting a thread must also remove its chat_history rows."""
        tid = tmp_db.create_thread("Doomed Thread")
        iso = "2026-01-01T00:00:00+00:00"
        tmp_db.save_chat_rows(tid, "hello", "world", None, iso)
        
        # Can't delete active thread
        tmp_db.current_thread_id = 1
        r = timed_call(tmp_db.delete_thread, tid)
        assert r.value is True

        # Verify history is gone
        history = tmp_db.load_history(limit=50, thread_id=tid)
        assert len(history) == 0, f"History still has {len(history)} rows after delete"
        print(f"  ✓ Deleted thread {tid} + history  ({r.elapsed_ms:.2f}ms)")

    def test_cannot_delete_active_thread(self, tmp_db):
        """Deleting the currently active thread must fail gracefully."""
        tmp_db.current_thread_id = 1
        r = timed_call(tmp_db.delete_thread, 1)
        assert r.value is False
        print(f"  ✓ Cannot delete active thread  ({r.elapsed_ms:.2f}ms)")

    def test_save_and_load_history(self, tmp_db):
        """save_chat_rows must persist user + assistant rows retrievable by load_history."""
        tid = tmp_db.create_thread("History Thread")
        iso = "2026-06-15T12:00:00+00:00"
        tmp_db.save_chat_rows(tid, "user message", "assistant reply", None, iso)

        r = timed_call(tmp_db.load_history, limit=50, thread_id=tid)
        history = r.value
        assert len(history) == 2, f"Expected 2 rows, got {len(history)}"
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "user message"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "assistant reply"
        print(f"  ✓ Save+load history round-trip  ({r.elapsed_ms:.2f}ms)")

    def test_internal_note_excluded_from_history(self, tmp_db):
        """system_note rows must NOT appear in load_history output."""
        tid = tmp_db.create_thread("Notes Thread")
        iso = "2026-06-15T12:00:00+00:00"
        tmp_db.save_chat_rows(tid, "hi", "hello", "secret scratchpad", iso)

        history = tmp_db.load_history(limit=50, thread_id=tid)
        roles = [h["role"] for h in history]
        assert "system_note" not in roles, \
            f"system_note leaked into history: {roles}"
        print(f"  ✓ system_note excluded from load_history")

    def test_message_count(self, tmp_db):
        """get_thread_message_count must return correct count excluding system_notes."""
        tid = tmp_db.create_thread("Count Thread")
        iso = "2026-06-15T12:00:00+00:00"
        assert tmp_db.get_thread_message_count(tid) == 0

        tmp_db.save_chat_rows(tid, "a", "b", "internal", iso)
        assert tmp_db.get_thread_message_count(tid) == 2  # user + assistant, not system_note

        tmp_db.save_chat_rows(tid, "c", "d", None, iso)
        assert tmp_db.get_thread_message_count(tid) == 4
        print(f"  ✓ Message count correct")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Freeze/Thaw round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestFreezeThaw:
    """
    Test brief §4: 'Freeze a thread (switch away), thaw it back — confirm
    rolling_summary, summary_pointer, and scratchpad all round-trip exactly.'
    """

    def test_freeze_thaw_roundtrip(self, tmp_db):
        """Summary and scratchpad must survive a freeze→thaw cycle exactly."""
        tid = tmp_db.create_thread("Freeze Test Thread")
        summary = "User is building an AI system. Discussed memory retrieval."
        scratchpad = "User prefers terse responses. Mood: focused."

        r_freeze = timed_call(tmp_db.freeze_thread, tid, summary, scratchpad)
        r_thaw = timed_call(tmp_db.thaw_thread, tid)

        thawed_summary, thawed_scratchpad = r_thaw.value
        assert thawed_summary == summary, \
            f"Summary mismatch:\n  expected: {summary!r}\n  got:      {thawed_summary!r}"
        assert thawed_scratchpad == scratchpad, \
            f"Scratchpad mismatch:\n  expected: {scratchpad!r}\n  got:      {thawed_scratchpad!r}"
        print(f"  ✓ Freeze/thaw round-trip  (freeze={r_freeze.elapsed_ms:.2f}ms, thaw={r_thaw.elapsed_ms:.2f}ms)")

    def test_thaw_nonexistent_thread_returns_defaults(self, tmp_db):
        """Thawing a thread that doesn't exist must return safe defaults, not crash."""
        r = timed_call(tmp_db.thaw_thread, 99999)
        summary, scratchpad = r.value
        assert summary == "Session just started."
        assert scratchpad == "No current internal notes."
        print(f"  ✓ Thaw nonexistent thread returns defaults  ({r.elapsed_ms:.2f}ms)")

    def test_freeze_overwrites_previous(self, tmp_db):
        """Freezing the same thread twice must overwrite, not append."""
        tid = tmp_db.create_thread("Overwrite Thread")

        tmp_db.freeze_thread(tid, "Summary v1", "Scratchpad v1")
        tmp_db.freeze_thread(tid, "Summary v2", "Scratchpad v2")

        summary, scratchpad = tmp_db.thaw_thread(tid)
        assert summary == "Summary v2"
        assert scratchpad == "Scratchpad v2"
        print(f"  ✓ Freeze overwrites previous state")

    def test_freeze_empty_strings(self, tmp_db):
        """Freezing with empty strings must thaw back as defaults (falsy → defaults)."""
        tid = tmp_db.create_thread("Empty Freeze Thread")
        tmp_db.freeze_thread(tid, "", "")

        summary, scratchpad = tmp_db.thaw_thread(tid)
        # DBManager.thaw_thread returns defaults for falsy values
        assert summary == "Session just started."
        assert scratchpad == "No current internal notes."
        print(f"  ✓ Empty freeze → default thaw")

    def test_freeze_preserves_unicode_and_special_chars(self, tmp_db):
        """Summary/scratchpad with unicode, newlines, and XML-like tags must round-trip."""
        tid = tmp_db.create_thread("Unicode Thread")
        summary = "用户正在讨论AI。\n<scratchpad>内部笔记</scratchpad>\nEmoji: 🧠💾"
        scratchpad = "Σ(data) = ∞\n\t<tag>nested</tag>"

        tmp_db.freeze_thread(tid, summary, scratchpad)
        thawed_summary, thawed_scratchpad = tmp_db.thaw_thread(tid)

        assert thawed_summary == summary
        assert thawed_scratchpad == scratchpad
        print(f"  ✓ Unicode/special chars survive freeze/thaw")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: StateManager switch_thread full flow
# ─────────────────────────────────────────────────────────────────────────────

class TestStateManagerSwitchThread:
    """
    End-to-end switch_thread: verifies that StateManager correctly freezes
    the old thread's state to SQLite and thaws the new thread's state back.
    """

    def test_switch_thread_preserves_state(self, tmp_state):
        """After switch_thread: rolling_summary, scratchpad, and active_session must all update."""
        state = tmp_state

        # Create two threads
        tid_a = state.db.create_thread("Thread A")
        tid_b = state.db.create_thread("Thread B")

        # Set up state for thread A
        state.db.current_thread_id = tid_a
        state.rolling_summary = "Summary for A — user asked about RAG."
        state.db.scratchpad = "A's scratchpad: user is tired."
        state.active_session = [{"role": "user", "content": "hello A"}]

        # Freeze thread A's state and seed thread B with known state
        state.db.freeze_thread(tid_a, state.rolling_summary, state.db.scratchpad)
        state.db.freeze_thread(tid_b, "Summary for B", "B's scratchpad")

        # Switch to B
        r = timed_call(state.switch_thread, tid_b)
        assert state.current_thread_id == tid_b
        assert state.rolling_summary == "Summary for B"
        assert state.scratchpad == "B's scratchpad"
        print(f"  ✓ Switched to thread B, state loaded correctly  ({r.elapsed_ms:.2f}ms)")

        # Switch back to A
        r2 = timed_call(state.switch_thread, tid_a)
        assert state.current_thread_id == tid_a
        assert state.rolling_summary == "Summary for A — user asked about RAG."
        assert state.scratchpad == "A's scratchpad: user is tired."
        print(f"  ✓ Switched back to thread A, state restored  ({r2.elapsed_ms:.2f}ms)")

    def test_switch_to_same_thread_is_noop(self, tmp_state):
        """Switching to the already-active thread must be a no-op (no crash, no state change)."""
        state = tmp_state
        original_summary = state.rolling_summary

        r = timed_call(state.switch_thread, state.current_thread_id)
        assert state.rolling_summary == original_summary
        print(f"  ✓ Same-thread switch is no-op  ({r.elapsed_ms:.2f}ms)")

    def test_rapid_switch_no_state_bleed(self, tmp_state):
        """
        Test brief §1: 'rapid switch-switch-switch for state bleed between threads.'
        Switch A→B→C→A rapidly and verify each thread's state is isolated.
        """
        state = tmp_state

        tids = []
        for name in ["Thread X", "Thread Y", "Thread Z"]:
            tid = state.db.create_thread(name)
            tids.append(tid)
            state.db.freeze_thread(tid, f"Summary for {name}", f"Scratchpad for {name}")

        # Rapid cycling
        t0 = time.perf_counter()
        for _ in range(5):  # 5 full cycles
            for tid in tids:
                state.switch_thread(tid)
        elapsed = (time.perf_counter() - t0) * 1000

        # Verify final state matches last thread switched to
        last_tid = tids[-1]
        assert state.current_thread_id == last_tid
        assert "Thread Z" in state.rolling_summary
        assert "Thread Z" in state.scratchpad
        print(f"  ✓ 15 rapid switches, no state bleed  ({elapsed:.2f}ms total)")


# ─────────────────────────────────────────────────────────────────────────────
# Unit: Persona loading
# ─────────────────────────────────────────────────────────────────────────────

class TestPersonaLoading:
    """Verify persona JSON loading and fallback behavior."""

    def test_load_default_persona(self, tmp_db):
        """Loading 'default' persona must populate current_persona with valid data."""
        r = timed_call(tmp_db.load_persona, "default")
        assert r.value is True
        assert "role_definition" in tmp_db.current_persona
        assert "style_guidelines" in tmp_db.current_persona
        print(f"  ✓ Default persona loaded  ({r.elapsed_ms:.2f}ms)")

    def test_load_nonexistent_persona_fallback(self, tmp_db):
        """Loading a missing persona must return False and set a hardcoded fallback."""
        r = timed_call(tmp_db.load_persona, "nonexistent_persona_xyz")
        assert r.value is False
        assert "role_definition" in tmp_db.current_persona, \
            "Fallback persona missing role_definition"
        print(f"  ✓ Missing persona → fallback  ({r.elapsed_ms:.2f}ms)")
