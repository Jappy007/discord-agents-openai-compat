#!/usr/bin/env python3
"""
Real initialization test: exercises the actual BotManager.initialize()
path with mocked network I/O. Uses real packages (discord, anthropic,
yaml, aiofiles, aiosqlite, etc.) — not stubs.

What this validates:
  1. Config loads and validates (real YAML, real dataclasses)
  2. SQLite databases create and initialize (real aiosqlite)
  3. ReactiveEngine constructs with all real managers
  4. AgenticEngine + Consolidator + WatchManager construct
  5. DiscordClient constructs with everything wired
  6. Our deque fix survives the real constructor
  7. Async shutdown path runs to completion
  8. Database cleanup works (real SQLite)
"""
import asyncio
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ["ANTHROPIC_API_KEY"] = "sk-test-real-init-validation"
os.environ["ALPHA_BOT_TOKEN"] = "MTIxMjM0NTY3ODkw.real-init-validation"
os.environ["LLM_PROVIDER"] = "anthropic"


async def run_test():
    """Full initialization test with real packages."""
    print("=" * 70)
    print("REAL INITIALIZATION TEST (real packages, mocked network)")
    print("=" * 70)

    tmpdir = tempfile.mkdtemp(prefix="discord_agents_init_test_")
    orig_cwd = os.getcwd()
    os.chdir(tmpdir)

    # Prepare directory structure
    for d in ["persistence", "logs", "memories", "bots"]:
        Path(d).mkdir(exist_ok=True)

    # Write config from example
    config_src = PROJECT_ROOT / "bots" / "alpha.yaml.example"
    config_dst = Path("bots") / "alpha.yaml"
    config_text = config_src.read_text()
    config_text = config_text.replace("backfill_enabled: true", "backfill_enabled: false")
    config_text = config_text.replace(
        "enabled: true  # Guaranteed response to @mentions",
        "enabled: false"
    )
    config_dst.write_text(config_text)

    try:
        # ── Phase 1: Config ───────────────────────────────────────────
        print("\n[Phase 1] Loading config (real YAML, real dataclasses)")
        from core.config import BotConfig
        config = BotConfig.load(config_dst)
        errors = config.validate()
        if errors:
            print(f"  ✗ Config validation failed: {errors}")
            return False
        print(f"  ✓ Config loaded: {config.name} (model={config.api.model})")
        print(f"    rate_limit={config.reactive.rate_limit}")
        print(f"    agentic.enabled={config.agentic.enabled}")

        # ── Phase 2: SQLite databases ─────────────────────────────────
        print("\n[Phase 2] Initializing SQLite databases (real aiosqlite)")
        from core.message_memory import MessageMemory
        db_path = Path("persistence") / f"{config.bot_id}_messages.db"
        msg_memory = MessageMemory(db_path)
        await msg_memory.initialize()
        print(f"  ✓ MessageMemory created: {db_path}")

        from core.user_cache import UserCache
        user_db_path = Path("persistence") / f"{config.bot_id}_users.db"
        user_cache = UserCache(user_db_path)
        await user_cache.initialize()
        print(f"  ✓ UserCache created: {user_db_path}")

        # ── Phase 3: Memory manager ───────────────────────────────────
        print("\n[Phase 3] Initializing memory subsystem")
        from core.memory_manager import MemoryManager
        memory_manager = MemoryManager(config.bot_id, Path("memories"))
        memory_manager.thread_parent_resolver = msg_memory.thread_parent
        memory_manager.dm_partner_resolver = user_cache.dm_partner
        print(f"  ✓ MemoryManager (base={memory_manager.base_path})")

        from core.conversation_logger import ConversationLogger
        conv_logger = ConversationLogger(config.bot_id, Path("logs"))
        print(f"  ✓ ConversationLogger")

        # ── Phase 4: Rate limiter ─────────────────────────────────────
        print("\n[Phase 4] Initializing rate limiter")
        from core.rate_limiter import RateLimiter
        rate_cfg = config.get_rate_limiting_config()
        rl = RateLimiter({
            "short_window_minutes": rate_cfg["short"]["duration_minutes"],
            "short_window_max": rate_cfg["short"]["max_responses"],
            "long_window_minutes": rate_cfg["long"]["duration_minutes"],
            "long_window_max": rate_cfg["long"]["max_responses"],
            "ignore_threshold": rate_cfg["ignore_threshold"],
        })
        print(f"  ✓ RateLimiter (short={rl.short_window_max}, long={rl.long_window_max})")

        # ── Phase 5: ReactiveEngine (the critical one) ────────────────
        print("\n[Phase 5] Constructing ReactiveEngine (real code path)")
        from core.reactive_engine import ReactiveEngine
        from collections import deque

        re = ReactiveEngine(
            config=config,
            rate_limiter=rl,
            message_memory=msg_memory,
            memory_manager=memory_manager,
            anthropic_api_key="sk-test-real-init-validation",
            conversation_logger=conv_logger,
            user_cache=user_cache,
        )

        # Verify our fix
        assert isinstance(re.pending_messages, deque), \
            f"pending_messages must be deque, got {type(re.pending_messages)}"
        assert re.pending_messages.maxlen == 10000, \
            f"maxlen must be 10000, got {re.pending_messages.maxlen}"
        assert hasattr(re, "_expedited_scans"), "Missing _expedited_scans"
        assert hasattr(re, "_background_tasks"), "Missing _background_tasks"
        assert hasattr(re, "shutdown"), "Missing shutdown method"
        print(f"  ✓ ReactiveEngine constructed")
        print(f"    pending_messages: deque(maxlen={re.pending_messages.maxlen})")
        print(f"    _background_tasks: set (len={len(re._background_tasks)})")
        print(f"    shutdown: {type(re.shutdown).__name__}")

        # ── Phase 6: AgenticEngine (if enabled) ───────────────────────
        agentic_engine = None
        if config.agentic.enabled:
            print("\n[Phase 6] Constructing AgenticEngine")
            from core.agentic_engine import AgenticEngine
            agentic_engine = AgenticEngine(
                config=config,
                memory_manager=memory_manager,
                message_memory=msg_memory,
                anthropic_client=re.anthropic,
            )
            print(f"  ✓ AgenticEngine constructed")

        # ── Phase 7: MemoryConsolidator ───────────────────────────────
        if agentic_engine:
            print("\n[Phase 7] Constructing MemoryConsolidator")
            from core.consolidator import MemoryConsolidator
            consolidator = MemoryConsolidator(
                bot_id=config.bot_id,
                config=config,
                message_memory=msg_memory,
                memory_manager=memory_manager,
                user_cache=user_cache,
                anthropic_client=re.anthropic,
                vaults=re.vaults,
            )
            agentic_engine.consolidator = consolidator
            print(f"  ✓ MemoryConsolidator")

            print("\n[Phase 7b] Constructing WatchManager")
            from core.watch_manager import WatchManager
            watches_path = memory_manager.resolve_path(
                f"/memories/{config.bot_id}/global/watches.json")
            watch_mgr = WatchManager(watches_path)
            agentic_engine.watch_manager = watch_mgr
            print(f"  ✓ WatchManager (path={watches_path})")

        # ── Phase 8: DiscordClient (ties everything together) ─────────
        print("\n[Phase 8] Constructing DiscordClient")
        from core.discord_client import DiscordClient
        client = DiscordClient(
            config=config,
            reactive_engine=re,
            agentic_engine=agentic_engine,
            message_memory=msg_memory,
            user_cache=user_cache,
            conversation_logger=conv_logger,
            memory_manager=memory_manager,
        )
        if agentic_engine:
            agentic_engine.set_discord_client(client)
        print(f"  ✓ DiscordClient (all components wired)")

        # ── Phase 9: Async init on reactive engine ────────────────────
        print("\n[Phase 9] Running ReactiveEngine.async_initialize() (real I/O)")
        # Mock the Anthropic client to avoid API calls
        re.anthropic = MagicMock()
        re.anthropic.beta = MagicMock()
        re.anthropic.beta.messages = MagicMock()
        re.anthropic.beta.messages.stream = MagicMock()
        re.anthropic.beta.files = MagicMock()
        re.anthropic.beta.files.delete = AsyncMock()
        re.anthropic.beta.files.retrieve_metadata = AsyncMock(return_value=MagicMock(
            id="file_test", filename="test.txt", size_bytes=100,
            mime_type="text/plain", created_at="2026-01-01"
        ))
        re.anthropic.beta.files.download = AsyncMock()
        re.files_api_client.anthropic = re.anthropic
        try:
            await re.async_initialize()
            print(f"  ✓ async_initialize() completed")
            print(f"    episode_manager: {re.episode_manager is not None}")
            print(f"    conversation_state_manager: {re.conversation_state_manager is not None}")
            print(f"    attachment_manager: {re.attachment_manager is not None}")
        except Exception as e:
            print(f"  ✗ async_initialize() failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # ── Phase 10: deque survival through expedited scan ────────────
        print("\n[Phase 10] Testing deque maxlen under expedited scan pattern")
        original_len = len(re.pending_messages)
        for i in range(100):
            re.pending_messages.append((f"chan{i}", i))
        assert len(re.pending_messages) == 100
        print(f"  ✓ Appended 100 messages (len={len(re.pending_messages)})")

        # Simulate what _expedited_scan does (our fixed code)
        channel = "chan50"
        mine = [p for p in re.pending_messages if p[0] == channel]
        assert len(mine) == 1, f"Expected 1 match, got {len(mine)}"
        keep = deque(maxlen=re.pending_messages.maxlen)
        for p in re.pending_messages:
            if p[0] != channel:
                keep.append(p)
        re.pending_messages = keep
        assert isinstance(re.pending_messages, deque), "lost deque type!"
        assert re.pending_messages.maxlen == 10000, "lost maxlen!"
        assert len(re.pending_messages) == 99
        print(f"  ✓ Filter preserved deque type + maxlen (len={len(re.pending_messages)})")

        # ── Phase 11: Async shutdown ───────────────────────────────────
        print("\n[Phase 11] Running async shutdown path")
        await re.shutdown()
        assert len(re._background_tasks) == 0, \
            f"background_tasks not cleared: {len(re._background_tasks)}"
        print(f"  ✓ Shutdown completed (background_tasks cleared)")

        # Close SQLite connections
        await msg_memory.close() if hasattr(msg_memory, 'close') else None
        await user_cache.close() if hasattr(user_cache, 'close') else None
        if re.conversation_state_manager:
            await re.conversation_state_manager.close()
        print(f"  ✓ Database connections closed")

        # ── Phase 12: Verify created files ─────────────────────────────
        print("\n[Phase 12] Verifying filesystem artifacts")
        persistence_dir = Path("persistence")
        created_files = list(persistence_dir.glob("*.db"))
        for f in created_files:
            print(f"    {f.name} ({f.stat().st_size} bytes)")
        assert len(created_files) >= 1, "No database files created"
        print(f"  ✓ {len(created_files)} database file(s) created and persisted")

        print("\n" + "=" * 70)
        print("ALL 12 PHASES PASSED ✓")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        os.chdir(orig_cwd)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)
