"""
OpenAICompatibleClient - a drop-in stand-in for `anthropic.AsyncAnthropic`,
backed by any OpenAI-compatible /chat/completions endpoint.

Scope (see OPENAI_COMPATIBILITY.md for the up to date status of each item):
  - Core conversation + client-side tool-calling loop: translated.
  - Vision (image attachments): translated (base64 data URLs).
  - Structured JSON output (`output_config.format.json_schema`, used by
    episode distillation / watch-eval): translated to OpenAI's
    `response_format={"type": "json_schema", ...}` on a best-effort basis -
    not every OpenAI-compatible backend supports it; callers already catch
    and log failures.
  - Anthropic-only server tools/features with no equivalent - the built-in
    memory tool, native web search/fetch, code execution & skills, the
    Files API, the Batches API, prompt caching (`cache_control`), extended
    thinking/effort - are dropped from outgoing requests (once-per-process
    warning logged) or raise a clear FeatureNotSupportedError from their
    stub methods, which existing call sites already catch.
"""
import json
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_warned: set = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


class FeatureNotSupportedError(Exception):
    """Raised by stub methods for Anthropic-only server features (Files API,
    Skills API, Batches API) when running against an OpenAI-compatible
    endpoint. Existing call sites already catch and log this."""


# ---------------------------------------------------------------------------
# Anthropic request shape -> OpenAI request shape
# ---------------------------------------------------------------------------

def _flatten_text(content) -> str:
    """Anthropic 'system' param (str, or list of text blocks) -> plain str."""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == "text":
            parts.append(block.get("text") if isinstance(block, dict) else block.text)
    return "\n".join(p for p in parts if p)


