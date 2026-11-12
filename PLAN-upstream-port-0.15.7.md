# Port plan: upstream `CharlesTheFool/discord-agents` → this OpenAI-compatible fork

## Baseline

- **Fork point:** `5e32517` (v0.12.4 + dashboard asset hashing, 2026-07-05)
- **Upstream now:** v0.15.7 (96 commits, 2026-11-02)
- **Do not merge upstream wholesale.** Upstream reintroduces the Anthropic SDK and the `core/model/` driver refactor; this fork deliberately replaced that boundary with `core/llm_providers/openai_compatible.py`.
- **Recommended method:** cherry-pick each fix/feature by hand, adapting the Anthropic-specific pieces to the internal message/tool shape in `core/reactive_engine.py`.

Legend: ✅ port as-is · 🟡 port with adaptation · 🔵 optional / after prerequisites · ❌ not applicable

---

## Compatibility matrix

| Upstream | Change | Fit | Notes |
|---|---|---|---|
| 0.12.5 | Dashboard API token, Host/Origin guard, no framing | ✅ | Fork has **no auth at all** |
| 0.12.5 | Asset cache-busting for images/fonts | ✅ | Fork regex only covers `.js/.css` |
| 0.12.5 | Reject Haiku as main model | ❌ | Anthropic-specific |
| 0.13.0 | `core/model/` driver + catalog + registry | ❌/🟡 | Fork's `llm_providers` is the equivalent; only role-model config is worth adapting |
| 0.13.0 | Installer bundle includes `tools/`, smoke-tests framework | ✅ | **Fork has this bug right now** |
| 0.13.0 | Pin dependency versions | ✅ | Fork uses `>=` everywhere |
| 0.13.0 | `background_model` / `worker_model` config | 🟡 | Fork has `OPENAI_UTILITY_MODEL`; add per-bot overrides |
| 0.13.1 | Per-channel locks replace bot-wide semaphore | ✅ | Fork has `Semaphore(1)` |
| 0.13.1 | Send guard / no double post | ✅ | |
| 0.13.1 | Turn events sum every model call | ✅ | Fork records only last call |
| 0.13.1 | Vault writes contained; memory paths normalized | ✅ | |
| 0.13.1 | One coordination drainer; scan/mention ordering | ✅ | |
| 0.14.0 | Workshop sandbox (microVM, bash, editor, proxy, jobs) | 🔵 | Large; provider-neutral and very natural for this fork |
| 0.14.0 | Attachments by framework id / Files API removal | ❌ | Fork already uses local storage |
| 0.14.0 | Local skills (`core/skills.py`) | ✅ | Fork deleted skills entirely |
| 0.14.0 | Orphan-process reclaim scoped to install | ✅ | Fork still substring-matches |
| 0.14.0 | DM repository disabled | 🟡 | Verify; small |
| 0.14.1 | Larger documents without workshop | 🟡 | Adapt to local text extraction for OpenAI |
| 0.14.1 | Silent note-driven turns | 🟡 | Fork's `stay_silent` tool already covers most |
| 0.14.2 | Trim message cap to a quarter below | ✅ | Helps OpenAI automatic prefix caching too |
| 0.14.3/4 | Anthropic server web tools / caching measure | ❌ | Fork uses client-side web tools |
| 0.15.0 | Projects / project check-ins | 🔵/🟡 | Can work without workshop if simplified |
| 0.15.0 | Helpers / `delegate` | 🔵 | Requires workshop |
| 0.15.0 | Workshop dashboard panel | 🔵 | Requires workshop |
| 0.15.0 | Keep computer awake / open at login | ✅ | Needs `app/preload.js` + `app/settings.js` |
| 0.15.0 | Web-fetch URL provenance | 🟡 | No server tools, but same injection risk |
| 0.15.0 | Context gauge writes `token_count` | ✅ | Fork gauge always shows 0 |
| 0.15.0 | Vault/DM checks case-insensitive + 8.3 names | ✅ | Real security hole |
| 0.15.1 | OpenAI Responses adapter | 🔵 | Not needed for generic `/chat/completions` |
| 0.15.1 | OpenAI prompt-cache breakpoints | ❌ | Chat Completions caches automatically |
| 0.15.1 | Role models routed by catalog | 🟡 | Fold into 0.13.0 item |
| 0.15.2 | Bot-chain limit (two bots stop looping) | ✅ | |
| 0.15.3 | `<silent/>` for scans | 🟡 | Fork's `stay_silent` is the primary mechanism; add near-miss text guard |
| 0.15.3 | Seed excludes queued messages | ✅ | |
| 0.15.4 | Recent map covers whole conversation | ✅ | Fork hardcodes `limit=15` |
| 0.15.4 | Collapse lifecycle markers; UTC crash mark | ✅ | |
| 0.15.4 | `ConversationState.held` idempotent appends | ✅ | |
| 0.15.5 | Reconnect is not a restart | ✅ | **Fork runs the whole boot on every READY** |
| 0.15.5 | Presence survives re-identify | ✅ | |
| 0.15.6 | Resume floor taken before READY-window messages | 🟡 | Adapt to fork's backfill-state model |
| 0.15.6 | Failed boot closes the client | ✅ | |
| 0.15.6 | Channel names refresh on reconnect | ✅ | |
| 0.15.7 | Clean stop via supervised stdin | ✅ | Terminate reads as crash today |
| 0.15.7 | "Restart now" stops bots first | ✅ | |

