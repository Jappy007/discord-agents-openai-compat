"""
LLM provider abstraction.

The rest of the codebase (reactive_engine, agentic_engine, skills_manager,
episode_manager, files_api_client, batch_client, ...) is written directly
against the `anthropic` SDK's client shape: `client.beta.messages.stream()`,
`client.messages.create()`, `client.beta.files.*`, `client.beta.skills.*`,
`client.beta.messages.batches.*`, and it reads back Anthropic Message objects
(`response.content`, `response.stop_reason`, `response.usage`, ...).

`factory.build_llm_client()` returns either the real `AsyncAnthropic` client
(default), or `OpenAICompatibleClient`, a drop-in stand-in with the same
attribute shape that talks to any OpenAI-compatible `/chat/completions`
endpoint instead. Only the core conversational + client-side tool-calling
loop is translated between the two wire formats; server-only Anthropic
features (code execution/skills, the Files API, the built-in memory tool,
native web search, the Batches API, prompt caching, extended thinking) have
no OpenAI-compatible equivalent and are cleanly disabled - see
OPENAI_COMPATIBILITY.md for the current state of each.
"""
from core.llm_providers.factory import build_llm_client, get_llm_provider, is_anthropic_native

__all__ = ["build_llm_client", "get_llm_provider", "is_anthropic_native"]
