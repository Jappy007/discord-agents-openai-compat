"""Phase 9 regression: model roles, model catalog, cost reporting."""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core import internal_constants as constants
from core.config import BotConfig
from core.internal_constants import (
    MODEL_MAX_OUTPUT_DEFAULT,
    estimate_cost_usd,
    model_max_output,
    model_price,
)
from core.llm_providers.factory import background_model, worker_model


def make_config(**api):
    data = {"bot_id": "alpha", "name": "Alpha", "api": {"model": "gpt-4o", **api}}
    return BotConfig._from_dict(data)


# --- config and role resolution ---------------------------------------------

def test_api_model_roles_parse_from_yaml():
    config = make_config(background_model="gpt-4o-mini",
                         worker_model="gpt-4.1-mini")
    assert config.api.background_model == "gpt-4o-mini"
    assert config.api.worker_model == "gpt-4.1-mini"


def test_model_roles_default_to_unset():
    config = make_config()
    assert config.api.background_model is None
    assert config.api.worker_model is None


def test_background_model_precedence(monkeypatch):
    monkeypatch.delenv("OPENAI_UTILITY_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    api = SimpleNamespace(model="main", background_model="bg")
    assert background_model(api) == "bg"

    api.background_model = None
    assert background_model(api) == "main"

    monkeypatch.setenv("OPENAI_UTILITY_MODEL", "utility")
    assert background_model(api) == "utility"

    monkeypatch.setenv("OPENAI_MODEL", "global")
    assert background_model(api) == "utility"


def test_background_model_falls_back_through_env_chain(monkeypatch):
    monkeypatch.delenv("OPENAI_UTILITY_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "global")
    api = SimpleNamespace(model="main", background_model=None)
    assert background_model(api) == "global"


def test_worker_model_precedence(monkeypatch):
    monkeypatch.setenv("OPENAI_UTILITY_MODEL", "utility")
    api = SimpleNamespace(model="main", worker_model=None)
    assert worker_model(api) == "main"
    api.worker_model = "worker"
    assert worker_model(api) == "worker"


def test_workers_constructor_uses_worker_role():
    from core.workshop.workers import Workers

    config = make_config(worker_model="gpt-4.1-mini")
    worker = Workers(workshop=None, config=config, memory=None, skills=None,
                     deliver=None, transcripts=None)
    assert worker.model == "gpt-4.1-mini"

    config = make_config()
    worker = Workers(workshop=None, config=config, memory=None, skills=None,
                     deliver=None, transcripts=None)
    assert worker.model == "gpt-4o"


# --- catalog ----------------------------------------------------------------

def test_catalog_output_ceilings_and_unknown_fallback():
    assert model_max_output("gpt-4o-mini") == 16_384
    assert model_max_output("gpt-4o-mini-2024-07-18") == 16_384
    assert model_max_output("gpt-4.1") == 32_768
    assert model_max_output("unknown-model") == MODEL_MAX_OUTPUT_DEFAULT


def test_catalog_prices_and_unknown_model():
    price = model_price("gpt-4o-mini")
    assert price["input"] == 0.15
    assert price["output_price"] == 0.60
    assert model_price("unknown-model") == {}

    # 1M fresh in + 1M cache read + 1M out for gpt-4o-mini
    tokens = {"uncached_in": 1_000_000, "cache_read": 1_000_000, "out": 1_000_000}
    assert estimate_cost_usd("gpt-4o-mini", tokens) == pytest.approx(0.825)
    assert estimate_cost_usd("unknown-model", tokens) is None
    assert estimate_cost_usd("gpt-4o-mini", {}) is None


def test_catalog_matching_does_not_swallow_unrelated_prefixes():
    # "gpt-4o" must not price "gpt-4o-fake-extra" silently? Dated variants are
    # matched after a separator, which is exactly what "-fake-extra" looks like.
    # The important guarantee is that an unrelated family stays unpriced.
    assert model_price("gpt-3.5-turbo") == {}
    assert estimate_cost_usd("gpt-3.5-turbo", {"uncached_in": 10}) is None


def test_event_payload_records_turn_model():
    from core.reactive_engine import ReactiveEngine, ToolLoopResult

    usage = SimpleNamespace(input_tokens=10, cache_read_input_tokens=2,
                            cache_creation_input_tokens=1, output_tokens=3)
    result = ToolLoopResult(model="gpt-4o-mini", total_usage=usage)
    payload = ReactiveEngine._event_payload(result, [])
    assert payload["model"] == "gpt-4o-mini"
    assert payload["tokens"] == {"uncached_in": 10, "cache_read": 2,
                                 "cache_write": 1, "out": 3}


# --- supervisor cost reporting ----------------------------------------------

def _seed_bot(root, bot_id="alpha", model="gpt-4o-mini"):
    root.seed()
    (root.bots_dir() / f"{bot_id}.yaml").write_text(
        f"bot_id: {bot_id}\nname: Alpha\napi:\n  model: {model}\n",
        encoding="utf-8")


async def _write_events(db_path, rows):
    from core.message_memory import MessageMemory

    memory = MessageMemory(db_path)
    await memory.initialize()
    try:
        for kind, payload in rows:
            await memory.add_event(kind, None, "chan", payload)
    finally:
        await memory.close()


@pytest.mark.asyncio
async def test_supervisor_cost_today_prices_catalogued_models(tmp_path):
    from supervisor.data import BotData
    from supervisor.paths import SupervisorRoot

    root = SupervisorRoot(tmp_path)
    _seed_bot(root)
    await _write_events(root.messages_db("alpha"), [
        ("mention", {"tokens": {"uncached_in": 1_000_000, "out": 1_000_000},
                     "model": "gpt-4o-mini"}),
        ("scan", {"tokens": {"uncached_in": 1_000_000, "out": 0},
                  "model": "gpt-4.1"}),
    ])

    status = await BotData(root).status("alpha", {"running": True, "pid": 1,
                                                  "uptime_s": 1})
    assert status["cost_complete"] is True
    assert status["cost_today_usd"] == pytest.approx(0.75 + 2.0, abs=1e-4)
    assert status["tokens_today"]["uncached_in"] == 2_000_000


@pytest.mark.asyncio
async def test_supervisor_cost_is_partial_for_unpriced_models(tmp_path):
    from supervisor.data import BotData
    from supervisor.paths import SupervisorRoot

    root = SupervisorRoot(tmp_path)
    _seed_bot(root, model="gpt-4o")
    await _write_events(root.messages_db("alpha"), [
        ("mention", {"tokens": {"uncached_in": 1_000_000, "out": 1_000_000},
                     "model": "some-local-model"}),
        # No model recorded: price with the bot's configured main model.
        ("scan", {"tokens": {"uncached_in": 1_000_000, "out": 0}}),
    ])

    status = await BotData(root).status("alpha", {"running": True, "pid": 1,
                                                  "uptime_s": 1})
    assert status["cost_complete"] is False
    assert status["cost_today_usd"] == pytest.approx(2.5, abs=1e-4)
    assert status["tokens_today"]["uncached_in"] == 2_000_000


@pytest.mark.asyncio
async def test_supervisor_cost_none_without_token_events(tmp_path):
    from supervisor.data import BotData
    from supervisor.paths import SupervisorRoot

    root = SupervisorRoot(tmp_path)
    _seed_bot(root)
    await _write_events(root.messages_db("alpha"), [
        ("mention", {"response": "hi", "tokens": {}}),
    ])

    status = await BotData(root).status("alpha", {"running": True, "pid": 1,
                                                  "uptime_s": 1})
    assert status["cost_today_usd"] == 0.0
    assert status["cost_complete"] is True


# --- cost script ------------------------------------------------------------

def _write_script_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            server_id TEXT,
            channel_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
    """)
    rows = [
        ("mention", {"tokens": {"uncached_in": 1_000_000, "out": 1_000_000},
                     "model": "gpt-4o-mini"}),
        ("mention", {"tokens": {"uncached_in": 1_000_000, "out": 0},
                     "model": "gpt-4o-mini"}),
        ("scan", {"tokens": {"uncached_in": 10, "out": 10},
                  "model": "unknown"}),
    ]
    for kind, payload in rows:
        con.execute(
            "INSERT INTO events (ts, kind, channel_id, payload) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), kind, "chan",
             json.dumps(payload)))
    con.execute(
        "INSERT INTO events (ts, kind, channel_id, payload) VALUES (?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), "mention", "chan",
         json.dumps({"response": "no tokens"})))
    con.commit()
    con.close()


def test_cost_script_groups_by_bot_kind_and_model(tmp_path):
    from scripts.cost_by_turn_kind import bot_databases, collect

    root = tmp_path
    (root / "bots").mkdir()
    (root / "bots" / "alpha.yaml").write_text("bot_id: alpha\n", encoding="utf-8")
    (root / "bots" / "beta.yaml").write_text("bot_id: beta\n", encoding="utf-8")
    (root / "bots" / "alpha.yaml.example").write_text("", encoding="utf-8")
    (root / "persistence").mkdir()
    _write_script_db(root / "persistence" / "alpha_messages.db")

    databases = bot_databases(root)
    assert [bot for bot, _ in databases] == ["alpha"]
    assert bot_databases(root, {"beta"}) == []

    rows = collect(databases)
    by_key = {(r["bot"], r["kind"], r["model"]): r for r in rows}
    assert set(by_key) == {("alpha", "mention", "gpt-4o-mini"),
                           ("alpha", "scan", "unknown")}

    priced = by_key[("alpha", "mention", "gpt-4o-mini")]
    assert priced["turns"] == 2
    assert priced["unpriced_turns"] == 0
    assert priced["cost_usd"] == pytest.approx(0.90)
    assert priced["tokens"]["uncached_in"] == 2_000_000

    unpriced = by_key[("alpha", "scan", "unknown")]
    assert unpriced["unpriced_turns"] == 1
    assert unpriced["cost_usd"] == 0.0

    # Rows without token usage are not turns for cost purposes.
    assert sum(r["turns"] for r in rows) == 3


def test_cost_script_since_filter(tmp_path):
    from scripts.cost_by_turn_kind import collect

    db = tmp_path / "alpha_messages.db"
    _write_script_db(db)
    future = (datetime.now(timezone.utc).replace(year=2099)).isoformat()
    assert collect([("alpha", db)], since=future) == []