---

## Phase 1 — Safety net and packaging (≈1 day)

### 1.1 Dashboard authentication (0.12.5)

- `supervisor/paths.py`: add `api_token_file()` / `api_token()`, generate `persistence/supervisor_token` with `0600`.
- `supervisor/api.py`: add `guard` middleware:
  - `Host` must be `127.0.0.1:<port>` or `localhost:<port>`
  - foreign `Origin` on writes → 403
  - `X-DA-Token` on every `/api/` route, except `GET /api/supervisor`
  - `X-Frame-Options: DENY` + `frame-ancestors 'none'` via `on_response_prepare`
- `supervisor.py`: embed `<meta name="da-token">` in rendered pages.
- `supervisor/ui/assets/*.js`: route all calls through `apiFetch()`; replace log `EventSource` with streamed `fetch`.
- `app/main.js`: read the token from the served page and send it on shutdown.
- **Breaking:** update `app/main.js` in the same change or the app can no longer stop the daemon.

### 1.2 Asset cache-busting

- Extend `_ASSET_REF_RE` in `supervisor.py` to images/fonts; sort extensions longest-first (`woff2` before `woff`).

### 1.3 Installer bundle

- `app/build-bundle.js`: add `"tools"` to `FRAMEWORK_ITEMS`; remove the nonexistent `"skills"` skip message.
- Change the smoke test from dependency imports to `import bot_manager, core.llm_providers.openai_compatible`.
- This is the upstream 0.13.0 fix; the fork currently ships a bundle that cannot start a bot.

### 1.4 Dependency pinning

- Pin `requirements.txt` to exact versions (keep `ddgs` and `openai`), matching the fork's actual resolved set.

### 1.5 Regression harness

- Fork has only `tests/test_silence_tools.py`. Add focused tests as each phase lands; upstream has no in-repo tests to copy.

---

## Phase 2 — Security and memory integrity (≈2–3 days)

### 2.1 Memory path normalization (0.13.1 + 0.15.0)

- In `core/vaults.py`: add `normalize_memory_path()`, `memory_path_problem()`, `path_parts()`.
- Normalize `path`/`new_path` **before** every vault/DM check in `core/memory_tool_executor.py`.
- Case-fold segment comparisons; reject `~`, `:`, trailing dot/space in any segment.
- Protect against `..`, Windows backslashes, 8.3 names, ADS.
- This is a real read/write escape on Windows/macOS today.

### 2.2 Vault write containment (0.13.1)

- Add `_inside_own_vault_tree()`: from inside a vault, writes must land in that vault's tree; innermost vault wins; `followups.json` remains allowed.
- Threads of vaulted channels count as inside.