def _tool_result_text(content) -> str:
    """Anthropic tool_result content (str, or list of blocks) -> a string
    an OpenAI 'tool' role message can carry."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "image":
                parts.append("[image omitted - not supported in tool results over this connection]")
            else:
                parts.append(json.dumps(block, default=str))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _image_block_to_openai(block: dict) -> Optional[dict]:
    source = block.get("source", {}) or {}
    stype = source.get("type")
    if stype == "base64":
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        return {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
    if stype == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url")}}
    _warn_once("image_source", f"Unsupported image source type '{stype}' for the OpenAI-compatible provider - image dropped")
    return None


_DROPPED_ASSISTANT_BLOCK_TYPES = (
    "server_tool_use", "code_execution_tool_result", "bash_code_execution_tool_result",
    "web_search_tool_result", "web_fetch_tool_result", "container_upload",
)


def anthropic_messages_to_openai(system, messages: List[dict]) -> List[dict]:
    openai_messages = []
    system_text = _flatten_text(system)
    if system_text:
        openai_messages.append({"role": "system", "content": system_text})

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            openai_messages.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts, tool_calls = [], []
            for block in content or []:
                btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if btype == "text":
                    text_parts.append(block.get("text") if isinstance(block, dict) else block.text)
                elif btype == "tool_use":
                    name = block.get("name") if isinstance(block, dict) else block.name
                    tool_input = block.get("input") if isinstance(block, dict) else block.input
                    tool_id = block.get("id") if isinstance(block, dict) else block.id
                    tool_calls.append({
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(tool_input or {})},
                    })
                elif btype == "thinking":
                    _warn_once("thinking_dropped", "Extended-thinking history is Anthropic-only and is dropped for the OpenAI-compatible provider")
                elif btype in _DROPPED_ASSISTANT_BLOCK_TYPES:
                    _warn_once(f"server_block_{btype}", f"Server-tool block '{btype}' has no OpenAI-compatible equivalent and was dropped from history")
            entry: Dict[str, Any] = {"role": "assistant", "content": "\n".join(t for t in text_parts if t) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            openai_messages.append(entry)
            continue

        # user (or other) role: text / tool_result / image blocks
        text_parts, image_parts, tool_messages = [], [], []
        for block in content or []:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.get("text") if isinstance(block, dict) else block.text)
            elif btype == "tool_result":
                tool_use_id = block.get("tool_use_id")
                result_text = _tool_result_text(block.get("content"))
                if block.get("is_error"):
                    result_text = f"[error] {result_text}"
                tool_messages.append({"role": "tool", "tool_call_id": tool_use_id, "content": result_text or "(empty result)"})
            elif btype == "image":
                img = _image_block_to_openai(block)
                if img:
                    image_parts.append(img)
            elif btype in ("document", "container_upload"):
                _warn_once("document_block", "Document/file attachments (Anthropic Files API) are not supported over an OpenAI-compatible endpoint and were dropped")
            # any 'cache_control' key on a block is simply ignored - no error

        # Anthropic requires tool_result blocks before any other content in
        # the same message; OpenAI wants each tool result as its own message.
        openai_messages.extend(tool_messages)
        if image_parts:
            parts = [{"type": "text", "text": t} for t in text_parts if t] + image_parts
            openai_messages.append({"role": "user", "content": parts})
        elif text_parts:
            openai_messages.append({"role": "user", "content": "\n".join(t for t in text_parts if t)})

    return openai_messages


_SKIPPED_TOOL_TYPES = {
    "memory_20250818": "the built-in Anthropic memory tool",
}
_SKIPPED_TOOL_PREFIXES = ("web_search", "web_fetch", "code_execution")


def anthropic_tools_to_openai(tools: Optional[List[dict]]) -> List[dict]:
    if not tools:
        return []
    openai_tools = []
    for tool in tools:
        ttype = tool.get("type")
        if ttype in _SKIPPED_TOOL_TYPES:
            _warn_once(f"tool_{ttype}", f"Tool '{tool.get('name', ttype)}' ({_SKIPPED_TOOL_TYPES[ttype]}) has no OpenAI-compatible equivalent and was not sent to the model")
            continue
        if ttype and ttype.startswith(_SKIPPED_TOOL_PREFIXES):
            _warn_once(f"tool_{ttype}", f"Server tool '{ttype}' has no OpenAI-compatible equivalent and was not sent to the model")
            continue
        name = tool.get("name")
        if not name:
            continue
        openai_tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return openai_tools


def _output_config_to_response_format(output_config: Optional[dict]) -> Optional[dict]:
    if not output_config:
        return None
    fmt = output_config.get("format") or {}
    if fmt.get("type") == "json_schema" and fmt.get("schema"):
        return {
            "type": "json_schema",
            "json_schema": {"name": "response", "strict": True, "schema": fmt["schema"]},
        }
    return None


# ---------------------------------------------------------------------------
# OpenAI response shape -> Anthropic response shape
# ---------------------------------------------------------------------------

_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "end_turn",
}


def _block_from_tool_call(tc) -> SimpleNamespace:
    try:
        parsed_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Could not parse tool call arguments as JSON: {tc.function.arguments!r}")
        parsed_input = {}
    return SimpleNamespace(type="tool_use", id=tc.id, name=tc.function.name, input=parsed_input)


def openai_response_to_anthropic(completion) -> SimpleNamespace:
    choice = completion.choices[0]
    msg = choice.message
    content = []
    if msg.content:
        content.append(SimpleNamespace(type="text", text=msg.content))
    for tc in (getattr(msg, "tool_calls", None) or []):
        content.append(_block_from_tool_call(tc))

    usage_obj = getattr(completion, "usage", None)
    usage = SimpleNamespace(
        input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )

    return SimpleNamespace(
        content=content,
        stop_reason=_FINISH_REASON_MAP.get(choice.finish_reason, "end_turn"),
        usage=usage,
        container=None,
        model=getattr(completion, "model", None),
    )


# ---------------------------------------------------------------------------
# The adapter surface: mimics AsyncAnthropic's attribute shape
# ---------------------------------------------------------------------------

class _FinalMessageStream:
    """Mimics the async-context-manager object `anthropic.beta.messages.stream()`
    yields, closely enough for `async with ... as s: await s.get_final_message()`
    to work. Not a real token stream - it issues one non-streaming request and
    hands back the full response, which is all existing call sites consume."""

    def __init__(self, client: AsyncOpenAI, request: dict):
        self._client = client
        self._request = request

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_final_message(self):
        completion = await self._client.chat.completions.create(**self._request)
        return openai_response_to_anthropic(completion)


class _MessagesNamespace:
    """Backs both `client.messages` and `client.beta.messages`."""

    def __init__(self, client: AsyncOpenAI, default_model: Optional[str], max_output_tokens: Optional[int]):
        self._client = client
        self._default_model = default_model
        self._max_output_tokens = max_output_tokens
        self.batches = _UnsupportedBatchesAPI()

    def _build_request(self, **api_params) -> dict:
        model = api_params.get("model") or self._default_model
        if not model:
            raise ValueError(
                "No model specified. Set 'model' in bots/<bot>.yaml, or set "
                "OPENAI_MODEL in .env to apply a default for every request."
            )
        messages = anthropic_messages_to_openai(api_params.get("system"), api_params.get("messages", []))
        tools = anthropic_tools_to_openai(api_params.get("tools"))

        if api_params.get("thinking"):
            _warn_once("thinking_param", "config.api.thinking is ignored on an OpenAI-compatible endpoint - no equivalent")
        if (api_params.get("output_config") or {}).get("effort"):
            _warn_once("effort_param", "config.api.effort is ignored on an OpenAI-compatible endpoint - no equivalent")
        if api_params.get("container"):
            _warn_once("container_param", "The skills/code-execution container is ignored on an OpenAI-compatible endpoint")

        max_tokens = api_params.get("max_tokens")
        if self._max_output_tokens:
            max_tokens = min(max_tokens, self._max_output_tokens) if max_tokens else self._max_output_tokens

        request: Dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            request["tools"] = tools
        if max_tokens:
            request["max_tokens"] = max_tokens

        response_format = _output_config_to_response_format(api_params.get("output_config"))
        if response_format:
            request["response_format"] = response_format

        return request

    def stream(self, **api_params):
        request = self._build_request(**api_params)
        return _FinalMessageStream(self._client, request)

    async def create(self, **api_params):
        request = self._build_request(**api_params)
        completion = await self._client.chat.completions.create(**request)
        return openai_response_to_anthropic(completion)


class _UnsupportedFilesAPI:
    _MSG = "The Files API has no OpenAI-compatible equivalent (attachments/container-output delivery are disabled on this provider)"

    async def upload(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def delete(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def retrieve_metadata(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def download(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)


class _UnsupportedSkillsAPI:
    _MSG = "Skills / code execution require Anthropic's server-side container and have no OpenAI-compatible equivalent"

    async def create(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def list(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)
        yield  # pragma: no cover - unreachable; makes this an async generator


class _UnsupportedBatchesAPI:
    _MSG = "The Batches API has no OpenAI-compatible equivalent - weekly reconsolidation and induction require LLM_PROVIDER=anthropic"

    async def create(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def retrieve(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)

    async def results(self, *a, **kw):
        raise FeatureNotSupportedError(self._MSG)


class _Beta:
    def __init__(self, messages: _MessagesNamespace):
        self.messages = messages
        self.files = _UnsupportedFilesAPI()
        self.skills = _UnsupportedSkillsAPI()


class OpenAICompatibleClient:
    """Drop-in stand-in for `anthropic.AsyncAnthropic`, backed by any
    OpenAI-compatible /chat/completions endpoint. See module docstring."""

    def __init__(self, api_key: Optional[str], base_url: str,
                 default_model: Optional[str] = None,
                 max_output_tokens: Optional[int] = None):
        self._client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url)
        self.messages = _MessagesNamespace(self._client, default_model, max_output_tokens)
        self.beta = _Beta(self.messages)
