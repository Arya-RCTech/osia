# api.py — Headless FastAPI wrapper for Osia ContextEngine
# Part of Osia Build 2.0 (Phase 1.8 refactor)
#
# Near-identical to the original api.py.
# Only change: ContextEngine is now an orchestrator that internally
# delegates to DBManager and MemoryEngine. The import and public API
# surface are unchanged.

import os
import sys
import os

# Add project root to sys.path so we can import 'tools' and other root modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Force UTF-8 on Windows so emoji in print() calls
# don't crash under cp1252 console encoding.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from context_engine import ContextEngine
from model_registry import registry

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent.parent / ".env")

# HuggingFace Auth & Cache Setup
current_dir = Path(__file__).parent.absolute()
hf_cache_dir = current_dir.parent / "hf_cache"
hf_cache_dir.mkdir(parents=True, exist_ok=True)

# Set cache location outside osia v0 directory
os.environ["HF_HOME"] = str(hf_cache_dir)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_cache_dir)
os.environ["FASTEMBED_CACHE_PATH"] = str(hf_cache_dir)
# Start online for first load, user will change to 1 later
os.environ["HF_HUB_OFFLINE"] = "0"
# Suppress advisory warnings since transformers is only used for tokenizers
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "0"

# Hugging Face tools will automatically pick up the HF_TOKEN environment variable.
# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

# --- Requests ---

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user message to send.")
    model_id: str | None = Field(
        default=None,
        description="Optional model override (e.g. 'openai/gpt-oss-120b'). Uses engine default if omitted.",
    )
    thinking: bool = Field(
        default=False,
        description="Whether to enable overthinking mode.",
    )


class CreateThreadRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Display name for the new thread.")


class SwitchThreadRequest(BaseModel):
    thread_id: int = Field(..., description="ID of the thread to switch to.")


class RenameThreadRequest(BaseModel):
    name: str = Field(..., min_length=1, description="New display name for the thread.")


class LoadPersonaRequest(BaseModel):
    persona_name: str = Field(
        ...,
        min_length=1,
        description="Persona file stem (e.g. 'coder') or full filename ('coder.json').",
    )


# --- Responses ---

class ChatResponse(BaseModel):
    response: str
    thread_id: int
    latency: float | None = None
    thread_name: str | None = None


class CreateThreadResponse(BaseModel):
    thread_id: int | None
    name: str


class SwitchThreadResponse(BaseModel):
    previous_thread_id: int
    current_thread_id: int


class LoadPersonaResponse(BaseModel):
    success: bool
    persona_name: str
    active_persona: dict


class PersonaInfo(BaseModel):
    name: str
    label: str


class HealthResponse(BaseModel):
    status: str = "ok"
    active_thread_id: int
    active_persona: str
    scratchpad_preview: str
    session_length: int
    rolling_summary_preview: str
    active_local_models: list[str] = Field(default_factory=list)

class ModelEntry(BaseModel):
    id: str
    display_name: str
    provider: str
    supports_thinking: bool
    is_default: bool


# ---------------------------------------------------------------------------
# Singleton Engine + Lifespan
# ---------------------------------------------------------------------------

engine: ContextEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot the ContextEngine once on startup; tear down on shutdown.

    API keys are now resolved inside ContextEngine via ModelRegistry,
    so we just call ContextEngine() with no arguments.
    """
    global engine
    engine = ContextEngine()
    yield
    # Graceful cleanup
    if engine and hasattr(engine, "db") and engine.db:
        engine.db.close()
    
    # Kill any background KoboldCpp models we spun up
    try:
        import kobold_manager
        kobold_manager.shutdown_all()
    except Exception as e:
        print(f"⚠️ Error shutting down Kobold models: {e}")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Osia API",
    version="2.0.0",
    description="Headless REST interface for the Osia ContextEngine (Refactored).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from tools.api import router as tools_router
app.include_router(tools_router)


def _require_engine() -> ContextEngine:
    """Guard that raises 503 if the engine failed to initialize."""
    if engine is None:
        raise HTTPException(status_code=503, detail="ContextEngine is not initialized.")
    return engine


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ── Chat (heavy path — uses threadpool) ──────────────────────────────────────

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message and receive the AI response.

    This is the only endpoint that performs synchronous network + vector
    computation, so it is explicitly dispatched to a worker thread via
    ``run_in_threadpool`` to keep the ASGI event loop responsive.
    """
    eng = _require_engine()
    response_text, stats = await run_in_threadpool(
        eng.chat, req.message, req.model_id, req.thinking
    )
    latency: float | None = None
    thread_name: str | None = None
    if isinstance(stats, dict):
        raw_lat = stats.get("latency")
        if isinstance(raw_lat, (int, float)):
            latency = float(raw_lat)
        raw_name = stats.get("thread_name")
        if isinstance(raw_name, str):
            thread_name = raw_name

    return ChatResponse(
        response=response_text,
        thread_id=eng.current_thread_id,
        latency=latency,
        thread_name=thread_name,
    )



import asyncio
import json
from fastapi.responses import StreamingResponse

# Serialise all streaming requests so concurrent calls from the client
# (e.g. user sends a second message while the first is still generating)
# never touch the singleton ContextEngine simultaneously.
# ContextEngine has mutable shared state (active_session, scratchpad, …)
# and is NOT thread-safe — concurrent access causes state corruption.
_chat_lock = asyncio.Lock()