### 2.3 Web-fetch provenance (0.15.0, adapted)

- `tools/client_web_tools.py`: track URLs seen in user messages and prior `web_search` results.
- Reject `web_fetch` URLs that appear only in tool results (e.g. a URL the bot printed itself).
- Update `SECURITY.md` with the residual (user/tool-result relay).

### 2.4 Orphan reclaim scoping (0.15.0)

- `supervisor/process_manager.py`: match the install's own script path, quote/case/slash-insensitively, with bot id as a whole argument; stop matching `alpha-2` for `alpha`.

### 2.5 DM repository

- Verify `repository_manager` refuses DM scopes; if not, add the guard.

### 2.6 Memory tool robustness (optional)

- Accept `insert_text` / `old_path` / `new_path` aliases alongside the fork's `old_str` / `new_str`, for OpenAI models that imitate Anthropic's schema.

---

## Phase 3 — Concurrency and turn accounting (≈4–6 days)

### 3.1 Per-channel locks (0.13.1)

- Add `core/channel_locks.py` (`lock(channel_id)`, `busy(channel_id)`).
- Replace `ReactiveEngine._response_semaphore` (currently `Semaphore(1)`, bot-wide) with channel locks.
- Hold the channel lock from reading state through saving the reply:
  - mention turns
  - periodic scans
  - proactive/follow-up/coordination sends
  - episode reseeds
  - attachment echo
  - backlog ingestion
- Keep a bot-wide model-call limit separately (e.g. semaphore of 3) so channels run side by side.
- This is the single biggest UX improvement: one slow channel no longer blocks every other channel.

### 3.2 Send guard (0.13.1)

- Track `ended_on_send` on `ToolLoopResult`, set true only when `send_message` actually posted.
- Drop trailing text only in that case; count `dropped_text_chars`.
- Never drop after a failed send or tool work.

### 3.3 Turn costs sum every call (0.13.1)

- Add `total_usage` to `ToolLoopResult`; accumulate each response's usage.
- Use it for events and cost reporting; keep `usage` (last call) for context-size measurement.

### 3.4 Event/monitor fixes (0.14 dashboard)

- Add `sent_texts`; make `_event_payload` fall back to what `send_message` sent.
- `supervisor/data.py` / `bot.js`: render `job` events; show "never" instead of "Dec 31" for no activity.

### 3.5 Context gauge (0.15.0)

- `ConversationStateManager.save()`: write `state.session_input_tokens` into `conversation_states.token_count`.

### 3.6 Coordination and scan ordering (0.13.1 + 0.15.3)

- One drainer at a time (`_drain_lock`) in `AgenticEngine`.
- Deferred scans: once a channel defers, later messages defer too; put deferred messages back at the front.
- A mention ingests older pending messages for its channel first.
- A scan that waited skips if the conversation moved past its target.

---

## Phase 4 — Conversation history and seeding (≈3–4 days)

### 4.1 `MessageMemory.get_recent()` options (0.15.3/4)

- Add `before_message_id`, `collapse_markers`, `real_only`.
- Collapse runs of lifecycle markers to the newest one.

### 4.2 Seed deduplication (0.15.3)

- `_initialize_conversation_from_db`: exclude queued message ids and everything from `before_message_id` on.
- Claim/ingest pending messages oldest-first (attachments can queue out of order).

### 4.3 `ConversationState.held` (0.15.4)

- In-memory `discord_id → message` map.
- `add_message(..., discord_id=...)` becomes idempotent: a live copy replaces a seeded copy in place (files, reply quote).
- Do **not** persist `held`.

### 4.4 Recent-message map

- `RECENT_MAP_MIN = 15`; `limit=max(RECENT_MAP_MIN, api.context_messages)`, `real_only=True`.
- Avoids "who said that 23 messages back" errors.

### 4.5 Lifecycle markers

- Crash marker stamped naive UTC.
- Seeds collapse markers; recent-per-request queries use real messages only.
- `newest_message_times()` excludes `is_system` and normalizes to aware UTC.

