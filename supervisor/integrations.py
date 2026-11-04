"""
Integrations surface: MCP server management (mcp_servers.json + live health).
"""

import json
import logging
from typing import List

from .paths import SupervisorRoot

logger = logging.getLogger(__name__)


def load_mcp_servers(root: SupervisorRoot) -> List[dict]:
    path = root.mcp_servers_json()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("servers", [])
    except (json.JSONDecodeError, OSError):
        logger.error("Unreadable mcp_servers.json")
        return []


def save_mcp_servers(root: SupervisorRoot, servers: List[dict]) -> None:
    root.mcp_servers_json().write_text(
        json.dumps({"servers": servers}, indent=2, ensure_ascii=False),
        encoding="utf-8")
