"""
Provider selection - entirely env-driven, per OPENAI_COMPATIBILITY.md.

LLM_PROVIDER=anthropic (default)         -> real anthropic.AsyncAnthropic
LLM_PROVIDER=openai_compatible           -> OpenAICompatibleClient

Relevant .env keys when LLM_PROVIDER=openai_compatible:
  OPENAI_API_KEY            required
  OPENAI_BASE_URL           required (e.g. http://localhost:11434/v1, or
                            any other OpenAI-compatible /v1 base)
  OPENAI_MODEL              optional - overrides api.model from bots/*.yaml
  OPENAI_MAX_OUTPUT_TOKENS  optional - overrides the per-model output cap
                            guess in internal_constants.py (which only knows
                            Claude model names)
  OPENAI_UTILITY_MODEL      optional - model used for the small internal
                            helper calls (episode distillation, watch-eval)
                            that otherwise default to a hardcoded Claude
                            model name. Falls back to OPENAI_MODEL.
"""
import os
from typing import Optional


def get_llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()


def is_anthropic_native() -> bool:
    return get_llm_provider() == "anthropic"


def build_llm_client(api_key: Optional[str] = None):
    """Build the client used for all model calls.

    `api_key` is accepted for backwards compatibility with call sites that
    already have an ANTHROPIC_API_KEY string in hand - it's only used when
    the provider is 'anthropic'. Under 'openai_compatible' the key always
    comes from OPENAI_API_KEY, since a Claude key string wouldn't mean
    anything to a different provider.
    """
    provider = get_llm_provider()

    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        return AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    if provider == "openai_compatible":
        from core.llm_providers.openai_compatible import OpenAICompatibleClient

        base_url = os.getenv("OPENAI_BASE_URL")
        if not base_url:
            raise ValueError(
                "LLM_PROVIDER=openai_compatible requires OPENAI_BASE_URL to be set in .env "
                "(e.g. https://api.openai.com/v1, http://localhost:11434/v1, ...)"
            )
        max_output_env = os.getenv("OPENAI_MAX_OUTPUT_TOKENS")
        return OpenAICompatibleClient(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=base_url,
            default_model=os.getenv("OPENAI_MODEL"),
            max_output_tokens=int(max_output_env) if max_output_env else None,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}' in .env - expected 'anthropic' or 'openai_compatible'"
    )


def utility_model(fallback: str) -> str:
    """Model used for small internal helper calls (episode distillation,
    watch-eval) that otherwise hardcode a Claude model name. Under
    LLM_PROVIDER=openai_compatible those hardcoded names don't exist on the
    target endpoint, so this substitutes OPENAI_UTILITY_MODEL (or
    OPENAI_MODEL) when set.
    """
    if not is_anthropic_native():
        override = os.getenv("OPENAI_UTILITY_MODEL") or os.getenv("OPENAI_MODEL")
        if override:
            return override
    return fallback
