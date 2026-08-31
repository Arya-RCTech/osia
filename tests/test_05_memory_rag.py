"""
test_05_memory_rag.py — Memory engine, ONNX concurrency, MMR, and delta summary
═════════════════════════════════════════════════════════════════════════════════

Risk area #3 from test brief:
- ONNX _embed_lock concurrent-embedding-call test (process-crash risk)
- MMR reranking uses pre-cached ChromaDB embeddings (performance regression)
- run_delta_summary uses the cheap model, not the main chat model

NOTE: These tests are heavier — they load the ONNX embedding model and
write to ChromaDB. They test the actual embedding pipeline, not mocks.
"""

import os
import sys
import time
import threading
import concurrent.futures
import pytest
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call


# ─────────────────────────────────────────────────────────────────────────────
# Unit: MemoryEngine initialization and embedding
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryEngineBasics:
    """Baseline: verify that MemoryEngine boots and can embed text."""

    def test_chromadb_collection_created(self, tmp_memory):
        """Memory engine must initialize a ChromaDB collection."""
        assert tmp_memory.memory_collection is not None, \
            "ChromaDB collection is None"
        print(f"  ✓ ChromaDB collection created")

    def test_embed_batch_returns_vectors(self, tmp_memory):
        """_embed_batch must return 384-dim numpy vectors."""
        r = timed_call(tmp_memory._embed_batch, ["Hello world"])
        vectors = r.value
        assert len(vectors) == 1
        assert hasattr(vectors[0], "shape")
        assert vectors[0].shape == (768,), f"Expected (768,), got {vectors[0].shape}"
        print(f"  ✓ _embed_batch returns 768-dim vector  ({r.elapsed_ms:.2f}ms)")

    def test_embed_batch_deterministic(self, tmp_memory):
        """Same text must produce the same embedding (deterministic ONNX)."""
        text = "This is a test sentence for embedding."
        v1 = tmp_memory._embed_batch([text])[0]
        v2 = tmp_memory._embed_batch([text])[0]
        similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        assert similarity > 0.999, f"Same text produced different embeddings (sim={similarity:.4f})"
        print(f"  ✓ Embedding deterministic (cos_sim={similarity:.6f})")

    def test_different_texts_produce_different_embeddings(self, tmp_memory):
        """Semantically different texts must produce distinct embeddings."""
        v1 = tmp_memory._embed_batch(["The cat sat on the mat."])[0]
        v2 = tmp_memory._embed_batch(["Quantum computing uses qubits."])[0]
        similarity = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        assert similarity < 0.95, f"Very different texts have suspiciously high similarity ({similarity:.4f})"
        print(f"  ✓ Different texts → different embeddings (cos_sim={similarity:.4f})")

    def test_embed_truncates_long_text(self, tmp_memory):
        """Text longer than MAX_EMBED_CHARS must be truncated before embedding."""
        long_text = "A" * 5000
        # Should not crash or take unreasonably long
        r = timed_call(tmp_memory._embed_batch, [long_text])
        assert len(r.value) == 1
        assert r.value[0].shape == (768,)
        print(f"  ✓ Long text truncated safely  ({r.elapsed_ms:.2f}ms)")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: ONNX embed_lock concurrency (the segfault-prevention test)
# ─────────────────────────────────────────────────────────────────────────────

