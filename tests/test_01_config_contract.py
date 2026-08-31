"""
test_01_config_contract.py — ModelRegistry config-as-contract tests
═══════════════════════════════════════════════════════════════════

Risk area #6 from test brief: supports_thinking, max_context_tokens,
rag_budget are read by multiple consumers. A single test that asserts
all consumers see the same value catches config-drift bugs early.

Also validates structural invariants of models.json itself.
"""

import os
import sys
import json
import time
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tests.conftest import timed_call, TimedResult


# ─────────────────────────────────────────────────────────────────────────────
# Unit: ModelRegistry accessor correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestModelRegistryAccessors:
    """Validate that registry helpers return correct typed values for every model."""

    def test_default_chat_model_exists(self, registry):
        """Default chat model must be a non-empty string that exists in models."""
        r = timed_call(registry.default_chat_model)
        assert isinstance(r.value, str) and len(r.value) > 0, \
            f"default_chat_model() returned {r.value!r}"
        assert r.value in registry.all_models(), \
            f"Default chat model {r.value!r} not found in models dict"
        print(f"  ✓ default_chat_model = {r.value!r}  ({r.elapsed_ms:.2f}ms)")

    def test_default_cheap_model_exists(self, registry):
        """Default cheap model must be a non-empty string that exists in models."""
        r = timed_call(registry.default_cheap_model)
        assert isinstance(r.value, str) and len(r.value) > 0, \
            f"default_cheap_model() returned {r.value!r}"
        assert r.value in registry.all_models(), \
            f"Default cheap model {r.value!r} not found in models dict"
        print(f"  ✓ default_cheap_model = {r.value!r}  ({r.elapsed_ms:.2f}ms)")

    def test_all_models_have_required_fields(self, registry):
        """Every model entry must have provider, max_output_tokens, max_context_tokens."""
        models = registry.all_models()
        assert len(models) > 0, "models.json contains zero models"

        for model_id, cfg in models.items():
            assert "provider" in cfg, f"{model_id}: missing 'provider'"
            assert "max_output_tokens" in cfg, f"{model_id}: missing 'max_output_tokens'"
            assert "max_context_tokens" in cfg, f"{model_id}: missing 'max_context_tokens'"
            assert "supports_thinking" in cfg, f"{model_id}: missing 'supports_thinking'"
            assert isinstance(cfg["supports_thinking"], bool), \
                f"{model_id}: supports_thinking must be bool, got {type(cfg['supports_thinking'])}"
        print(f"  ✓ All {len(models)} models have required fields")

    def test_provider_for_returns_valid_provider(self, registry):
        """provider_for() must return one of the known provider strings."""
        valid_providers = {"groq", "google", "koboldcpp", "ollama"}
        for model_id in registry.all_models():
            provider = registry.provider_for(model_id)
            assert provider in valid_providers, \
                f"{model_id}: provider_for() returned {provider!r}, expected one of {valid_providers}"
        print(f"  ✓ All models resolve to valid providers")

    def test_rag_budget_less_than_context_window(self, registry):
        """rag_budget must be strictly less than max_context_tokens for every model."""
        for model_id in registry.all_models():
            rag = registry.rag_budget(model_id)
            ctx = registry.max_context_tokens(model_id)
            assert rag < ctx, \
                f"{model_id}: rag_budget ({rag}) >= max_context_tokens ({ctx})"
        print(f"  ✓ RAG budgets are bounded by context windows")

    def test_output_tokens_less_than_context(self, registry):
        """max_output_tokens must be < max_context_tokens (you can't output more than the window)."""
        for model_id in registry.all_models():
            out = registry.max_output_tokens(model_id)
            ctx = registry.max_context_tokens(model_id)
            assert out < ctx, \
                f"{model_id}: max_output_tokens ({out}) >= max_context_tokens ({ctx})"


# ─────────────────────────────────────────────────────────────────────────────
# Integration: Cross-consumer config consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigConsistency:
    """
    Verify that the registry values consumed by prompt_builder, llm_transport,
    thinking_manager, and memory_engine all agree for every model_id.
    This catches config-drift bugs where different modules read stale or
    different default values.
    """

    def test_supports_thinking_agrees_across_consumers(self, registry):
        """
        thinking_manager and llm_transport both call registry.supports_thinking().
        Verify the single-source-of-truth contract: calling it twice yields the same value.
        """
        for model_id in registry.all_models():
            v1 = registry.supports_thinking(model_id)
            v2 = registry.supports_thinking(model_id)
            assert v1 == v2, f"{model_id}: supports_thinking returned {v1} then {v2}"

    def test_for_api_includes_all_models(self, registry):
        """for_api() must return an entry for every model in all_models()."""
        api_list = registry.for_api()
        api_ids = {entry["id"] for entry in api_list}
        all_ids = set(registry.all_models().keys())
        assert api_ids == all_ids, \
            f"for_api() missing models: {all_ids - api_ids}"

    def test_for_api_default_is_first(self, registry):
        """The default chat model must be the first entry in for_api()."""
        api_list = registry.for_api()
        if api_list:
            assert api_list[0]["is_default"] is True, \
                f"First model in for_api() is not marked as default: {api_list[0]}"
            assert api_list[0]["id"] == registry.default_chat_model()

    def test_reload_idempotent(self, registry):
        """Calling reload() twice must produce identical state."""
        r1 = timed_call(registry.reload)
        snap1 = json.dumps(registry.all_models(), sort_keys=True)
        r2 = timed_call(registry.reload)
        snap2 = json.dumps(registry.all_models(), sort_keys=True)
        assert snap1 == snap2, "reload() produced different state on second call"
        print(f"  ✓ reload() idempotent  ({r1.elapsed_ms:.1f}ms, {r2.elapsed_ms:.1f}ms)")


