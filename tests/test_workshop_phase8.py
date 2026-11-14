"""Phase 8 regression: workshop config, scopes, tools, jobs, panel, gate."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import aiosqlite
import pytest

from core.config import BotConfig
from core.vaults import VaultEnforcer
from core.workshop.backends.fake import FakeBackend
from core.workshop.gate import off_reason, open_workshop
from core.workshop.jobs import DONE, RUNNING, JobStore, _record
from core.workshop.panel import Panel
from core.workshop.scopes import Scope, setting_for
from core.workshop.service import Workshop, WorkspaceFiles
from core.workshop.state import WorkshopState
from core.workshop.watcher import JobWatcher
from tools.bash_tool import run_bash
from tools.editor_tool import run_editor


def make_config(**workshop):
    data = {
        "bot_id": "alpha", "name": "Alpha",
        "workshop": {"enabled": True, "default_setting": "container", **workshop},
    }
    return BotConfig._from_dict(data)


@pytest.fixture
async def workshop(tmp_path):
    config = make_config()
    db = await aiosqlite.connect(str(tmp_path / "messages.db"))
    db.row_factory = aiosqlite.Row
    jobs = JobStore(db, "alpha")
    await jobs.create_schema()
    (tmp_path / "root").mkdir()
    ws = Workshop(
        config=config, bot_id="alpha", data_root=tmp_path / "root",
        backend=FakeBackend(), jobs=jobs, vaults=VaultEnforcer([]),
        state=WorkshopState(tmp_path / "workshop" / "state.json"))
    await ws.start()
    await ws._template_task          # the fake template builds at once
    try:
        yield ws
    finally:
        await ws.close()
        await db.close()


# --- config, scopes, gate ---------------------------------------------------

def test_workshop_config_parses_yaml_booleans_and_lowercases_hosts():
    config = make_config(default_setting=False, scopes={"123456789012345678": "off"},
                         allowlist=["Example.COM."])
    w = config.workshop
    assert w.default_setting == "off"
    assert w.scopes == {"123456789012345678": "off"}
    assert w.allowlist == ["example.com"]
    assert config._validate_workshop() == []


def test_workshop_config_rejects_bad_values():
    bad = make_config(default_setting="sometimes")
    assert any("workshop.default_setting" in e for e in bad._validate_workshop())

    bad = make_config(scopes={"not-an-id": "container"})
    assert any("not a Discord id" in e for e in bad._validate_workshop())

    bad = make_config(allowlist=["https://example.com/x"])
    assert any("not a host name" in e for e in bad._validate_workshop())


def test_scope_resolution_honours_vaults_threads_and_dms():
    vaults = VaultEnforcer(["111"])
    vaults.dm_partner_resolver = lambda cid: "42" if cid == "dm1" else None

    assert vaults.resolve_scope("9", "111") == Scope("vault", "111")
    assert vaults.resolve_scope("9", "222") == Scope("server", "9")
    assert vaults.resolve_scope("9", "333", is_thread=True) is None
    assert vaults.resolve_scope("9", "333", parent_id="111", is_thread=True) == Scope("vault", "111")
    assert vaults.resolve_scope(None, "dm1") == Scope("dm", "42")
    assert vaults.resolve_scope(None, "dm2") == Scope("dm-channel", "dm2")


def test_setting_for_most_specific_id_wins():
    config = make_config(default_setting="container", scopes={
        "9": "off", "222": "container", "333": "off"})
    scope = Scope("server", "9")
    assert setting_for(scope, config, server_id="9", channel_id="222") == "container"
    assert setting_for(scope, config, server_id="9", channel_id="444") == "off"
    assert setting_for(None, config) == "off"          # unresolved thread
    config.workshop.enabled = False
    assert setting_for(scope, config, server_id="9") == "off"


async def test_start_gate_off_is_recorded_not_blocked(tmp_path):
    config = make_config(default_setting="off")
    assert off_reason(config)
    result = await open_workshop(
        config, "alpha", root=tmp_path, vaults=VaultEnforcer([]), db=None,
        skills_dir=tmp_path / "skills")
    assert result is None
    status = json.loads((tmp_path / "persistence" / "workshop" / "alpha" /
                         "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "off"
    assert "no scope" in status["reason"]


# --- tools ------------------------------------------------------------------

async def test_bash_runs_in_the_scope_and_records_a_job(workshop):
    text = await run_bash(workshop, {"command": "true"},
                          server_id="9", channel_id="222")
    assert "exit code 0" in text
    jobs = await _all_jobs(workshop)
    assert len(jobs) == 1
    assert jobs[0].kind == "shell"
    assert jobs[0].state == DONE
    assert jobs[0].home_channel_id == "222"


async def test_bash_refuses_a_scope_that_is_off(workshop):
    workshop.config.workshop.scopes["222"] = "off"
    text = await run_bash(workshop, {"command": "true"},
                          server_id="9", channel_id="222")
    assert "isn't available" in text
    assert await _all_jobs(workshop) == []


async def test_editor_round_trip_and_workspace_files(workshop):
    created = await run_editor(
        workshop, {"command": "create", "path": "/workspace/notes.md",
                   "file_text": "hello\n"},
        server_id="9", channel_id="222")
    assert "Created" in created

    viewed = await run_editor(workshop, {"command": "view", "path": "/workspace/notes.md"},
                              server_id="9", channel_id="222")
    assert "hello" in viewed

    files = WorkspaceFiles(workshop, Scope("server", "9"))
    assert await files.read("/workspace/notes.md") == b"hello\n"
    with pytest.raises(Exception):
        WorkspaceFiles.jail("/etc/passwd")


# --- background jobs and the watcher ---------------------------------------

async def test_background_job_finishes_and_the_watcher_delivers_a_note(workshop):
    config = workshop.config
    noted, woken = [], []

    class Notes:
        async def write(self, channel_id, note):
            noted.append((channel_id, note))
            return True

    watcher = JobWatcher(workshop, Notes(), wake=_wake(woken), config=config)
    await run_bash(workshop, {"command": "true", "background": True},
                   server_id="9", channel_id="222")
    job = (await _all_jobs(workshop))[-1]
    assert job.state == RUNNING

    watcher.follow(job)
    for _ in range(50):
        if noted:
            break
        await asyncio.sleep(0.02)

    finished = await workshop.jobs.get(job.id)
    assert finished.state == DONE
    assert finished.notified is True
    assert noted and noted[0][0] == "222"
    assert "Your background job" in noted[0][1]
    assert woken == ["222"]
    await watcher.close()


def _wake(woken):
    async def go(channel_id):
        woken.append(channel_id)
    return go


async def _all_jobs(workshop):
    cursor = await workshop.jobs.db.execute("SELECT * FROM jobs ORDER BY started_at")
    rows = await cursor.fetchall()
    return [_record(row) for row in rows]


# --- panel ------------------------------------------------------------------

async def test_panel_applies_host_requests_and_publishes(tmp_path, workshop):
    folder = tmp_path / "panel"
    requests = folder / "requests"
    requests.mkdir(parents=True)
    panel = Panel(workshop, folder)

    (requests / "aaaaaaaaaaaa.json").write_text(json.dumps(
        {"action": "allow_host", "scope": "server:9", "host": "Example.com"}),
        encoding="utf-8")
    assert await panel.apply_requests() is True
    assert "example.com" in workshop.state.approved_hosts("server:9")
    assert not list(requests.iterdir())

    await panel.publish()
    snapshot = json.loads((folder / "panel.json").read_text(encoding="utf-8"))
    assert snapshot["requests"][0]["ok"] is True
    assert "example.com allowed" in snapshot["requests"][0]["outcome"]
    assert snapshot["proxy_port"] == workshop.proxy_port


async def test_panel_rejects_bad_scope_and_unknown_action(tmp_path, workshop):
    folder = tmp_path / "panel"
    requests = folder / "requests"
    requests.mkdir(parents=True)
    panel = Panel(workshop, folder)
    for rid, body in (("bbbbbbbbbbbb", {"action": "allow_host", "scope": "nope", "host": "x.com"}),
                      ("cccccccccccc", {"action": "dance", "scope": "server:9"})):
        (requests / f"{rid}.json").write_text(json.dumps(body), encoding="utf-8")
    await panel.apply_requests()
    outcomes = {o["id"]: o for o in panel.outcomes}
    assert outcomes["bbbbbbbbbbbb"]["ok"] is False
    assert outcomes["cccccccccccc"]["ok"] is False


async def test_fetched_file_is_copied_into_the_workshop_inbox(workshop):
    from core.workshop.workers import copy_to_inbox

    class Attachments:
        async def local_bytes(self, attachment_id):
            return b"file bytes"

    note = await copy_to_inbox(
        workshop, Attachments(),
        {"attachment_id": "a1", "filename": "my file.txt"}, Scope("server", "9"))
    assert "/workspace/inbox/my_file.txt" in note
    assert await WorkspaceFiles(workshop, Scope("server", "9")).read(
        "/workspace/inbox/my_file.txt") == b"file bytes"


# --- supervisor routes ------------------------------------------------------

async def test_supervisor_workshop_routes_read_and_queue(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from supervisor.api import build_app
    from supervisor.paths import SupervisorRoot
    from supervisor.process_manager import ProcessManager

    root = SupervisorRoot(tmp_path)
    root.seed()
    (root.bots_dir() / "alpha.yaml").write_text(
        "bot_id: alpha\nname: Alpha\nworkshop:\n  default_setting: container\n",
        encoding="utf-8")
    client = TestClient(TestServer(build_app(root, ProcessManager(root))))
    await client.start_server()
    headers = {"X-DA-Token": root.api_token()}
    try:
        r = await client.get("/api/bots/alpha/workshop", headers=headers)
        assert r.status == 200
        view = await r.json()
        assert view["status"]["state"] == "unknown"
        assert view["settings"]["default_setting"] == "container"

        r = await client.post("/api/bots/alpha/workshop/requests", headers=headers, json={
            "action": "allow_host", "scope": "server:9", "host": "example.com"})
        assert r.status == 200
        queued = (await r.json())["queued"]
        assert len(queued) == 12
        request = json.loads((root.workshop_dir("alpha") / "requests" /
                              f"{queued}.json").read_text(encoding="utf-8"))
        assert request == {"action": "allow_host", "scope": "server:9", "host": "example.com"}

        r = await client.post("/api/bots/alpha/workshop/requests", headers=headers,
                              json={"action": "dance"})
        assert r.status == 400
        r = await client.post("/api/bots/alpha/workshop/requests", headers=headers,
                              json={"action": "wipe", "scope": "server:9"})
        assert r.status == 400
        r = await client.post("/api/bots/alpha/workshop/requests", headers=headers,
                              json={"action": "decide", "approval_id": "x", "allow": True})
        assert r.status == 200
        r = await client.get("/api/bots/alpha/workshop/workers/not-a-job", headers=headers)
        assert r.status == 400
    finally:
        await client.close()
