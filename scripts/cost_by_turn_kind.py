#!/usr/bin/env python3
"""What today's (or any window's) turns cost, by kind and model.

Token counts come from the `events` table MessageMemory writes; prices come
from the small catalog in core/internal_constants.py. Models missing from the
catalog are counted but reported as unpriced, so the total says how complete
it is.

Usage:
    python3 scripts/cost_by_turn_kind.py [data-root] [--bot alpha] [--days 7]
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.internal_constants import estimate_cost_usd  # noqa: E402


def _connect(path: Path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _payload(row):
    try:
        return json.loads(row[0]) or {}
    except (TypeError, json.JSONDecodeError):
        return {}


def bot_databases(root: Path, bots=None):
    """[(bot_id, messages.db)] for bots that have one.

    The fork stores per-bot databases as `persistence/<bot>_messages.db`.
    """
    found = []
    for bot in sorted((root / "bots").glob("*.yaml")):
        bot_id = bot.stem
        if bots and bot_id not in bots:
            continue
        db = root / "persistence" / f"{bot_id}_messages.db"
        if db.exists():
            found.append((bot_id, db))
    return found


def collect(databases, *, since=None):
    """Rows grouped by (bot, kind, model) with tokens, cost and completeness."""
    groups = {}
    for bot_id, path in databases:
        con = _connect(path)
        con.row_factory = sqlite3.Row
        try:
            sql = "SELECT kind, ts, payload FROM events"
            params = ()
            if since:
                sql += " WHERE ts >= ?"
                params = (since,)
            rows = con.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            con.close()

        for row in rows:
            payload = _payload((row["payload"],))
            tokens = payload.get("tokens") or {}
            if not any(tokens.values()):
                continue
            model = payload.get("model") or "(unknown)"
            key = (bot_id, row["kind"], model)
            g = groups.setdefault(key, {
                "bot": bot_id, "kind": row["kind"], "model": model,
                "tokens": {"uncached_in": 0, "cache_read": 0, "cache_write": 0, "out": 0},
                "cost_usd": 0.0, "turns": 0, "unpriced_turns": 0,
            })
            for k in g["tokens"]:
                g["tokens"][k] += tokens.get(k, 0) or 0
            cost = estimate_cost_usd(model, tokens)
            if cost is None:
                g["unpriced_turns"] += 1
            else:
                g["cost_usd"] += cost
            g["turns"] += 1
    return sorted(groups.values(), key=lambda g: (g["cost_usd"], g["tokens"]["out"]), reverse=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="data root (default: .)")
    parser.add_argument("--bot", action="append", help="limit to a bot id (repeatable)")
    parser.add_argument("--days", type=int, default=None,
                        help="only events this many days back (default: everything)")
    args = parser.parse_args(argv)

    since = None
    if args.days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()

    rows = collect(bot_databases(Path(args.root), set(args.bot or [])), since=since)
    if not rows:
        print("No priced or token-bearing turn events found.")
        return 0

    print(f"{'bot':<16} {'kind':<14} {'model':<28} {'turns':>6} {'in':>10} "
          f"{'cached':>10} {'out':>10} {'cost':>10}")
    total = 0.0
    unpriced = 0
    for g in rows:
        total += g["cost_usd"]
        unpriced += g["unpriced_turns"]
        print(f"{g['bot']:<16} {g['kind']:<14} {g['model']:<28} {g['turns']:>6} "
              f"{g['tokens']['uncached_in']:>10,} {g['tokens']['cache_read']:>10,} "
              f"{g['tokens']['out']:>10,} {('$' + format(g['cost_usd'], '.4f')):>10}")
    print(f"{'':<16} {'':<14} {'TOTAL':<28} {'':>6} {'':>10} {'':>10} {'':>10} "
          f"{('$' + format(total, '.4f')):>10}")
    if unpriced:
        print(f"Note: {unpriced} turn(s) used a model with no catalog price; the total is partial.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
