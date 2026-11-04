"""
LLM provider abstraction.

The rest of the codebase talks to an internal client interface
(`client.beta.messages.stream()`, `client.messages.create()`, and reads back
Message-like objects with `.content`, `.stop_reason`, `.usage`).

`factory.build_llm_client()` returns `OpenAICompatibleClient`, a drop-in
stand-in with that shape that talks to any OpenAI-compatible
`/chat/completions` endpoint. Only the conversational + client-side
tool-calling loop is translated; vision is supported, and structured JSON is
mapped to `response_format`. See OPENAI_COMPATIBILITY.md.
"""
from core.llm_providers.factory import build_llm_client, utility_model

__all__ = ["build_llm_client", "utility_model"]
