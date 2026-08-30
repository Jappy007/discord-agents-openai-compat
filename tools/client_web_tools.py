"""
Client-side web_search / web_fetch tools for LLM_PROVIDER=openai_compatible.

Anthropic's web_search / web_fetch (tools/web_search.py) are server-side
tools executed by Anthropic itself - there's no equivalent wire-protocol
feature for a generic OpenAI-compatible endpoint. These are ordinary
function tools instead: the model calls them, this module makes the actual
search/HTTP request, and the result goes back as a normal tool_result.

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


async def execute_web_fetch(url: str) -> str:
    if not url or not url.strip():
        return "Error: url is required"
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return "Error: url must start with http:// or https://"

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