@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    """Stream the AI response using Server-Sent Events (SSE).

    chat_stream() is now a native async generator (uses httpx for Ollama,
    asyncio.to_thread for Gemini/Groq), so we iterate it directly — no
    iterate_in_threadpool needed. This prevents the deadlock where a
    sync worker held the lock forever when the client disconnected.
    """
    eng = _require_engine()

    async def event_generator():
        try:
            async with _chat_lock:
                async for chunk in eng.chat_stream(req.message, req.model_id, req.thinking):
                    yield f"data: {json.dumps(chunk)}\n\n"
        except asyncio.CancelledError:
            print("⚠️ Client stream dropped (Caught in API). Bubbling cancellation to ContextEngine...")
            raise
        finally:
            import ctypes
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Threads ──────────────────────────────────────────────────────────────────

@app.post("/api/v1/preload")
def preload_models():
    """Endpoint for the UI to proactively trigger heavy model loading."""
    eng = _require_engine()
    eng.state.memory.preload()
    return {"status": "preloading_started"}

@app.get("/api/v1/threads")
def list_threads():
    """Return all threads as a list of ``{id, name}`` objects."""
    eng = _require_engine()
    rows = eng.get_threads()  # [(id, name, created_at), ...]
    return [{"id": row[0], "name": row[1], "created_at": row[2]} for row in rows]


@app.post("/api/v1/threads/create", response_model=CreateThreadResponse)
def create_thread(req: CreateThreadRequest):
    """Create a new conversation thread."""
    eng = _require_engine()
    new_id = eng.create_thread(req.name)
    if new_id is None:
        raise HTTPException(status_code=500, detail="Failed to create thread.")
    return CreateThreadResponse(thread_id=new_id, name=req.name)


@app.post("/api/v1/threads/switch", response_model=SwitchThreadResponse)
def switch_thread(req: SwitchThreadRequest):
    """Freeze the current thread context and thaw the target thread."""
    eng = _require_engine()
    previous = eng.current_thread_id
    eng.switch_thread(req.thread_id)
    return SwitchThreadResponse(
        previous_thread_id=previous,
        current_thread_id=eng.current_thread_id,
    )


@app.post("/api/v1/threads/{thread_id}/rename")
def rename_thread(thread_id: int, req: RenameThreadRequest):
    """Rename an existing thread."""
    eng = _require_engine()
    success = eng.rename_thread(thread_id, req.name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to rename thread.")
    return {"thread_id": thread_id, "name": req.name}


@app.delete("/api/v1/threads/{thread_id}")
def delete_thread(thread_id: int):
    """Delete a thread and all its chat history."""
    eng = _require_engine()
    success = eng.delete_thread(thread_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete thread (it may be active or not found).")
    return {"deleted": True, "thread_id": thread_id}


# ── History ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/history")
def get_history(
    thread_id: int = Query(..., description="Thread ID to fetch history for."),
    limit: int = Query(50, ge=1, le=500, description="Max messages to return."),
):
    """Return raw conversation history for a specific thread."""
    eng = _require_engine()
    history = eng.load_history(limit=limit, thread_id=thread_id)
    return {"thread_id": thread_id, "limit": limit, "messages": history}


# ── Personas ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/personas", response_model=list[PersonaInfo])
def list_personas():
    """Scan the ``personas/`` directory and return available persona files."""
    personas_path = Path(__file__).parent.parent / "personas"
    if not personas_path.exists():
        return [PersonaInfo(name="default", label="Default")]

    json_files = sorted(personas_path.glob("*.json"))
    if not json_files:
        return [PersonaInfo(name="default", label="Default")]

    return [
        PersonaInfo(
            name=f.stem,
            label=f.stem.replace("_", " ").title(),
        )
        for f in json_files
    ]


@app.post("/api/v1/personas/load", response_model=LoadPersonaResponse)
def load_persona(req: LoadPersonaRequest):
    """Switch the engine's active persona JSON file."""
    eng = _require_engine()
    success = eng.load_persona(req.persona_name)
    return LoadPersonaResponse(
        success=success,
        persona_name=req.persona_name,
        active_persona=eng.current_persona,
    )


# ── Models ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/models", response_model=list[ModelEntry])
def list_models():
    """Return all available models from models.json.

    The default chat model is always first in the list.
    Frontend dropdowns should call this on startup instead of using
    any hardcoded model lists.
    """
    return registry.for_api()


@app.post("/api/v1/models/reload")
def reload_models():
    """Hot-reload models.json without restarting the server.

    Useful during development when you add/rename models frequently.
    """
    registry.reload()
    return {"reloaded": True, "model_count": len(registry.all_models())}


@app.post("/api/v1/models/{model_id}/stop")
def stop_model(model_id: str):
    """Gracefully kills the KoboldCpp instance for the specified model."""
    import kobold_manager
    success = kobold_manager.shutdown_model(model_id)
    return {"success": success, "model_id": model_id}


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    """System state overview for debugging and dashboards."""
    eng = _require_engine()
    persona_name = eng.current_persona.get("name", "Unknown")
    scratchpad_preview = (eng.scratchpad or "")[:200]
    summary_preview = (eng.rolling_summary or "")[:200]
    
    import kobold_manager
    active_models = []
    for model_id in registry.all_models():
        if registry.provider_for(model_id) == "koboldcpp":
            port = registry.get_port(model_id)
            if port and kobold_manager.is_port_in_use(port):
                active_models.append(model_id)
                
    return HealthResponse(
        active_thread_id=eng.current_thread_id,
        active_persona=persona_name,
        scratchpad_preview=scratchpad_preview,
        session_length=len(eng.active_session),
        rolling_summary_preview=summary_preview,
        active_local_models=active_models,
    )


# ── Shutdown ─────────────────────────────────────────────────────────────────

@app.post("/api/v1/shutdown")
def shutdown_server():
    """Gracefully terminate the FastAPI / Uvicorn server."""
    import signal
    import threading
    import time

    def _do_shutdown():
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return {"status": "shutting_down"}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
