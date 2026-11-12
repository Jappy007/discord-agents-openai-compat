"""Phase 1 regression: dashboard auth guard + asset cache-busting."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from supervisor.api import build_app
from supervisor.paths import SupervisorRoot
from supervisor.process_manager import ProcessManager


def _load_supervisor_module():
    path = Path(__file__).resolve().parents[1] / "supervisor.py"
    spec = importlib.util.spec_from_file_location("supervisor_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def daemon(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    pm = ProcessManager(root)
    app = build_app(root, pm)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield root, app, client
    finally:
        await client.close()


async def test_api_requires_token_except_launcher_health(daemon):
    root, app, client = daemon
    r = await client.get("/api/bots")
    assert r.status == 401
    r = await client.get("/api/supervisor")
    assert r.status == 200
    r = await client.get("/api/bots",
                         headers={"X-DA-Token": root.api_token()})
    assert r.status == 200
    assert json.loads(await r.text()) == []


async def test_guard_rejects_foreign_host_and_origin(daemon):
    root, app, client = daemon
    r = await client.get("/api/bots", headers={
        "X-DA-Token": root.api_token(), "Host": "evil.example"})
    assert r.status == 403
    r = await client.post("/api/supervisor/shutdown", headers={
        "X-DA-Token": root.api_token(),
        "Origin": "http://evil.example"})
    assert r.status == 403


async def test_framing_denied_on_every_response(daemon):
    root, app, client = daemon
    r = await client.get("/api/supervisor")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_token_file_is_private_and_stable(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    token = root.api_token()
    assert token and root.api_token() == token
    if os.name == "posix":
        assert (root.api_token_file().stat().st_mode & 0o777) == 0o600


def test_render_html_busts_images_and_fonts(tmp_path):
    mod = _load_supervisor_module()
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("x", encoding="utf-8")
    (assets / "brand.woff2").write_text("x", encoding="utf-8")
    page = tmp_path / "index.html"
    page.write_text(
        '<head><link rel="stylesheet" href="assets/app.js?v=old">'
        '<img src="assets/logo.png">'
        '<style>url(assets/brand.woff2)</style></head>',
        encoding="utf-8")

    html = mod._render_html(page, assets, "secret-token")
    assert 'assets/app.js?v=' in html
    assert "?v=old" not in html
    assert 'assets/logo.png?v=' in html
    assert 'assets/brand.woff2?v=' in html      # not truncated to .woff
    assert '<meta name="da-token" content="secret-token">' in html
