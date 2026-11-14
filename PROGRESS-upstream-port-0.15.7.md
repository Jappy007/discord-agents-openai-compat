# Progress: upstream port 0.15.7

Tracking implementation of `PLAN-upstream-port-0.15.7.md`.
Legend: [ ] pending · [~] in progress · [x] done

## Phase 1 — Safety net and packaging

- [x] 1.1 Dashboard authentication (token, Host/Origin guard, no framing, apiFetch)
- [x] 1.2 Asset cache-busting for images/fonts
- [x] 1.3 Installer bundle includes `tools/`, smoke-tests framework imports
- [x] 1.4 Dependency pinning
- [x] 1.5 Regression harness (tests added per phase)

## Phase 2 — Security and memory integrity

- [x] 2.1 Memory path normalization
- [x] 2.2 Vault write containment
- [x] 2.3 Web-fetch provenance
- [x] 2.4 Orphan reclaim scoping
- [x] 2.5 DM repository guard
- [x] 2.6 Memory tool aliases

## Phase 3 — Concurrency and turn accounting

- [x] 3.1 Per-channel locks
- [x] 3.2 Send guard
- [x] 3.3 Turn costs sum every call
- [x] 3.4 Event/monitor fixes (sent_texts + never; job events wait for workshop)
- [x] 3.5 Context gauge
- [x] 3.6 Coordination and scan ordering

## Phase 4 — Conversation history and seeding

- [x] 4.1 `MessageMemory.get_recent()` options
- [x] 4.2 Seed deduplication
- [x] 4.3 `ConversationState.held`
- [x] 4.4 Recent-message map
- [x] 4.5 Lifecycle markers
- [x] 4.6 Message cap
- [x] 4.7 Bot chain limit
- [x] 4.8 Silent near-miss guard

## Phase 5 — Lifecycle, reconnect, clean stop

- [x] 5.1 Boot once per process
- [x] 5.2 Presence survives re-identify
- [x] 5.3 Resume floor / reconnect catch-up
- [x] 5.4 Boot failure
- [x] 5.5 Channel names on reconnect
- [x] 5.6 Clean stop
- [x] 5.7 App restart

## Phase 6 — App and dashboard polish

- [x] 6.1 Requirements hash install
- [x] 6.2 Paused/failed updates state
- [x] 6.3 Keep awake / open at login
- [x] 6.4 Fleet board real status

## Phase 7 — Skills

- [x] 7.1 `core/skills.py`
- [x] 7.2 `tools/skills_tool.py` + tool wiring
- [x] 7.3 Copy text-only skills
- [x] 7.4 Bundle `skills/`

> Fork note: upstream v0.15.7 leaves the two fiction guides workshop-only.
> This fork marks them `text-only: true` so they keep working where no workshop
> is configured (Phase 8 now provides the workshop, but the fallback is still
> useful on hosts without virtualization); the other four skill folders remain
> workshop-only.

## Phase 8 — Workshop sandbox (optional)

- [x] 8.1 Dependency/runtime: `microsandbox==0.7.8`, bundle smoke imports
- [x] 8.2 Core workshop modules (`scopes`, `state`, `backend`, `service`,
      `jobs`, `notes`, `approvals`, `proxy`, `watcher`, `panel`, `projects`,
      `workers`) plus `backends/{fake,microsandbox}.py`
- [x] 8.3 `bash` + editor tools, dispatch in `_execute_tool_blocks`, 25-step
      workshop turn cap and 20-minute turn wall clock
- [x] 8.4 Long jobs: jobs table, `JobWatcher`, completion notes and quiet
      turns, boot reconciliation
- [x] 8.5 Network approvals: egress proxy, rotating per-scope credentials,
      `request_network_access`, operator DMs + dashboard decisions
- [x] 8.6 Start gate: test boot before login, `status.json`, exit code 78,
      supervisor blocked state + 10-minute retry, `workshop.enabled: false`
- [x] 8.7 Dashboard Workshop tab: status/disk per scope, reset/wipe, pending
      approvals, jobs and helper transcripts; read-only supervisor routes
- [x] 8.8 Attachments: `/workspace` paths in `send_message`; fetched files
      copied into `/workspace/inbox`
- [x] 8.9 Projects and check-ins (`projects.py`, hourly tick, manifest in the
      volatile tail)
- [x] 8.10 Helpers: `delegate` tool, `workers.py`, restricted tools, budgets,
      step/time caps
- [x] 8.11 Regression tests (`tests/test_workshop_phase8.py`) on `FakeBackend`
- [x] 8.12 Operator Stop stops this install's sandboxes (`supervisor/sandboxes.py`)

> Fork adaptations: `core/workshop/workers.py` calls the fork's
> `llm.beta.messages.stream()` instead of `core/model/driver`; tool schemas are
> built from the fork's internal shapes. Worker model routing uses `api.model`
> until Phase 9 adds `api.worker_model`. The supervisor never imports bot code;
> `VaultEnforcer.resolve_scope` was ported from upstream for scopes.
>
> Not exercised here: the real Microsandbox backend needs a Linux VM runtime.
> Tests drive the same paths through `FakeBackend`; production uses
> `MicrosandboxBackend`. The dashboard skills-management UI upstream added in
> 0.14 is still absent (skills are configured in YAML).

## Phase 9 — Model roles and optional OpenAI layer

- [x] 9.1 Per-bot background/worker models (`api.background_model`,
      `api.worker_model`; `OPENAI_UTILITY_MODEL` remains the global fallback)
- [x] 9.2 Mini-catalog / costs (`MODEL_CATALOG`, ceilings and per-model prices;
      `cost_today_usd` + `cost_complete` in the supervisor)
- [x] 9.3 Cost-by-turn script (`scripts/cost_by_turn_kind.py`, per bot/kind/model)
- [ ] 9.4 Responses adapter — deferred (optional); generic OpenAI-compatible
      `/chat/completions` remains the only transport
- [x] 9.5 Regression tests (`tests/test_model_roles_phase9.py`)

> Fork adaptations: upstream routes roles through `core/model/`; this fork
> resolves them in `core/llm_providers/factory.py` and keeps passing explicit
> model names to the existing OpenAI-compatible client. Unknown/self-hosted
> models stay unpriced (cost totals are marked partial) and keep the generic
> output ceiling. The cost script reads the fork's
> `persistence/<bot>_messages.db` layout.
