# memory_engine.py — ChromaDB vector search, MMR reranking, Delta-Summarizer
# Part of Osia Build 2.0 (Phase 1.8 refactor)
#
# This module owns ALL vector/embedding operations:
#   - ChromaDB persistent client + collection
#   - fastembed local embeddings (ONNX CPU)
#   - Tiktoken token counting
#   - Semantic retrieval + keyword fallback + dedup + MMR reranking + budget packing
#   - Delta rolling summarizer (calls Groq background model)

import os
import numpy as np
import chromadb
import tiktoken
from fastembed import TextEmbedding
from numpy.linalg import norm
import threading
import concurrent.futures

# --- CONFIGURATION ---
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "my_local_memory_db")
COLLECTION_NAME = "user_context_memory"
RAG_CONTEXT_BUDGET = 2000


class MemoryEngine:
    """Vector memory store with retrieval pipeline and rolling summarizer."""

    def __init__(self, db_path=None, collection_name=None):
        db_path = db_path or DB_PATH
        collection_name = collection_name or COLLECTION_NAME
        self._embed_lock = threading.Lock()
        self._embed_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # 1. ChromaDB
        try:
            self.chroma_client = chromadb.PersistentClient(path=db_path)
            self.memory_collection = self.chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            print(f"❌ Failed to init ChromaDB: {e}")
            self.memory_collection = None

        # 2. Local Embeddings
        self.embed_model = None

        # 3. Tokenizer
        self._hf_tokenizer_loaded = False
        self.hf_tokenizer = None
        self.tiktoken_tokenizer = None

    def preload(self):
        """Asynchronously load heavy models to prevent latency spikes on first query."""
        import threading
        
        def _load():
            try:
                if not self._hf_tokenizer_loaded:
                    self._hf_tokenizer_loaded = True
                    print("   -> Preloading HF Tokenizer (gpt2 default)...")
                    import os
                    os.environ["TOKENIZERS_PARALLELISM"] = "false"
                    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
                    os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
                    import transformers
                    transformers.logging.set_verbosity_error()
                    from transformers import AutoTokenizer
                    self.hf_tokenizer = AutoTokenizer.from_pretrained("gpt2", model_max_length=100000)
            except Exception as e:
                print(f"⚠️ Preload HF Tokenizer failed ({e})")
                self.hf_tokenizer = None
                
            try:
                if not self.tiktoken_tokenizer:
                    print("   -> Preloading Tiktoken (cl100k_base)...")
                    import tiktoken
                    self.tiktoken_tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                print(f"⚠️ Preload Tiktoken failed ({e})")
                self.tiktoken_tokenizer = "FAILED"
                
            def _load_embed():
                with self._embed_lock:
                    if not self.embed_model:
                        print("   -> Preloading embedding model...")
                        from fastembed import TextEmbedding
                        self.embed_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5", threads=1)
            self._embed_pool.submit(_load_embed)
            
        threading.Thread(target=_load, daemon=True).start()

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------
    def count_tokens(self, text: str, model_id: str | None = None) -> int:
        """Count tokens using HF tokenizer, fallback to tiktoken if GPT, or char/4."""
        if not text:
            return 0
            
        if model_id and "gpt" in model_id.lower():
            if not self.tiktoken_tokenizer:
                print("   -> Lazy loading Tiktoken (cl100k_base)...")
                try:
                    import tiktoken
                    self.tiktoken_tokenizer = tiktoken.get_encoding("cl100k_base")
                except Exception as e:
                    print(f"⚠️ Tiktoken failed ({e})")
                    self.tiktoken_tokenizer = "FAILED"
            
            if self.tiktoken_tokenizer and self.tiktoken_tokenizer != "FAILED":
                try:
                    return len(self.tiktoken_tokenizer.encode(text))
                except Exception:
                    pass
                    
        # Default HF tokenizer
        if not self._hf_tokenizer_loaded:
            self._hf_tokenizer_loaded = True
            print("   -> Lazy loading HF Tokenizer (gpt2 default)...")
            try:
                import os
                os.environ["TOKENIZERS_PARALLELISM"] = "false"
                os.environ["TRANSFORMERS_VERBOSITY"] = "error"
                os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
                import transformers
                transformers.logging.set_verbosity_error()
                from transformers import AutoTokenizer
                self.hf_tokenizer = AutoTokenizer.from_pretrained("gpt2", model_max_length=100000)
            except Exception as e:
                print(f"⚠️ HF Tokenizer failed ({e}), falling back to rough estimation.")
                self.hf_tokenizer = None
                
        if hasattr(self, 'hf_tokenizer') and self.hf_tokenizer:
            try:
                return len(self.hf_tokenizer.encode(text, truncation=False, verbose=False))
            except Exception:
                pass
                
        return len(text) // 4

    MAX_EMBED_CHARS = 1000  # ~250 tokens. Relevance lives in the head of a doc.
    def _embed_batch(self, texts, batch_size=1, is_query=False):
        prefix = "search_query: " if is_query else "search_document: "
        prefixed = [prefix + t[:self.MAX_EMBED_CHARS] for t in texts]
        
        def _do_embed():
            out = []
            with self._embed_lock:
                if not self.embed_model:
                    print("   -> Lazy loading embedding model...")
                    from fastembed import TextEmbedding
                    self.embed_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5", threads=1)
                for t in prefixed:
                    out.extend(list(self.embed_model.embed([t])))
            return out
            
        # Run exclusively on the dedicated embedding thread to prevent ONNX arena leaks
        future = self._embed_pool.submit(_do_embed)
        return future.result()

    # -------------------------------------------------------------------------
    # SAVE: Write conversation pair to ChromaDB
    # -------------------------------------------------------------------------
    def save_to_vector_db(self, user_msg, ai_msg, internal_note, timestamp, thread_id):
        """Embed and store a conversation pair in the vector collection."""
        if not self.memory_collection:
            return

        combined_text = f"User: {user_msg}\nAI: {ai_msg}"
        if internal_note:
            combined_text += f"\n[Internal Note]: {internal_note}"
            
        import datetime, uuid
        dt = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        date_str = dt.strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:6]
        new_id = f"pair_{date_str}_{short_uuid}"

        embedding = self._embed_batch([combined_text], is_query=False)[0].tolist()
        self.memory_collection.add(
            documents=[combined_text],
            embeddings=[embedding],
            metadatas=[{
                "type": "conversation_pair",
                "epoch_timestamp": timestamp,
                "thread_id": thread_id,
            }],
            ids=[new_id],
        )

    # -------------------------------------------------------------------------
    # RETRIEVE: Full retrieval pipeline
    # -------------------------------------------------------------------------
    def retrieve_packed_context(self, query, db_conn, token_budget=None):
        """
        Run the full retrieval pipeline:
        1. Semantic vector search (ChromaDB)
        2. Keyword fallback (SQLite via db_conn)
        3. Deduplication
        4. MMR reranking
        5. Token-budget packing

        Args:
            query: The user message to search against.
            db_conn: A raw sqlite3.Connection for keyword fallback queries.
            token_budget: Max tokens for the packed result.

        Returns:
            (packed_text: str, token_count: int)
        """
        import time
        t_start = time.time()
        
        if token_budget is None:
            token_budget = RAG_CONTEXT_BUDGET

        if not self.memory_collection:
            return "", 0

        # Step 1: Semantic search
        t0 = time.time()
        query_vector = self._embed_batch([query], is_query=True)[0].tolist()
        print(f"🔍 RAG - Embed query took: {time.time() - t0:.2f}s")
        t1 = time.time()
        try:
            vector_results = self.memory_collection.query(
                query_embeddings=[query_vector],
                n_results=60,
                where={"$or": [
                    {"type": "conversation_pair"},
                    {"type": "internal_monologue"},
                ]},
                include=["documents", "distances", "metadatas", "embeddings"],
            )
        except Exception as e:
            print(f"⚠️ Vector search failed: {e}")
            return "", 0
        print(f"🔍 RAG - ChromaDB search took: {time.time() - t1:.2f}s")

        candidates = []
        raw_docs = vector_results.get("documents")
        if raw_docs and len(raw_docs) > 0:
            docs = raw_docs[0]
            raw_dists = vector_results.get("distances")
            dists = raw_dists[0] if raw_dists and len(raw_dists) > 0 else []

            raw_metas = vector_results.get("metadatas")
            metas = raw_metas[0] if raw_metas and len(raw_metas) > 0 else []

            raw_ids = vector_results.get("ids")
            ids = raw_ids[0] if raw_ids and len(raw_ids) > 0 else []

            raw_embs = vector_results.get("embeddings")
            embs = raw_embs[0] if raw_embs and len(raw_embs) > 0 else []

            for i, doc in enumerate(docs):
                distance = dists[i] if i < len(dists) else 1.0
                score = max(0, 1 - distance)
                meta = metas[i] if i < len(metas) and metas[i] is not None else {}
                doc_id = ids[i] if i < len(ids) else None
                emb = embs[i] if i < len(embs) else None
                doc_text = str(doc)[:2000] if doc else ""
                candidates.append({"id": doc_id, "text": doc_text, "score": score, "source": "vector", "meta": meta, "embedding": emb})

        # Step 2: Keyword fallback (SQLite)
        keywords = [w for w in query.split() if len(w) > 4][:8]
        if keywords and db_conn:
            cursor = db_conn.cursor()
            for word in keywords:
                cursor.execute(
                    "SELECT substr(content, 1, 1200) FROM chat_history "
                    "WHERE content LIKE ? AND role != 'system_note' "
                    "ORDER BY id DESC LIMIT 5",
                    (f"%{word}%",),
                )
                rows = cursor.fetchall()
                for r in rows:
                    candidates.append({"id": None, "text": r[0], "score": 0.5, "source": "keyword", "meta": {}})

        # Step 3: Deduplicate
        seen_hashes = set()
        unique_candidates = []
        for c in candidates:
            h = hash(c["text"])
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_candidates.append(c)

        if not unique_candidates:
            return "", 0

        # Step 3.5: RFM Interceptor
        import math
        import time
        current_time = time.time()
        for c in unique_candidates:
            base_score = c.get("score", 0.5)
            meta = c.get("meta", {})
            
            # Frequency (F) multiplier
            ref_count = meta.get("reference_count", 0)
            frequency_boost = 1.0 + (0.1 * math.log1p(ref_count))
            
            # Recency (R) exponential decay
            epoch_stamp = meta.get("epoch_timestamp", current_time)
            age_in_days = max(0.0, (current_time - float(epoch_stamp)) / 86400.0)
            time_decay = math.exp(-0.05 * age_in_days)
            
            # Final score injection for MMR
            c["rfm_score"] = base_score * frequency_boost * time_decay

        # Step 4: MMR Reranking (CPU Bomb FIX)
        t2 = time.time()
        
        # ONLY pass candidates that already have a pre-computed vector!
        vector_candidates = [c for c in unique_candidates if c.get("embedding") is not None]
        keyword_candidates = [c for c in unique_candidates if c.get("embedding") is None]

        selected_docs = self._mmr_rerank(
            query_vector=query_vector,
            candidates=vector_candidates,
            top_k=20,
            lambda_param=0.7,
        )
        print(f"🔍 RAG - MMR Reranking took: {time.time() - t2:.2f}s")

        # Safely append up to 3 keyword-matched docs to the end (NO MATH REQUIRED!)
        selected_docs.extend(keyword_candidates[:3])

        # Step 5: Budget Packing
        import time
        packed_text = []
        current_tokens = 0
        update_ids = []
        update_metas = []
        
        for doc in selected_docs:
            epoch_ts = doc.get("meta", {}).get("epoch_timestamp")
            
            bucket = "[Unknown Time]"
            if epoch_ts:
                diff = time.time() - float(epoch_ts)
                if diff < 600: bucket = "[Past 10 minutes]"
                elif diff < 3600: bucket = "[Past hour]"
                elif diff < 86400 * 2: bucket = "[Yesterday]"
                elif diff < 86400 * 7: bucket = "[This week]"
                elif diff < 86400 * 60: bucket = "[Older]"
                else: bucket = "[Older than 2 months]"
            
            tagged_doc = f"{bucket}\n{doc['text']}"
            doc_tokens = self.count_tokens(tagged_doc)
            if current_tokens + doc_tokens <= token_budget:
                packed_text.append(tagged_doc)
                current_tokens += doc_tokens
                
                # Track frequency for vectors
                if doc.get("source") == "vector" and doc.get("id"):
                    meta = doc.get("meta", {}).copy()
                    meta["reference_count"] = meta.get("reference_count", 0) + 1
                    update_ids.append(doc["id"])
                    update_metas.append(meta)

        # Update ChromaDB reference counts
        if update_ids and self.memory_collection:
            try:
                self.memory_collection.update(ids=update_ids, metadatas=update_metas)
            except Exception as e:
                print(f"⚠️ Failed to update reference_count: {e}")

        print(f"🔍 RAG - TOTAL RAG TOOK: {time.time() - t_start:.2f}s")
        return "\n\n---\n\n".join(packed_text), current_tokens

    def _mmr_rerank(self, query_vector, candidates, top_k=15, lambda_param=0.7):
        """Maximal Marginal Relevance reranking for diversity."""
        candidate_embeddings = []
        valid_candidates = []
        
        # SAFETY RAIL: Only accept candidates with pre-existing embeddings
        for c in candidates:
            if c.get("embedding") is not None:
                candidate_embeddings.append(c["embedding"])
                valid_candidates.append(c)
                
        if not valid_candidates:
            return []

        query_vec_np = np.array(query_vector)

        selected_indices = []
        candidate_indices = list(range(len(valid_candidates)))

        for _ in range(min(top_k, len(valid_candidates))):
            best_mmr = -np.inf
            best_idx = -1

            for idx in candidate_indices:
                if idx in selected_indices:
                    continue

                current_emb = candidate_embeddings[idx]
                relevance = valid_candidates[idx].get("rfm_score", 0.5)

                if not selected_indices:
                    diversity = 0
                else:
                    sims_to_selected = []
                    for sel_idx in selected_indices:
                        sel_emb = candidate_embeddings[sel_idx]
                        sim = np.dot(current_emb, sel_emb) / (
                            norm(current_emb) * norm(sel_emb)
                        )
                        sims_to_selected.append(sim)
                    diversity = max(sims_to_selected)

                mmr_score = (lambda_param * relevance) - ((1 - lambda_param) * diversity)
                if mmr_score > best_mmr:
                    best_mmr = mmr_score
                    best_idx = idx

            if best_idx != -1:
                selected_indices.append(best_idx)
            else:
                break

        return [valid_candidates[i] for i in selected_indices]

    # -------------------------------------------------------------------------
    # DELTA SUMMARIZER
    # -------------------------------------------------------------------------
    def run_delta_summary(self, new_messages, previous_summary, completion_fn, cheap_model):
        """
        Merge new conversation messages into the rolling summary using a
        background LLM call.

        Args:
            new_messages: List of {"role", "content"} dicts (the delta).
            previous_summary: The current rolling summary string.
            completion_fn: Callable(messages, model_id, max_tokens) -> str.
                           Provided by ContextEngine, already provider-aware.
            cheap_model: Model ID for the summarizer (from models.json defaults).

        Returns:
            Updated summary string.
        """
        # 1. Prepare input
        text_block = ""
        for msg in new_messages:
            timestamp_str = msg.get('iso_timestamp', 'Unknown Time')
            content = str(msg.get("content", ""))[:1200]
            text_block += f"[{timestamp_str}] {msg['role'].upper()}: {content}\n"

        if len(text_block) > 16000:
            text_block = text_block[:16000] + "...[truncated]"

        # Safety cap for the delta
        if self.count_tokens(text_block) > 4000:
            text_block = text_block[:12000] + "...[truncated]..."

        # Cold boot handling
        if previous_summary == "Session just started.":
            previous_summary = ""

        # 2. Call background model
        import datetime
        current_iso_string = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        try:
            print(f"\n📨 SUMMARISER ({cheap_model}): {len(new_messages)} new messages")

            messages = [
                {"role": "system", "content":
                    f"[System Anchor]: The current system time is {current_iso_string}. Use this as your absolute present for all temporal reasoning.\n\n"
                    "You are a rolling session memory and a temporal archivist.\n"
                    "Your job:\n"
                    "- Preserve the overall purpose and flow of this chat\n"
                    "- Preserve user habits, tone, jokes, preferences\n"
                    "- Preserve recurring facts or themes but final summary should not be repetative\n"
                    "- Do not list technical details or errors.\n"
                    "Rules:\n"
                    "- Output structured bullet points (max 400 tokens)\n"
                    "- Preserve context, user habits, and long-term goals\n"
                    "- Discard trivial chit-chat\n"
                    "- Pay attention to the timestamps attached to each message to understand the flow.\n"
                    "- Note which events happened first and which happened last.\n"
                    "- Compare timestamps to the [System Anchor], and group the events into distinct, relative time buckets (e.g., [Past 10 minutes], [Past hour], [Yesterday], [This week], [Older than 2 months]). Do not write a generic summary; output a structured timeline."
                },
                {"role": "user", "content":
                    f"CURRENT SUMMARY:\n{previous_summary}\n\nNEW DELTA (Recent events):\n{text_block}\n\n"
                    "Merge the New Delta into the Current Summary. Remove outdated info."
                },
            ]

            # completion_fn is provider-aware (from context_engine._call_cheap_model)
            new_summary = completion_fn(messages, cheap_model, max_tokens=400)
            if hasattr(new_summary, "strip"):
                new_summary = new_summary.strip()

            print(f"\n📬 SUMMARISER RESPONSE:")
            print(new_summary)
            print("------------------------------------------\n")

            return new_summary

        except Exception as e:
            print(f"⚠️ Summariser ({cheap_model}) failed: {e}")
            return previous_summary
