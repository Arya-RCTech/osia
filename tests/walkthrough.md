# OSIA Test Suite — Walkthrough

## What was created

A comprehensive test suite covering all 6 risk areas from the [test brief](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/1_test_brief.md), prioritized by crash-severity.

## Files created

| File | Purpose | Test count |
|:--|:--|:--|
| [`conftest.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/conftest.py) | Shared fixtures: isolated DBManager (temp SQLite), isolated MemoryEngine (temp ChromaDB), isolated StateManager, `timed_call()` helper | — |
| [`test_01_config_contract.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_01_config_contract.py) | Config-as-contract + ThinkingManager guard | 15 |
| [`test_02_db_thread_lifecycle.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_02_db_thread_lifecycle.py) | DB CRUD, freeze/thaw, switch_thread state isolation | 18 |
| [`test_03_tag_parsing.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_03_tag_parsing.py) | Tag parsing parity (server + client regex round-trip) | 20 |
| [`test_04_concurrency_locking.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_04_concurrency_locking.py) | Concurrency, lock contention, session trimming | 11 |
| [`test_05_memory_rag.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_05_memory_rag.py) | ONNX concurrency, MMR reranking, delta summary | 18 |
| [`test_06_stream_processor.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_06_stream_processor.py) | StreamProcessor with mocked transports | 10 |
| [`test_07_prompt_builder.py`](file:///home/arya/Documents/Project_OSIA/osia%20v0/tests/test_07_prompt_builder.py) | PromptBuilder context assembly + summary trigger | 10 |
| [`pytest.ini`](file:///home/arya/Documents/Project_OSIA/osia%20v0/pytest.ini) | Pytest config | — |

**Total: 102 tests (100% passing)**

---

## Test brief risk areas → coverage mapping

| Risk area | Brief section | Primary test file | Key tests |
|:--|:--|:--|:--|
| **Concurrency & locking** | §1 | `test_04` | Concurrent save_interaction under `_engine_lock`, `prepare_context` vs `save_interaction` lock contention, rapid thread switching |
| **Tag parsing parity** | §2 | `test_03` | Server/client regex round-trip, tag split across chunks, all hidden tag types |
| **Memory/ONNX concurrency** | §3 | `test_05` | 5-thread concurrent `_embed_batch`, concurrent `save_to_vector_db`, MMR timing assertion |
| **Thread freeze/thaw** | §4 | `test_02` + `test_04` | Freeze/thaw round-trip, unicode, rapid switch-switch-switch, HARD_LIMIT trimming |
| **Multi-provider transport** | §5 | `test_06` | Mocked transport streaming, error handling (real LLM tests left for manual runs) |
| **Config-as-contract** | §6 | `test_01` | Cross-consumer consistency, ThinkingManager guard for all providers |

---

## Timing and return values

All tests use the `timed_call()` helper from conftest which wraps any function call in a `TimedResult(value, elapsed_ms)`. Tests print timing in their output (e.g., `✓ Freeze/thaw round-trip (freeze=0.34ms, thaw=0.12ms)`).

---

## How to run

```bash
# From the osia v0/ directory, with the venv activated:
source /home/arya/Documents/Project_OSIA/venv/bin/activate

# Run all tests:
pytest

# Run a specific test file:
pytest tests/test_01_config_contract.py

# Run a specific test class:
pytest tests/test_03_tag_parsing.py::TestClientServerTagParity

# Run with extra verbose output:
pytest -v -s
```