### 4.6 Message cap

- Over cap, trim to `cap - max(1, cap // 4)` instead of one message per turn.
- Keeps the conversation head stable for OpenAI prompt caching.

### 4.7 Bot chain limit (0.15.2)

- `BOT_CHAIN_LIMIT = 6`; past that, unaddressed bot messages get no scan until a person speaks.
- Explicit bot `@mention` still answered.

### 4.8 Silent near-miss guard (0.15.3, optional)

- Treat a reply that is only `<silent/>` / `<silence/>` / `<silent>` as silence in scan paths, complementing `stay_silent`.

---

## Phase 5 — Lifecycle, reconnect, clean stop (≈3–4 days)

### 5.1 Boot once per process (0.15.5)

- `DiscordClient._booted`; on a second `on_ready`, only catch up and refresh names.
- Prevents duplicate scan loops, agentic loops, daily tasks, and false crash markers.
- Fixes the current bug where the running flag is read as a crash on every reconnect.

### 5.2 Presence survives re-identify

- Pass `activity=discord.Game(...)` to `discord.Client.__init__` instead of `change_presence()`.

### 5.3 Resume floor / reconnect catch-up (0.15.6, adapted)

- Take `newest_message_times()` in `setup_hook()` and once per outage in `on_disconnect()`.
- `on_resumed()` clears it.
- Pass the floor into the fork's backfill as the resume point, preserving the existing "first full backfill / widened window" logic.
- This closes the READY-window gap that the fork's `last_backfilled_at` approach can skip.

### 5.4 Boot failure

- Wrap the first boot; on exception log critical, `await self.close()`, let the supervisor restart.

### 5.5 Channel names on reconnect

- Extract `_sweep_channel_names()` and run it on reconnect.

### 5.6 Clean stop (0.15.7)

- Supervisor spawns bots with `--supervised` and `stdin=PIPE`.
- `bot_manager.py`: read stdin on a daemon thread; EOF cancels the main task (same path as Ctrl+C).
- `ProcessManager.stop()` closes stdin, waits `STOP_TIMEOUT_SECONDS=15`, then kills.
- `shutdown()` stops all bots concurrently without mutating desired state.
- Clear the running flag again after task cancellation.
- Fix `os._exit(0)` masking exit codes.

### 5.7 App restart

- `app/main.js`: on "Restart now", stop the daemon/bots before `quitAndInstall()`.

---

## Phase 6 — App and dashboard polish (≈1–2 days)

- **6.1** Dependency install by `requirements.txt` hash (`persistence/requirements.sha256`), retry failed installs.
- **6.2** Paused/failed updates written to `persistence/app_state.json`; fleet page names modified files.
- **6.3** Keep computer awake (`powerSaveBlocker`) and open at login: add `app/preload.js`, `app/settings.js`, IPC in `app/main.js`, toggles in the dashboard.
- **6.4** Fleet board asks the daemon for real status instead of faking a PID.

---

## Phase 7 — Skills (≈2 days)

- Port `core/skills.py`:
  - `SkillCatalog`, frontmatter parsing, `_skill_home()` wrapper-folder handling.
  - `metadata: {text-only: true}` gating.
- Port `tools/skills_tool.py` (`request_skill`) and add the tool to `_build_api_params`.
- Add the skills list to the system prompt only in channels where they are available.
- Copy upstream `skills/`:
  - `storytelling`, `fiction-criticism` are text-only and work today.
  - `docx`, `pptx`, `xlsx`, `pdf` only become useful once the workshop exists.
- Update `app/build-bundle.js` to include `skills/`.

---

## Phase 8 — Workshop sandbox (optional, large: ≈2–3 weeks)

This is provider-neutral and fills the hole left by removing Anthropic code execution. Build in this order:

