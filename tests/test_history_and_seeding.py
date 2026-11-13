"""Phase 4 regression: history windows, seeding, held copies, markers, caps."""

from datetime import datetime, timezone

import pytest

from core.conversation_state import ConversationState
from core.message_memory import MessageMemory
from core.reactive_engine import SILENT_FORMS


async def _insert(db, message_id, ts, *, channel="c1", content=None,
                  is_bot=False, is_system=False, author_id="u1"):
    await db.execute(
        """
        INSERT INTO messages
            (message_id, channel_id, guild_id, author_id, author_name, content,
             timestamp, is_bot, is_system, has_attachments, mentions)
        VALUES (?, ?, 'g1', ?, ?, ?, ?, ?, ?, 0, '[]')
        """,
        (str(message_id), channel, author_id, f"author{author_id}",
         content if content is not None else f"m{message_id}", ts.isoformat(),
         is_bot, is_system),
    )
    await db.commit()


@pytest.fixture
async def memory(tmp_path):
    m = MessageMemory(tmp_path / "messages.db")
    await m.initialize()
    yield m
    await m.close()


async def test_get_recent_collapses_runs_of_lifecycle_markers(memory):
    db = memory._db
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # three consecutive markers, one real message, two more markers
    await _insert(db, 1, base, is_system=True)
    await _insert(db, 2, base.replace(second=1), is_system=True)
    await _insert(db, 3, base.replace(second=2), is_system=True)
    await _insert(db, 4, base.replace(second=3), content="hello")
    await _insert(db, 5, base.replace(second=4), is_system=True)
    await _insert(db, 6, base.replace(second=5), is_system=True)

    all_msgs = await memory.get_recent("c1", limit=20)
    assert [m.message_id for m in all_msgs] == ["1", "2", "3", "4", "5", "6"]

    collapsed = await memory.get_recent("c1", limit=20, collapse_markers=True)
    assert [m.message_id for m in collapsed] == ["3", "4", "6"]


async def test_get_recent_before_and_real_only(memory):
    db = memory._db
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await _insert(db, 10, base, is_system=True)
    await _insert(db, 20, base.replace(second=1), content="one")
    await _insert(db, 30, base.replace(second=2), content="two")
    await _insert(db, 40, base.replace(second=3), content="three")

    before = await memory.get_recent("c1", limit=20, before_message_id=40)
    assert [m.message_id for m in before] == ["10", "20", "30"]

    real = await memory.get_recent("c1", limit=20, real_only=True)
    assert [m.message_id for m in real] == ["20", "30", "40"]


async def test_newest_message_times_ignores_markers_and_returns_aware_utc(memory):
    db = memory._db
    real_ts = datetime(2026, 1, 1, 12, 0, 0)
    marker_ts = datetime(2026, 1, 2, 12, 0, 0)
    await _insert(db, 100, real_ts)
    # A marker is written at boot, and may carry a naive utcnow stamp
    await _insert(db, 101, marker_ts, is_system=True)

    times = await memory.newest_message_times()
    assert times["c1"] == real_ts.replace(tzinfo=timezone.utc)
    assert times["c1"].tzinfo is timezone.utc


def test_held_copy_updates_in_place_and_is_not_persisted():
    state = ConversationState("c1", max_messages=10)

    assert state.add_message("user", "seeded", discord_id="42") is True
    assert state.add_message("user", "live copy", attachment_ids=["a1"],
                             discord_id="42") is False

    assert len(state.messages) == 1
    assert state.messages[0]["content"] == "live copy"
    assert state.messages[0]["attachment_ids"] == ["a1"]
    assert "held" not in state.to_dict()


def test_message_cap_trims_a_quarter_below_the_cap():
    state = ConversationState("c1", max_messages=20)
    for i in range(24):
        state.add_message("user", f"m{i}", discord_id=str(i))

    removed = state.enforce_message_cap()
    remaining = [m for m in state.messages if m["message_type"].startswith("discord_")]

    assert removed == 9
    assert len(remaining) == 15  # 20 - max(1, 20 // 4)
    assert remaining[0]["content"] == "m9"
    assert remaining[-1]["content"] == "m23"


def test_silent_forms_only_match_whole_tags():
    for text in ("<silent/>", "<silence/>", "<silent>", "</silent>", " <SILENT/> "):
        assert SILENT_FORMS.fullmatch(text.strip())
    for text in ("<silent/> but here is more", "not silent", "<silent>text</silent>"):
        assert not SILENT_FORMS.fullmatch(text.strip())
