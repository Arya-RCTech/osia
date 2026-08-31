# model_registry.py — Single source of truth loader for models.json
# Part of Osia Build 2.0
#
# Usage:
#   from model_registry import registry
#
#   registry.default_chat_model()       -> "gemma-4-31b-it"
#   registry.default_cheap_model()      -> "llama-3.3-70b-versatile"
#   registry.provider_for("gemma-4-31b-it")  -> "google"
#   registry.get_api_key("groq")        -> value of GROQ_API_KEY from .env
#   registry.max_output_tokens("gemma-4-31b-it")  -> 4500
#   registry.rag_budget("gemma-4-31b-it")          -> 4000
#   registry.all_models()               -> {id: config_dict, ...}
#   registry.for_api()                  -> list of {id, display_name, provider}

import json
import os
from pathlib import Path


_MODELS_FILE = Path(__file__).parent / "models.json"


class ModelRegistry:
    """
    Loads models.json once at import time and exposes typed helpers.

    Reload at runtime by calling registry.reload() — useful if you hot-swap
    models.json without restarting the server (dev workflow).
    """

    def __init__(self, path: Path = _MODELS_FILE):
        self._path = path
        self._data: dict = {}
        self.reload()

    # -------------------------------------------------------------------------
    # Loader
    # -------------------------------------------------------------------------
    def reload(self) -> None:
        """Re-read models.json from disk."""
        try:
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
            print(f"✅ ModelRegistry: loaded {len(self._data.get('models', {}))} models from {self._path.name}")
        except FileNotFoundError:
            print(f"⚠️  ModelRegistry: {self._path} not found — using empty config")
            self._data = {"defaults": {}, "providers": {}, "models": {}}
        except json.JSONDecodeError as e:
            print(f"❌ ModelRegistry: JSON parse error in {self._path}: {e}")
            self._data = {"defaults": {}, "providers": {}, "models": {}}

    # -------------------------------------------------------------------------
    # Defaults
    # -------------------------------------------------------------------------
    def default_chat_model(self) -> str:
        return self._data.get("defaults", {}).get("chat_model", "")

    def default_cheap_model(self) -> str:
        return self._data.get("defaults", {}).get("cheap_model", "")

    # -------------------------------------------------------------------------
    # Per-model helpers
    # -------------------------------------------------------------------------
    def get(self, model_id: str) -> dict:
        """Return the full config dict for a model, or {} if not found."""
        return self._data.get("models", {}).get(model_id, {})

    def provider_for(self, model_id: str) -> str:
        """Return the provider name ('groq' or 'google') for a model."""
        return self.get(model_id).get("provider", "groq")

    def max_output_tokens(self, model_id: str) -> int:
        return self.get(model_id).get("max_output_tokens", 2048)

    def rag_budget(self, model_id: str) -> int:
        return self.get(model_id).get("rag_budget_tokens", 2000)

    def max_context_tokens(self, model_id: str) -> int:
        return self.get(model_id).get("max_context_tokens", 7000)

    def supports_thinking(self, model_id: str) -> bool:
        return self.get(model_id).get("supports_thinking", False)

    def get_port(self, model_id: str) -> int | None:
        return self.get(model_id).get("port")

    def get_gguf_filename(self, model_id: str) -> str | None:
        return self.get(model_id).get("gguf_filename")

    def get_gpulayers(self, model_id: str) -> int | None:
        return self.get(model_id).get("gpulayers")

    # -------------------------------------------------------------------------
    # API key resolution (reads env vars named in providers block)
    # -------------------------------------------------------------------------
    def get_api_key(self, provider: str) -> str | None:
        """
        Look up the API key for a provider by reading the env var named in
        models.json under providers.<provider>.api_key_env.

        Example models.json entry:
            "providers": { "groq": { "api_key_env": "GROQ_API_KEY" } }
        """
        env_var = (
            self._data.get("providers", {})
            .get(provider, {})
            .get("api_key_env")
        )
        if not env_var:
            return None
        return os.getenv(env_var)

    def get_api_key_for_model(self, model_id: str) -> str | None:
        """Shortcut: resolve the API key for whichever provider owns model_id."""
        provider = self.provider_for(model_id)
        return self.get_api_key(provider)

    # -------------------------------------------------------------------------
    # Bulk accessors
    # -------------------------------------------------------------------------
    def all_models(self) -> dict:
        """Return the full {model_id: config} dict."""
        return self._data.get("models", {})

    def for_api(self) -> list[dict]:
        """
        Return a JSON-serialisable list suitable for the /api/v1/models endpoint.
        The default chat model is always returned first.
        """
        default_id = self.default_chat_model()
        models_dict = self.all_models()

        result = []
        # Default model first
        if default_id and default_id in models_dict:
            cfg = models_dict[default_id]
            result.append({
                "id": default_id,
                "display_name": cfg.get("display_name", default_id),
                "provider": cfg.get("provider", "groq"),
                "supports_thinking": cfg.get("supports_thinking", False),
                "is_default": True,
            })

        # Rest in insertion order
        for model_id, cfg in models_dict.items():
            if model_id == default_id:
                continue
            result.append({
                "id": model_id,
                "display_name": cfg.get("display_name", model_id),
                "provider": cfg.get("provider", "groq"),
                "supports_thinking": cfg.get("supports_thinking", False),
                "is_default": False,
            })

        return result


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------
registry = ModelRegistry()
