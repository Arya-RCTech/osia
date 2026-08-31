"""
conftest.py — Shared fixtures for OSIA test suite.

Provides isolated in-memory / temp-dir instances of DBManager, MemoryEngine,
StateManager, and ModelRegistry so tests never touch production databases.
"""

import os
import sys
import json
import time
import tempfile
import shutil
import pytest

# --- Ensure the project root is importable ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Fixture: Isolated DBManager (in-memory SQLite)
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_db(tmp_path):
    """Returns a DBManager backed by a temporary SQLite file + temp persona dir."""
    from db_manager import DBManager

    db_path = str(tmp_path / "test_chat.db")
    personas_dir = str(tmp_path / "personas")
    os.makedirs(personas_dir, exist_ok=True)

    # Write a minimal default persona
    with open(os.path.join(personas_dir, "default.json"), "w") as f:
        json.dump({
            "name": "TestPersona",
            "role_definition": "You are a test assistant.",
            "style_guidelines": ["Be concise."],
        }, f)

    db = DBManager(sql_db_path=db_path, personas_dir=personas_dir)
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Fixture: Isolated MemoryEngine (temp ChromaDB directory)
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_memory(tmp_path):
    """Returns a MemoryEngine backed by a temp ChromaDB directory."""
    from memory_engine import MemoryEngine

    db_dir = str(tmp_path / "test_vector_db")
    mem = MemoryEngine(db_path=db_dir, collection_name="test_collection")
    yield mem


# ---------------------------------------------------------------------------
# Fixture: Isolated StateManager (wires tmp_db + tmp_memory together)
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_state(tmp_db, tmp_memory):
    """
    Returns a StateManager whose .db and .memory point at temp locations.
    Avoids the normal constructor so we don't touch real DBs.
    """
    from state_manager import StateManager
    import threading

    state = object.__new__(StateManager)
    state._engine_lock = threading.Lock()
    state.db = tmp_db
    state.memory = tmp_memory
    
    # Mock save_to_vector_db on tmp_state so background daemon threads
    # don't trigger HuggingFace downloads during unit/concurrency tests
    state.memory.save_to_vector_db = lambda user, ai, note, ts, tid: None

    state.active_session = tmp_db.load_history(limit=50)
    state.rolling_summary = "Session just started."
    state.summary_pointer = 0
    yield state


# ---------------------------------------------------------------------------
# Fixture: Fresh ModelRegistry pointing at real models.json
# ---------------------------------------------------------------------------
@pytest.fixture
def registry():
    """Returns the project's live ModelRegistry singleton (read-only usage)."""
    from model_registry import registry as reg
    reg.reload()  # ensure fresh state
    return reg


# ---------------------------------------------------------------------------
# Helpers available to all test modules
# ---------------------------------------------------------------------------
class TimedResult:
    """Container for a function's return value + wall-clock elapsed time."""
    __slots__ = ("value", "elapsed_ms")

    def __init__(self, value, elapsed_ms):
        self.value = value
        self.elapsed_ms = elapsed_ms

    def __repr__(self):
        return f"TimedResult(value={self.value!r}, elapsed_ms={self.elapsed_ms:.2f})"


def timed_call(fn, *args, **kwargs):
    """Execute fn(*args, **kwargs) and return TimedResult(value, elapsed_ms)."""
    t0 = time.perf_counter()
    value = fn(*args, **kwargs)
    elapsed = (time.perf_counter() - t0) * 1000
    return TimedResult(value, elapsed)
