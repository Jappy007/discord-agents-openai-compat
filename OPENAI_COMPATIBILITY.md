# OpenAI-compatible endpoint support

This project talks to Anthropic's Messages API by default. Setting
`LLM_PROVIDER=openai_compatible` in `.env` switches every model call over to
an OpenAI-compatible `/chat/completions` endpoint instead — OpenAI itself,
OpenRouter, Together, Groq, a local Ollama/vLLM/LM Studio server, or anything
else that speaks the same wire format.

Everything needed to point at a new API lives in `.env` — no code or YAML
changes required. See `.env.example` for the full list of `OPENAI_*` keys.

## How it works

`core/llm_providers/openai_compatible.py` implements `OpenAICompatibleClient`,
a drop-in stand-in for `anthropic.AsyncAnthropic` with the same attribute
shape (`client.beta.messages.stream()`, `client.messages.create()`, etc). It
translates Anthropic's message/tool-block format to and from OpenAI's format
at the boundary, so the rest of the codebase (conversation state, context
building, memory, episodes) is unaware of which provider is in use.

## What's translated (works on either provider)

- Core conversation loop and client-side tool-calling (Discord actions,
  memory-search tools, repository tool, custom/MCP tools, etc.)
- Vision — image attachments are translated to OpenAI's `image_url` /
  base64-data-URL format
- Structured JSON output (used for episode-title distillation and
  standing-watch evaluation) — translated to OpenAI's
  `response_format={"type": "json_schema", ...}` on a best-effort basis.
  Not every OpenAI-compatible backend supports strict JSON-schema mode; if
  yours doesn't, these two features will log an error and back off rather
  than crash anything else.
- The two hardcoded Claude model names used for those small internal calls
  (episode distillation, watch-eval) are substituted with `OPENAI_UTILITY_MODEL`
  (or `OPENAI_MODEL`) when set.
- **The built-in memory tool** — Anthropic's native `memory_20250818` server
  type carries no schema of its own; under `openai_compatible` it's declared
  as an explicit function-tool schema instead (`core/memory_tool_executor.py:MEMORY_TOOL_SCHEMA`).
  The actual read/write logic was always local (`MemoryToolExecutor`), so
  memory works identically on either provider.
- **Web search / web fetch** — Anthropic's native server tools are replaced
  under `openai_compatible` with ordinary function tools
  (`tools/client_web_tools.py`) backed by the Brave Search API. Requires
  `BRAVE_SEARCH_API_KEY` in `.env`; if `config.api.web_search.enabled` is
  true but the key is missing, the tools are still offered but every call
  returns a clear error rather than crashing.

## What's disabled under `LLM_PROVIDER=openai_compatible`

These are genuine Anthropic server-side features with no OpenAI-compatible
equivalent. Each disables itself cleanly (a one-time warning in the logs, no
crash) rather than failing loudly mid-conversation:

| Feature | Behavior |
|---|---|
| Code execution / Skills | Never registered as a tool; `skills_manager` fails its init check and disables itself entirely (`bot.skills_manager = None`) |
| Files API (attachment uploads, container-output delivery) | Upload/delete/retrieve calls raise `FeatureNotSupportedError`, caught by existing call sites |
| Prompt caching (`cache_control`) | Silently ignored — no error, just no caching benefit |
| Extended thinking / `effort` | Ignored with a one-time warning; no equivalent reasoning-trace format is assumed |
| Batches API — weekly memory reconsolidation, induction | Disabled at startup (main bot process) and refuses to run (`--consolidate` / `--induct` CLI commands print a clear error and exit) |

## Known gap

`supervisor/` (the optional localhost setup-wizard web UI) only has a "set
Anthropic key" flow (`PUT /api/setup/anthropic`, which validates the key
against Anthropic's API). It hasn't been extended for `openai_compatible` —
if you use the supervisor UI, you'll still need to set the `OPENAI_*` /
`LLM_PROVIDER` values directly in `.env` rather than through that UI. This
wasn't in scope for the initial pass; flag it if you want it wired up.

## Picking a provider

Not every model handles tool-calling and vision equally well. If you hit
issues:
- Confirm your target model supports OpenAI-style function/tool calling —
  the bot relies on it for almost everything (Discord actions, memory
  search, etc), not just optional extras.
- If your provider doesn't support `response_format: json_schema`, episode
  titles and standing watches will just stop updating (logged, non-fatal) —
  everything else keeps working.
- `OPENAI_MAX_OUTPUT_TOKENS` matters: the built-in per-model token-cap table
  only recognizes Claude model names, so unset it defaults to whatever
  `max_tokens` the bot's YAML specifies uncapped by a model-specific ceiling.
