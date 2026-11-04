# OpenAI Compatibility

This project is built exclusively for OpenAI-compatible endpoints. Every model
call goes through `core/llm_providers/openai_compatible.py`, which talks to any
`/chat/completions` API:

- OpenAI
- OpenRouter, Together, Groq, and similar hosted providers
- Local servers such as Ollama, LM Studio, and vLLM

## Configuration

Set these in `.env`:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
# Optional; overrides api.model from bots/<bot>.yaml
OPENAI_MODEL=gpt-4o
# Optional; caps outgoing max_tokens
OPENAI_MAX_OUTPUT_TOKENS=16384
# Optional; model for episode distillation and watch evaluation
OPENAI_UTILITY_MODEL=gpt-4o-mini
```

`OPENAI_API_KEY` and `OPENAI_BASE_URL` are required. A model must be configured
either through `OPENAI_MODEL` or `api.model` in the bot YAML.

## How it works

`OpenAICompatibleClient` exposes the client shape the shared code expects
(`client.messages.create`, `client.beta.messages.stream`, and responses with
`.content`, `.stop_reason`, `.usage`). At the boundary it translates:

- system prompt (string or text blocks) → OpenAI system message
- text / tool_use / tool_result blocks → OpenAI messages + `tool_calls`
- image blocks (base64 or URL) → OpenAI `image_url` parts
- `tools[].input_schema` → OpenAI function `parameters`
- `output_config.format.json_schema` → `response_format` (best effort)
- OpenAI completion → the internal response shape

Only client-side function tools are supported.

## What works

| Feature | Status |
|---|---|
| Core conversation | Full support |
| Client-side tool calling | Full support |
| Vision / image attachments | Full support (base64 data URLs) |
| Memory | Full support: the memory tool is declared as an explicit function schema and executed locally |
| Episode distillation | Full support via `response_format` JSON schema (backend permitting) |
| Client-side web search / fetch | Full support via the keyless `ddgs` backend |
| `create_pptx` | Full support; builds the file locally and attaches it to the reply |
| MCP tools | Full support |
| `ask_prime` cross-server messaging | Full support |

## What is not supported

The following were provider-specific server-side features and have been removed:

- Code execution / skills containers
- Files API attachment uploads
- Batches API
- Native web search / fetch server tools
- Extended thinking / effort parameters
- Prompt caching (`cache_control`)

Attachments are stored locally. Images are sent inline as base64; other files
remain on disk and are referenced by path through the attachment tools.

## Notes on backends

- `response_format` with JSON schema is not implemented by every
  OpenAI-compatible server. Episode distillation catches and logs failures.
- Some local servers ignore `OPENAI_API_KEY`; any non-empty placeholder works.
- Model names are provider-specific. Nothing in the codebase assumes a
  particular model family.
- Token usage/cost: token counts are reported when the endpoint returns them;
  dollar cost is not estimated because prices vary by endpoint and model.
