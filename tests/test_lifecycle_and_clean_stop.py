"""Phase 5 regression: boot-once, resume floors, clean supervised stop."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.discord_client import DiscordClient
from supervisor.paths import SupervisorRoot
from supervisor.process_manager import ProcessManager


class _TestClient(DiscordClient):
    user = SimpleNamespace(name="bot", id=1)
    guilds = []


def _bare_client():
    c = object.__new__(_TestClient)
    c.user = SimpleNamespace(name="bot", id=1)
    c.guilds = []
    c.config = SimpleNamespace(discord=SimpleNamespace(
        backfill_enabled=True, backfill_days=30))
    c._booted = False
    c._resume_floor = {"c1": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    c.closed = 0

    async def close():
        c.closed += 1

    c.close = close
    return c


async def test_on_ready_boots_once_and_only_catches_up_on_reconnect():
    c = _bare_client()
    calls = []

    async def boot(floor):
        calls.append(("boot", floor))

    async def sweep():
        calls.append(("sweep",))

    c._boot = boot
    c._sweep_channel_names = sweep
    c._catch_up = lambda floor: calls.append(("catch_up", floor))

    floor = c._resume_floor
    await c.on_ready()
    assert calls == [("boot", floor)]
    assert c._booted and c._resume_floor is None

    await c.on_ready()
    assert calls[1:] == [("catch_up", None), ("sweep",)]


async def test_boot_failure_closes_so_the_supervisor_restarts():
    c = _bare_client()

    async def boot(floor):
        raise RuntimeError("boom")

    c._boot = boot
    await c.on_ready()
    assert c.closed == 1


async def test_disconnect_takes_one_floor_and_resume_clears_it():
    c = _bare_client()
    c._resume_floor = None
    taken = []

    async def newest():
        taken.append(1)
        return {"c1": datetime(2026, 1, 2, tzinfo=timezone.utc)}

    c.message_memory = SimpleNamespace(newest_message_times=newest)

    await c.on_disconnect()
    await c.on_disconnect()          # one floor per outage
    assert len(taken) == 1 and c._resume_floor

    await c.on_resumed()
    assert c._resume_floor is None
    await c.on_disconnect()          # a later outage takes a fresh floor
    assert len(taken) == 2


class _FakeStdin:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self):
        self.returncode = None
        self.stdin = _FakeStdin()
        self.killed = False
        self._waiters = []

    async def wait(self):
        if self.returncode is not None:
            return self.returncode
        future = asyncio.get_event_loop().create_future()
        self._waiters.append(future)
        await future
        return self.returncode

    def finish(self):
        self.returncode = 0
        for f in self._waiters:
            if not f.done():
                f.set_result(self.returncode)

    def kill(self):
        self.killed = True
        self.finish()


@pytest.fixture
def manager(tmp_path):
    root = SupervisorRoot(tmp_path)
    root.seed()
    return ProcessManager(root)


async def test_stop_closes_stdin_for_a_clean_bot_shutdown(manager):
    proc = _FakeProc()
    manager._procs["alpha"] = proc
    manager._desired = ["alpha"]

    task = asyncio.create_task(manager.stop("alpha"))
    await asyncio.sleep(0.01)          # let it close stdin and await wait()
    assert proc.stdin.closed
    proc.finish()
    await task

    assert "alpha" not in manager._procs
    assert "alpha" not in manager._desired       # an explicit stop is intent


async def test_shutdown_stops_bots_concurrently_without_clearing_desired(manager):
    a, b = _FakeProc(), _FakeProc()
    manager._procs = {"alpha": a, "beta": b}
    manager._desired = ["alpha", "beta"]

    task = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0.01)
    # both got the clean-stop signal before either exited
    assert a.stdin.closed and b.stdin.closed
    a.finish()
    b.finish()
    await task

    assert manager._procs == {}
    assert sorted(manager._desired) == ["alpha", "beta"]


async def test_stop_kills_a_bot_that_ignores_stdin(manager, monkeypatch):
    import supervisor.process_manager as pm_module
    monkeypatch.setattr(pm_module, "STOP_TIMEOUT_SECONDS", 0.01)

    proc = _FakeProc()
    manager._procs["alpha"] = proc

    await manager.stop("alpha")
    assert proc.killed