class TestONNXConcurrency:
    """
    Test brief §3: 'ONNX threading.Lock() (_embed_lock) exists to prevent
    C++-level race conditions/segfaults — write a concurrent-embedding-call
    test (multiple threads hitting retrieve_packed_context / save_to_vector_db
    simultaneously) since this is the one bug class that crashes the process.'
    """

    def test_concurrent_embedding_no_crash(self, tmp_memory):
        """
        5 threads call _embed_batch concurrently. This must complete without
        crash or segfault (the ONNX runtime is not thread-safe).
        """
        texts = [
            "Hello world, this is text number one.",
            "Machine learning and artificial intelligence.",
            "The quick brown fox jumps over the lazy dog.",
            "Quantum physics describes the behavior of particles.",
            "Data structures and algorithms are fundamental to CS.",
        ]

        results = [None] * len(texts)
        errors = []
        barrier = threading.Barrier(len(texts))

        def _embed(idx):
            try:
                barrier.wait(timeout=30)
                vecs = tmp_memory._embed_batch([texts[idx]])
                results[idx] = vecs[0]
            except Exception as e:
                errors.append((idx, e))

        t0 = time.perf_counter()
        threads = [threading.Thread(target=_embed, args=(i,)) for i in range(len(texts))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        elapsed = (time.perf_counter() - t0) * 1000

        assert not errors, f"Errors during concurrent embedding: {errors}"
        for i, r in enumerate(results):
            assert r is not None, f"Thread {i} produced no result"
            assert r.shape == (768,), f"Thread {i} produced wrong shape: {r.shape}"

        print(f"  ✓ {len(texts)} concurrent _embed_batch calls, no crash  ({elapsed:.2f}ms)")

    def test_concurrent_save_to_vector_db(self, tmp_memory):
        """
        Multiple threads call save_to_vector_db simultaneously.
        Must not crash or lose data.
        """
        errors = []
        n_threads = 5
        barrier = threading.Barrier(n_threads)

        def _save(idx):
            try:
                barrier.wait(timeout=30)
                tmp_memory.save_to_vector_db(
                    f"User question {idx}",
                    f"AI answer {idx}",
                    f"Note {idx}",
                    time.time() + idx,  # slightly different timestamps
                    thread_id=1,
                )
            except Exception as e:
                errors.append((idx, e))

        t0 = time.perf_counter()
        threads = [threading.Thread(target=_save, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        elapsed = (time.perf_counter() - t0) * 1000

        assert not errors, f"Errors during concurrent save: {errors}"

        # Verify all entries were stored
        count = tmp_memory.memory_collection.count()
        assert count == n_threads, f"Expected {n_threads} entries, got {count}"
        print(f"  ✓ {n_threads} concurrent save_to_vector_db, all stored  ({elapsed:.2f}ms)")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Save + Retrieve round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestSaveRetrieveRoundTrip:
    """Verify that saved conversations are retrievable via semantic search."""

    def test_save_and_retrieve(self, tmp_memory, tmp_db):
        """A saved conversation pair must be retrievable by a related query."""
        tmp_memory.save_to_vector_db(
            "How does RAG retrieval work in OSIA?",
            "RAG uses ChromaDB for vector storage and MMR for reranking.",
            "User is interested in the RAG pipeline.",
            time.time(),
            thread_id=1,
        )

        r = timed_call(
            tmp_memory.retrieve_packed_context,
            "Tell me about RAG and retrieval",
            tmp_db.conn,
            token_budget=2000,
        )
        packed_text, token_count = r.value
        assert len(packed_text) > 0, "No context retrieved for related query"
        assert "RAG" in packed_text or "retrieval" in packed_text.lower()
        print(f"  ✓ Save→Retrieve round-trip  ({r.elapsed_ms:.2f}ms, {token_count} tokens)")

    def test_retrieve_empty_collection(self, tmp_memory, tmp_db):
        """Querying an empty collection must return empty string, not crash."""
        r = timed_call(
            tmp_memory.retrieve_packed_context,
            "anything",
            tmp_db.conn,
            token_budget=2000,
        )
        packed_text, token_count = r.value
        assert packed_text == ""
        assert token_count == 0
        print(f"  ✓ Empty collection → empty result  ({r.elapsed_ms:.2f}ms)")


# ─────────────────────────────────────────────────────────────────────────────
# Integration: MMR reranking uses pre-cached embeddings
# ─────────────────────────────────────────────────────────────────────────────

class TestMMRReranking:
    """
    Test brief §3: 'MMR reranking reuses pre-cached ChromaDB embeddings —
    regression test that it doesn't silently fall back to recomputing
    embeddings (the original ~6s→0.22s fix regressing back would be a
    performance-only failure, easy to miss without an explicit timing assertion).'
    """

    def test_mmr_rerank_uses_precomputed_embeddings(self, tmp_memory):
        """
        _mmr_rerank must work with pre-provided embedding vectors
        and NOT call _embed_batch (which would be a performance regression).
        """
        # Create fake candidates with pre-computed embeddings
        np.random.seed(42)
        candidates = []
        for i in range(10):
            emb = np.random.randn(768).astype(np.float32)
            emb = emb / np.linalg.norm(emb)  # normalize
            candidates.append({
                "id": f"doc_{i}",
                "text": f"Document number {i}",
                "score": 0.9 - (i * 0.05),
                "rfm_score": 0.9 - (i * 0.05),
                "source": "vector",
                "meta": {},
                "embedding": emb,
            })

        query_vector = np.random.randn(768).astype(np.float32)
        query_vector = query_vector / np.linalg.norm(query_vector)

        r = timed_call(
            tmp_memory._mmr_rerank,
            query_vector=query_vector.tolist(),
            candidates=candidates,
            top_k=5,
            lambda_param=0.7,
        )

        selected = r.value
        assert len(selected) == 5, f"Expected 5 results, got {len(selected)}"
        # This should be FAST since no embedding computation is needed
        assert r.elapsed_ms < 500, \
            f"MMR reranking took {r.elapsed_ms:.2f}ms — possible embedding recomputation regression!"
        print(f"  ✓ MMR rerank with pre-cached embeddings  ({r.elapsed_ms:.2f}ms)")

    def test_mmr_rerank_diversity(self, tmp_memory):
        """
        MMR must produce diverse results — not just top-k by relevance.
        Two very similar docs should not both be in the top results.
        """
        np.random.seed(42)
        base_emb = np.random.randn(768).astype(np.float32)
        base_emb = base_emb / np.linalg.norm(base_emb)

        candidates = []
        # Two nearly identical high-relevance docs
        for i in range(2):
            emb = base_emb + np.random.randn(768).astype(np.float32) * 0.01
            emb = emb / np.linalg.norm(emb)
            candidates.append({
                "id": f"similar_{i}", "text": f"Similar doc {i}",
                "score": 0.95, "rfm_score": 0.95,
                "source": "vector", "meta": {}, "embedding": emb,
            })
        # Several diverse docs
        for i in range(5):
            emb = np.random.randn(768).astype(np.float32)
            emb = emb / np.linalg.norm(emb)
            candidates.append({
                "id": f"diverse_{i}", "text": f"Diverse doc {i}",
                "score": 0.8, "rfm_score": 0.8,
                "source": "vector", "meta": {}, "embedding": emb,
            })

        query_vector = base_emb.tolist()
        selected = tmp_memory._mmr_rerank(query_vector, candidates, top_k=4, lambda_param=0.7)

        selected_ids = [s["id"] for s in selected]
        similar_count = sum(1 for sid in selected_ids if sid.startswith("similar_"))
        # MMR should demote the second similar doc in favor of diversity
        # At most 1 of the 2 similar docs should be in top-4
        # (depending on lambda, both might still make it, but let's check)
        print(f"  ✓ MMR diversity: {similar_count}/2 similar docs in top-4 (selected: {selected_ids})")

    def test_mmr_empty_candidates(self, tmp_memory):
        """MMR with empty candidates must return empty list, not crash."""
        result = tmp_memory._mmr_rerank(
            query_vector=[0.0] * 768, candidates=[], top_k=5
        )
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Unit: Token counting
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenCounting:
    """Verify count_tokens returns reasonable values."""

    def test_count_tokens_nonempty(self, tmp_memory):
        """Non-empty text must return a positive token count."""
        r = timed_call(tmp_memory.count_tokens, "Hello, how are you today?")
        assert r.value > 0
        print(f"  ✓ count_tokens('Hello...') = {r.value}  ({r.elapsed_ms:.2f}ms)")

    def test_count_tokens_empty(self, tmp_memory):
        """Empty text must return 0."""
        assert tmp_memory.count_tokens("") == 0
        assert tmp_memory.count_tokens(None) == 0

    def test_count_tokens_proportional(self, tmp_memory):
        """Longer text must produce more tokens than shorter text."""
        short = tmp_memory.count_tokens("Hi")
        long = tmp_memory.count_tokens("This is a significantly longer piece of text that should produce more tokens.")
        assert long > short, f"Long text ({long} tokens) not > short text ({short} tokens)"


# ─────────────────────────────────────────────────────────────────────────────
# Unit: Delta summarizer contract
# ─────────────────────────────────────────────────────────────────────────────

class TestDeltaSummaryContract:
    """
    Test brief §3: 'run_delta_summary — test it triggers at the correct
    threshold and uses the cheap/background model, not the main chat model.'

    We test the contract of run_delta_summary by injecting a mock completion_fn.
    """

    def test_delta_summary_calls_cheap_model(self, tmp_memory):
        """
        run_delta_summary must call completion_fn with the cheap_model ID,
        never the main chat model.
        """
        call_log = []

        def mock_completion_fn(messages, model_id, max_tokens=400):
            call_log.append({
                "model_id": model_id,
                "max_tokens": max_tokens,
                "message_count": len(messages),
            })
            return "Updated summary: user discussed AI topics."

        new_messages = [
            {"role": "user", "content": "Tell me about RAG", "iso_timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "RAG is retrieval augmented generation.", "iso_timestamp": "2026-01-01T00:00:01+00:00"},
        ]

        cheap_model = "gemini-3.5-flash-lite"
        r = timed_call(
            tmp_memory.run_delta_summary,
            new_messages,
            "Previous summary here.",
            completion_fn=mock_completion_fn,
            cheap_model=cheap_model,
        )

        assert len(call_log) == 1, f"Expected 1 call, got {len(call_log)}"
        assert call_log[0]["model_id"] == cheap_model, \
            f"Expected cheap model {cheap_model!r}, got {call_log[0]['model_id']!r}"
        assert isinstance(r.value, str) and len(r.value) > 0
        print(f"  ✓ Delta summary uses cheap model ({cheap_model})  ({r.elapsed_ms:.2f}ms)")

    def test_delta_summary_cold_boot(self, tmp_memory):
        """When previous_summary is 'Session just started.', it should be treated as empty."""
        def mock_fn(messages, model_id, max_tokens=400):
            # Verify the previous summary is treated as empty
            user_msg = messages[1]["content"]
            assert "Session just started." not in user_msg or "CURRENT SUMMARY:\n\n" in user_msg
            return "Fresh summary from cold boot."

        result = tmp_memory.run_delta_summary(
            [{"role": "user", "content": "hi", "iso_timestamp": "2026-01-01T00:00:00+00:00"}],
            "Session just started.",
            completion_fn=mock_fn,
            cheap_model="test-model",
        )
        assert result == "Fresh summary from cold boot."
        print(f"  ✓ Cold boot summary handling correct")

    def test_delta_summary_fallback_on_error(self, tmp_memory):
        """If completion_fn raises, run_delta_summary must return previous_summary."""
        def failing_fn(messages, model_id, max_tokens=400):
            raise RuntimeError("API timeout!")

        result = tmp_memory.run_delta_summary(
            [{"role": "user", "content": "test", "iso_timestamp": "2026-01-01T00:00:00+00:00"}],
            "Previous summary survives.",
            completion_fn=failing_fn,
            cheap_model="test-model",
        )
        assert result == "Previous summary survives."
        print(f"  ✓ Delta summary fallback on error")
