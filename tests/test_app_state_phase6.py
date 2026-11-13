"""Phase 6 regression: app update/dependency report on the dashboard API."""

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from supervisor.api import build_app
from supervisor.data import BotData
from supervisor.paths import SupervisorRoot
from supervisor.process_manager import ProcessManager


@pytest.fixture
async def daemon(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    pm = ProcessManager(root)
    app = build_app(root, pm)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield root, client
    finally:
        await client.close()


def test_app_state_is_read_from_persistence(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    state = {
        "framework": {"status": "skipped", "reason": "tracked files modified locally",
                      "files": ["core/app.py"]},
        "deps": {"status": "error", "reason": "pip exploded"},
    }
    root.app_state().write_text(json.dumps(state), encoding="utf-8")

    assert BotData(root).app_state() == state


async def test_supervisor_api_includes_the_app_report(daemon):
    root, client = daemon
    root.app_state().write_text(json.dumps({"deps": {"status": "current"}}),
                                encoding="utf-8")

    r = await client.get("/api/supervisor")
    assert r.status == 200
    body = await r.json()
    assert body["app"] == {"deps": {"status": "current"}}


async def test_missing_app_state_is_an_empty_report(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    assert BotData(root).app_state() == {}