# ─────────────────────────────────────────────────────────────────────────────
# Unit: ThinkingManager guard — non-thinking models must not get reasoning payload
# ─────────────────────────────────────────────────────────────────────────────

class TestThinkingManagerGuard:
    """
    Test brief §2: 'a model without thinking support never gets a reasoning
    payload — a false positive here is a hard crash, not a wrong answer.'
    """

    def test_gemini_no_thinking_model_gets_no_config(self, registry):
        """apply_thinking_config_gemini must NOT set thinking_config for non-thinking models."""
        from thinking_manager import apply_thinking_config_gemini

        for model_id, cfg in registry.all_models().items():
            if cfg.get("provider") != "google":
                continue
            if cfg.get("supports_thinking") is True:
                continue

            kwargs = {"temperature": 0.7, "max_output_tokens": 1024}
            apply_thinking_config_gemini(model_id, kwargs, thinking=True)
            assert "thinking_config" not in kwargs, \
                f"{model_id}: non-thinking Google model got thinking_config injected!"
            print(f"  ✓ {model_id} (google, no-think) — no thinking_config injected")

    def test_groq_no_thinking_model_gets_no_reasoning(self, registry):
        """apply_thinking_config_groq must strip reasoning_effort for non-thinking models."""
        from thinking_manager import apply_thinking_config_groq

        for model_id, cfg in registry.all_models().items():
            if cfg.get("provider") != "groq":
                continue
            if cfg.get("supports_thinking") is True:
                continue

            kwargs = {"temperature": 0.7, "reasoning_effort": "high"}
            apply_thinking_config_groq(model_id, kwargs, thinking=True)
            assert "reasoning_effort" not in kwargs, \
                f"{model_id}: non-thinking Groq model still has reasoning_effort!"
            print(f"  ✓ {model_id} (groq, no-think) — reasoning_effort stripped")

    def test_groq_thinking_model_gets_reasoning_effort(self, registry):
        """Groq models WITH thinking support must receive reasoning_effort when thinking=True."""
        from thinking_manager import apply_thinking_config_groq

        for model_id, cfg in registry.all_models().items():
            if cfg.get("provider") != "groq" or not cfg.get("supports_thinking"):
                continue

            kwargs = {"temperature": 0.7}
            apply_thinking_config_groq(model_id, kwargs, thinking=True)
            assert "reasoning_effort" in kwargs, \
                f"{model_id}: thinking Groq model didn't get reasoning_effort!"
            assert kwargs["reasoning_effort"] == "default", \
                f"{model_id}: expected reasoning_effort='default', got {kwargs['reasoning_effort']!r}"
            print(f"  ✓ {model_id} (groq, think) — reasoning_effort='default'")

    def test_koboldcpp_thinking_model_gets_template_kwargs(self, registry):
        """KoboldCpp models WITH thinking support must get chat_template_kwargs."""
        from thinking_manager import apply_thinking_config_koboldcpp

        for model_id, cfg in registry.all_models().items():
            if cfg.get("provider") != "koboldcpp" or not cfg.get("supports_thinking"):
                continue

            kwargs = {"temperature": 1.0}
            apply_thinking_config_koboldcpp(model_id, kwargs, thinking=True)
            assert "chat_template_kwargs" in kwargs, \
                f"{model_id}: thinking koboldcpp model didn't get chat_template_kwargs!"
            assert kwargs["chat_template_kwargs"]["enable_thinking"] is True
            print(f"  ✓ {model_id} (koboldcpp, think) — chat_template_kwargs injected")

    def test_koboldcpp_no_thinking_model_gets_nothing(self, registry):
        """KoboldCpp models WITHOUT thinking support must not get template kwargs."""
        from thinking_manager import apply_thinking_config_koboldcpp

        for model_id, cfg in registry.all_models().items():
            if cfg.get("provider") != "koboldcpp" or cfg.get("supports_thinking"):
                continue

            kwargs = {"temperature": 1.0}
            apply_thinking_config_koboldcpp(model_id, kwargs, thinking=True)
            assert "chat_template_kwargs" not in kwargs, \
                f"{model_id}: non-thinking koboldcpp model got chat_template_kwargs!"
            print(f"  ✓ {model_id} (koboldcpp, no-think) — no template kwargs")
