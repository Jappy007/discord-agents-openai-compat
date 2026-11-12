"""
Client-side web_search / web_fetch tools.

These are ordinary function tools: the model calls them, this module makes
the actual search/HTTP request, and the result goes back as a normal
tool_result. No provider-side server tools are involved.

Search backend: DuckDuckGo via the `ddgs` package (https://pypi.org/project/ddgs/).
No API key, no account, no card - it scrapes DuckDuckGo/Bing's public result
pages rather than calling an official API, so it's inherently less reliable
than a paid provider (result markup can change, or it can get rate-limited
under heavy use) - that trade-off is the price of "genuinely free, no key".
"""
import asyncio
import html as html_lib
import logging
import re
from typing import Optional

import httpx
from ddgs import DDGS
from ddgs.exceptions import DDGSException

logger = logging.getLogger(__name__)

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Returns up to a handful of "
        "results with titles, URLs, and short snippets. Follow up with "
        "web_fetch to read the full content of a promising result."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
        },
        "required": ["query"],
    },
}

WEB_FETCH_TOOL = {
    "name": "web_fetch",
    "description": (
        "Fetch the text content of a web page by URL - e.g. a result from "
        "web_search, or any URL mentioned in conversation. HTML pages are "
        "reduced to plain text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch (must start with http:// or https://)"},
        },
        "required": ["url"],
    },
}

_MAX_RESULTS = 8
_MAX_FETCH_CHARS = 8000
_USER_AGENT = "Mozilla/5.0 (compatible; DiscordAgentBot/1.0; +https://github.com/)"
_URL_RE = re.compile(r'https?://[^\s<>"\'\])}]+')


def urls_in_text(text: str) -> set:
    """Every http(s) URL a piece of text mentions, stripped of trailing
    punctuation. Provenance for web_fetch: only URLs the conversation (or a
    search result) actually brought up are fetchable."""
    if not text:
        return set()
    return {u.rstrip(".,;:!?") for u in _URL_RE.findall(str(text))}


def allowed_urls_from_messages(messages) -> set:
    """URLs from user messages only. A tool_result rides in a user-role
    message too, so those blocks are excluded: a URL the bot printed or
    read from a file must not become fetchable (0.15.0)."""
    allowed = set()
    for msg in messages or []:
        if msg.get("role") != "user" or msg.get("message_type") == "tool_result":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            allowed |= urls_in_text(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    allowed |= urls_in_text(block.get("text", ""))
    return allowed


def _ddg_search_sync(query: str) -> list:
    """Runs in a thread (see execute_web_search) - ddgs is a blocking library."""
    return DDGS().text(query, max_results=_MAX_RESULTS)


async def execute_web_search(query: str, api_key: Optional[str] = None) -> str:
    """`api_key` is accepted (and ignored) for interface compatibility with
    other search backends - DuckDuckGo needs none."""
    if not query or not query.strip():
        return "Error: query is required"

    try:
        results = await asyncio.to_thread(_ddg_search_sync, query)
    except DDGSException as e:
        logger.error(f"DuckDuckGo search failed for '{query}': {e}")
        return f"Error: search failed ({e})"
    except Exception as e:
        logger.error(f"DuckDuckGo search failed for '{query}': {e}", exc_info=True)
        return f"Error: search failed ({e})"

    if not results:
        return "No results found."

    lines = []
    for r in results[:_MAX_RESULTS]:
        title = r.get("title", "(no title)")
        url = r.get("href", "")
        snippet = r.get("body", "")
        lines.append(f"- {title}\n  {url}\n  {snippet}")
    return "\n".join(lines)


async def execute_web_fetch(url: str, allowed_urls: Optional[set] = None) -> str:
    if not url or not url.strip():
        return "Error: url is required"
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Error: url must start with http:// or https://"
    if allowed_urls is not None and url.rstrip(".,;:!?") not in allowed_urls:
        return (
            "Error: that URL wasn't mentioned in a message or returned by "
            "web_search - only those are fetchable."
        )

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                text = _html_to_text(resp.text)
            elif content_type.startswith("text/") or "json" in content_type:
                text = resp.text
            else:
                return f"Error: unsupported content type '{content_type}' for {url}"
    except httpx.HTTPStatusError as e:
        logger.error(f"web_fetch HTTP error for {url}: {e}")
        return f"Error: fetch failed ({e.response.status_code})"
    except Exception as e:
        logger.error(f"web_fetch failed for {url}: {e}", exc_info=True)
        return f"Error: fetch failed ({e})"

    if len(text) > _MAX_FETCH_CHARS:
        text = text[:_MAX_FETCH_CHARS] + "\n... [truncated]"
    return text.strip() or "(empty page)"


def _html_to_text(html_content: str) -> str:
    """Minimal, dependency-free HTML-to-text: strip script/style/comments and
    tags, unescape entities, collapse whitespace. Not a faithful readability
    extraction, but enough for a model to work with without adding a new
    HTML-parsing dependency (BeautifulSoup, etc)."""
    cleaned = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html_content)
    cleaned = re.sub(r"(?s)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()
