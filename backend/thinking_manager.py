from model_registry import registry

def apply_thinking_config_gemini(model_id: str, config_kwargs: dict, thinking: bool):
    """
    Applies thinking parameters for Google Gemini models.
    Mutates config_kwargs in place.
    """
    supports_thinking = registry.supports_thinking(model_id)
    
    if not supports_thinking:
        # Model does not support thinking at all; do not send any thinking configuration.
        # This prevents 400 INVALID_ARGUMENT errors on non-thinking models like Gemini 3.6 Flash.
        return
        
    from google.genai import types
    if not thinking:
        # Model supports thinking, but user has toggled it OFF.
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
    else:
        # Model supports thinking and user wants it ON.
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="high")

def apply_thinking_config_groq(model_id: str, kwargs: dict, thinking: bool):
    """
    Applies reasoning parameters for Groq models (Qwen, LLaMA, GPT wrappers, etc.).
    Mutates kwargs in place.
    """
    supports_thinking = registry.supports_thinking(model_id)
    
    if not supports_thinking:
        # Model does not support thinking (e.g. GPT).
        # Remove reasoning_effort completely.
        kwargs.pop("reasoning_effort", None)
        return
        
    if thinking:
        # User wants thinking ON.
        # Groq (and Qwen on Groq) requires 'default' instead of 'low'.
        kwargs["reasoning_effort"] = "default"
    else:
        # User wants thinking OFF.
        kwargs["reasoning_effort"] = "none"

def apply_thinking_config_koboldcpp(model_id: str, kwargs: dict, thinking: bool):
    """
    Applies thinking parameters for local KoboldCpp models (e.g., Gemma 4).
    Mutates kwargs in place.
    """
    supports_thinking = registry.supports_thinking(model_id)
    
    if not supports_thinking:
        return
        
    # Standard OpenAI SDK demands custom fields be tucked under extra_body, 
    # but since our llm_transport uses raw httpx requests, we also set it at the top-level 
    # so KoboldCpp receives it correctly!
    if "extra_body" not in kwargs:
        kwargs["extra_body"] = {}
        
    template_kwargs = {
        "enable_thinking": thinking,
        "preserve_thinking": thinking
    }
    
    kwargs["extra_body"]["chat_template_kwargs"] = template_kwargs
    kwargs["chat_template_kwargs"] = template_kwargs