1. **Dependency/runtime:** `microsandbox==0.7.8`; pin versions; update bundle.
2. **Core:** `core/workshop/{scopes,state,backend,service,jobs,notes}.py`; `core/workshop/backends/microsandbox.py` (plus `fake.py` for tests).
3. **Tools:** `tools/bash_tool.py`, `tools/editor_tool.py`; dispatch through the fork's existing `_execute_tool_blocks`; raise tool-loop iterations to 25 for workshop turns.
4. **Long jobs:** job table/store, `JobWatcher`, completion note → a quiet turn; survive restarts.
5. **Network:** egress proxy (`proxy.py`), `request_network_access`, operator Allow/Deny DMs, rotating per-scope credentials.
6. **Start gate:** test boot before login; supervisor "Can't start" + retry; `workshop.enabled: false` fallback.
7. **Dashboard panel:** workshop status/disk, reset/wipe, approvals, job/helper transcripts; supervisor routes read only named fields.
8. **Attachments:** bridge `/workspace/inbox` and `send_message` attachments by workspace path.
9. **Projects/check-ins:** `core/workshop/projects.py` + hourly tick + context injection; can be shipped before helpers.
10. **Helpers:** `tools/delegate_tool.py`, `core/workshop/workers.py`, restricted tool set, budget/step/time caps.

Also port the workshop-specific fixes from 0.14.1–0.15.7: proxy rotation, real disk usage, wipe confirmation, helper output-limit message, concurrency caps, panel hardening.

---

## Phase 9 — Model roles and optional OpenAI layer (≈1–3 days)

- **9.1** Add per-bot `api.background_model` and `api.worker_model`; route through `build_llm_client()` with the resolved model. Keep `OPENAI_UTILITY_MODEL` as the global fallback.
- **9.2** Optional mini-catalog in `core/internal_constants.py` for output ceilings and per-model prices; feed `supervisor/data.py` cost reporting (currently `cost_today_usd: None`).
- **9.3** Optional `scripts/cost_by_turn_kind.py` adapted to token events.
- **9.4** OpenAI Responses adapter (0.15.1) only if you want `/responses` support or reasoning-model controls. It is not required for generic OpenAI-compatible endpoints.

---

## Explicitly skipped

| Upstream | Why |
|---|---|
| `core/model/` driver + Anthropic adapter + catalog rewrite | Fork's `llm_providers` boundary is the replacement; porting would undo the OpenAI-only design |
| Anthropic server web search/fetch fixes (0.14.3, 0.14.4) | Fork uses client-side tools |
| Files API / attachment refs (0.14.0) | Fork already stores locally |
| Batch/consolidation/induction changes (0.13.x) | Those modules were removed from the fork |
| Haiku model validation | Anthropic-specific |
| Model-stamp rollback script | No model stamps |
| OpenAI cache breakpoints | Chat Completions caches automatically |
| Workshop-only fixes | Only after Phase 8 |

---

## Suggested order and rough effort

| Phase | Effort | Recommendation |
|---|---|---|
| Phase 1 Packaging/auth | 1 day | **First PR** — low risk |
| 2 Security/memory | 2–3 days | **First PR** — highest severity |
| 3 Concurrency | 4–6 days | Second PR |
| 4 History/seeding | 3–4 days | Same PR as 3 or immediately after (same files) |
| 5 Lifecycle/stop | 3–4 days | Third PR |
| 6 App/dashboard | 1–2 days | Can run in parallel |
| 7 Skills | 2 days | Small, independent |
| 8 Workshop | 15–25 days | Separate epic; decide first |
| 9 Model roles | 1–3 days | Low priority |

**Core without workshop: roughly 3–4 weeks.** Full port including workshop: **6–8 weeks**.

## Main risks

1. `core/reactive_engine.py` has diverged substantially; Phases 3–4 will need manual conflict resolution, not `git cherry-pick`.
2. The fork has almost no tests; each port needs a new regression test to avoid re-breaking silence/send/seed behavior.
3. Upstream code assumes `core/model/`, `core/channel_locks.py`, and workshop modules that don't exist; import paths must be adapted.
4. OpenAI-compatible endpoints differ in document/tool-result support; any attachment or PDF work must stay on local text extraction.
5. Dashboard auth is a breaking change for the desktop launcher; ship `supervisor/` and `app/main.js` together.
