"""
Client-side web_search / web_fetch tools for LLM_PROVIDER=openai_compatible.

Anthropic's web_search / web_fetch (tools/web_search.py) are server-side
tools executed by Anthropic itself - there's no equivalent wire-protocol
feature for a generic OpenAI-compatible endpoint. These are ordinary
function tools instead: the model calls them, this module makes the actual
HTTP request, and the result goes back as a normal tool_result.

Search backend: Brave Search API (https://api.search.brave.com/). Requires
BRAVE_SEARCH_API_KEY in .env - see .env.example.
"""
import html as html_lib
import logging
import re
from typing import Optional

import httpx

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


async def execute_web_search(query: str, api_key: Optional[str]) -> str:
    if not api_key:
        return "Error: web search isn't configured (missing BRAVE_SEARCH_API_KEY in .env)"
    if not query or not query.strip():
        return "Error: query is required"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": _MAX_RESULTS},
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Brave search HTTP error for '{query}': {e}")
        return f"Error: search failed ({e.response.status_code})"
    except Exception as e:
        logger.error(f"Brave search failed for '{query}': {e}", exc_info=True)
        return f"Error: search failed ({e})"

    results = ((data or {}).get("web") or {}).get("results") or []
    if not results:
        return "No results found."

    lines = []
    for r in results[:_MAX_RESULTS]:
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = re.sub(r"<[^>]+>", "", r.get("description", ""))  # Brave wraps snippet highlights in <strong>
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
