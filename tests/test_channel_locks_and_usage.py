"""Phase 3 regression: channel locks, turn usage totals, send guard."""

import asyncio
import types

from core.channel_locks import ChannelLocks
from core.reactive_engine import ToolLoopResult, _accumulate_usage


async def test_channel_locks_are_per_channel_and_report_busy():
    locks = ChannelLocks()
    assert locks.lock("a") is locks.lock("a")
    assert locks.lock("a") is not locks.lock("b")
    assert not locks.busy("a")
    async with locks.lock("a"):
        assert locks.busy("a")
        assert not locks.busy("b")
    assert not locks.busy("a")


async def test_different_channels_run_side_by_side():
    locks = ChannelLocks()
    order = []

    async def turn(name, delay):
        async with locks.lock(name):
            order.append(f"{name}-start")
            await asyncio.sleep(delay)
            order.append(f"{name}-end")

    await asyncio.gather(turn("a", 0.05), turn("b", 0.01))
    # b finished while a was still running
    assert order.index("b-end") < order.index("a-end")


async def test_same_channel_serializes():
    locks = ChannelLocks()
    order = []

    async def turn(name):
        async with locks.lock(name):
            order.append(f"start-{len(order)}")
            await asyncio.sleep(0.01)
            order.append(f"end-{len(order)}")

    await asyncio.gather(turn("a"), turn("a"))
    assert order[0].startswith("start") and order[1].startswith("end")
    assert order[2].startswith("start") and order[3].startswith("end")


def test_turn_usage_sums_every_model_call():
    first = types.SimpleNamespace(input_tokens=10, output_tokens=2,
                                  cache_read_input_tokens=3,
                                  cache_creation_input_tokens=1)
    second = types.SimpleNamespace(input_tokens=20, output_tokens=5,
                                   cache_read_input_tokens=0,
                                   cache_creation_input_tokens=2)
    total = _accumulate_usage(_accumulate_usage(None, first), second)
    assert (total.input_tokens, total.output_tokens) == (30, 7)
    assert total.cache_read_input_tokens == 3
    assert total.cache_creation_input_tokens == 3
    assert _accumulate_usage(total, None) is total


def test_send_guard_fields_default_off():
    r = ToolLoopResult()
    assert not r.ended_on_send and r.dropped_text_chars == 0
    r.sent_texts.append("hi")
    assert r.sent_texts == ["hi"]
