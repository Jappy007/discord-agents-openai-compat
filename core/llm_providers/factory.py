"""
LLM client construction - OpenAI-compatible endpoints only.

Relevant .env keys:
  OPENAI_API_KEY            required
  OPENAI_BASE_URL           required (e.g. https://api.openai.com/v1,
                            http://localhost:11434/v1, or any other
                            OpenAI-compatible /v1 base)
  OPENAI_MODEL              optional - overrides api.model from bots/*.yaml
  OPENAI_MAX_OUTPUT_TOKENS  optional - overrides the per-model output cap
  OPENAI_UTILITY_MODEL      optional - model used for the small internal
                            helper calls (episode distillation, watch-eval).
                            Falls back to OPENAI_MODEL.
"""
import os
from typing import Optional


def build_llm_client(model: str, api_key: str, base_url: str):
    """Build the client used for all model calls.

    `api_key` is accepted for backwards compatibility with older call sites;
    the key always comes from OPENAI_API_KEY.
    """
    from core.llm_providers.openai_compatible import OpenAICompatibleClient

    base_url = os.getenv("OPENAI_BASE_URL")
    if not base_url:
        raise ValueError(
            "OPENAI_BASE_URL must be set in .env "
            "(e.g. https://api.openai.com/v1, http://localhost:11434/v1, ...)"
        )
    max_output_env = os.getenv("OPENAI_MAX_OUTPUT_TOKENS")
    return OpenAICompatibleClient(
        api_key=os.getenv("OPENAI_API_KEY") or api_key,
        base_url=base_url,
        default_model=os.getenv("OPENAI_MODEL"),
        max_output_tokens=int(max_output_env) if max_output_env else None,
    )


def utility_model(fallback: Optional[str] = None) -> Optional[str]:
    """Model used for small internal helper calls (episode distillation,
    watch-eval). Resolves OPENAI_UTILITY_MODEL, then OPENAI_MODEL, then the
    supplied fallback (normally the bot's configured model)."""
    return os.getenv("OPENAI_UTILITY_MODEL") or os.getenv("OPENAI_MODEL") or fallback
