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

- [ ] 6.1 Requirements hash install
- [ ] 6.2 Paused/failed updates state
- [ ] 6.3 Keep awake / open at login
- [ ] 6.4 Fleet board real status

## Phase 7 — Skills

- [ ] 7.1 `core/skills.py`
- [ ] 7.2 `tools/skills_tool.py` + tool wiring
- [ ] 7.3 Copy text-only skills
- [ ] 7.4 Bundle `skills/`

## Phase 8 — Workshop sandbox (optional)

- [ ] Skipped for now (large, separate epic)

## Phase 9 — Model roles and optional OpenAI layer

- [ ] 9.1 Per-bot background/worker models
- [ ] 9.2 Mini-catalog / costs
- [ ] 9.3 Cost-by-turn script
- [ ] 9.4 Responses adapter (optional)
