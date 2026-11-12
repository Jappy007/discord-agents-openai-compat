"""Phase 2 regression: memory path gates, vault containment, fetch provenance."""

from pathlib import Path

from core.memory_tool_executor import MemoryToolExecutor
from core.repository_manager import RepositoryManager
from core.vaults import (
    VaultEnforcer, memory_path_problem, normalize_memory_path, path_parts,
)
from supervisor.process_manager import _spawns
from tools.client_web_tools import (
    allowed_urls_from_messages, execute_web_fetch, urls_in_text,
)


def test_normalize_and_problem_paths():
    assert normalize_memory_path(r"/memories\bot\a\..\b.md") == "/memories/bot/b.md"
    assert memory_path_problem("/memories/bot/notes.md") is None
    assert memory_path_problem("/memories/bot/142494~1.MD") is not None
    assert memory_path_problem("/memories/bot/x.md:secret") is not None
    assert memory_path_problem("/memories/bot/trailing.") is not None
    assert memory_path_problem("/memories/bot/trailing ") is not None
    assert path_parts("/Memories/Bot/Servers/1/X.md")[3] == "servers"


def test_vault_matching_is_case_insensitive_and_blocks_escapes():
    v = VaultEnforcer(["111", "222"])
    allowed, _ = v.check_memory_access(
        "/memories/bot/Servers/111/notes.md", "view", "999", "999")
    assert not allowed
    allowed, _ = v.check_memory_access(
        "/memories/bot/servers/111/channels/222/notes.md", "create", "111", "222")
    assert allowed
    # innermost vault wins: a vaulted channel's writes stay in its own tree
    allowed, reason = v.check_memory_access(
        "/memories/bot/servers/111/channels/333/notes.md", "create", "111", "222")
    assert not allowed and "outside this vault" in reason
    allowed, _ = v.check_memory_access(
        "/memories/bot/servers/111/channels/222/notes.md", "create", "111", "999")
    assert not allowed


def test_vault_still_allows_followups():
    v = VaultEnforcer(["222"])
    allowed, _ = v.check_memory_access(
        "/memories/bot/servers/222/followups.json", "create", "222", "222")
    assert allowed


def test_executor_normalizes_before_gate_and_accepts_aliases(tmp_path):
    v = VaultEnforcer(["111"])
    ex = MemoryToolExecutor(tmp_path, "bot", vaults=v)

    # Backslash + traversal spelling must not slip past validation.
    out = ex.execute({"command": "create", "path": r"/memories\bot\..\other\x.md",
                      "file_text": "x"}, "111", "111")
    assert out.startswith("Error: Invalid path")

    # A path that names a vaulted server from outside is still refused even
    # when spelled with mixed case and backslashes.
    out = ex.execute({"command": "view", "path": r"/memories\bot\Servers\111\notes.md"},
                     "999", "999")
    assert "Access denied" in out

    out = ex.execute({"command": "create",
                      "path": "/memories/bot/servers/111/channels/111/notes.md",
                      "file_text": "line1\nline2\n"}, "111", "111")
    assert out.startswith("Successfully")
    out = ex.execute({"command": "insert",
                      "path": "/memories/bot/servers/111/channels/111/notes.md",
                      "insert_line": 1, "insert_text": "inserted"}, "111", "111")
    assert out.startswith("Successfully")
    assert "inserted" in (tmp_path / "bot" / "servers/111/channels/111/notes.md").read_text()


async def test_repository_refuses_dm_scope(tmp_path):
    repo = RepositoryManager.__new__(RepositoryManager)  # guard runs before state use
    repo.vaults = None
    out = await repo.execute({"action": "list"}, None, "dm")
    assert "no repository in DMs" in out


def test_fetch_provenance_helpers():
    assert urls_in_text("see https://example.com/a).") == {"https://example.com/a"}
    msgs = [
        {"role": "user", "message_type": "discord_user",
         "content": "look at https://good.example/x"},
        {"role": "user", "message_type": "tool_result",
         "content": [{"type": "tool_result", "content": "https://evil.example/y"}]},
        {"role": "assistant", "content": [{"type": "text",
                                            "text": "https://evil.example/z"}]},
    ]
    allowed = allowed_urls_from_messages(msgs)
    assert allowed == {"https://good.example/x"}


async def test_web_fetch_refuses_urls_from_tool_results_only():
    out = await execute_web_fetch("https://evil.example/steal", allowed_urls=set())
    assert out.startswith("Error:") and "wasn't mentioned" in out


def test_orphan_scan_matches_whole_bot_id_and_path(tmp_path):
    script = tmp_path / "bot_manager.py"
    assert _spawns(f'python "{script}" spawn alpha', script, "alpha")
    assert not _spawns(f'python "{script}" spawn alpha-2', script, "alpha")
    other = tmp_path / "other" / "bot_manager.py"
    assert not _spawns(f'python "{other}" spawn alpha', script, "alpha")
