# Discord Agents

**Version:** 0.12.4 fork baseline, ported through upstream 0.15.7 (Pre-release Beta)

Build intelligent Discord bots that think, remember, and act autonomously on any
OpenAI-compatible model endpoint.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Discord.py](https://img.shields.io/badge/discord.py-2.7.1-blue.svg)](https://discordpy.readthedocs.io/)
[![Security](https://img.shields.io/badge/security-policy-blue.svg)](SECURITY.md)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](CHANGELOG.md)

---

## ⚠️ Beta Notice

This is a beta release. The framework is feature-complete and validated through
live scenario testing, but APIs and configuration may still evolve between beta
versions. Report issues via [GitHub Issues](../../issues); report security
vulnerabilities via [GitHub Security Advisories](SECURITY.md).

**Fork scope.** This checkout is the OpenAI-compatible fork of Discord Agents.
Every model call goes through `/chat/completions` — OpenAI, OpenRouter, Together,
Groq, Ollama, LM Studio, vLLM, or any compatible endpoint. Upstream's
Anthropic-specific capabilities (server-side code execution, Files/Batches APIs,
native web tools, prompt caching) are intentionally absent. Provider-neutral
upstream work through v0.15.7 has been ported by hand; see
[OPENAI_COMPATIBILITY.md](OPENAI_COMPATIBILITY.md) for the supported matrix.

---

## What It Does

### Two engines, one bot

A **reactive engine** answers @mentions immediately and scans ongoing
conversation for moments worth joining — with the judgment to stay quiet when
it has nothing to add. An **agentic engine** runs in the background: it
initiates conversation in idle channels, remembers to follow up on things
people mentioned ("how did the presentation go?"), and learns per-channel
engagement rates so it backs off where it isn't wanted.

### Memory that survives

- **Episodic sessions** — when a conversation session grows past its token
  threshold or goes idle, the bot distills it into a titled, timestamped
  episode file and reseeds its live context. The archive stays searchable
  through the bot's memory tool, so "what did we decide last Tuesday?" works
  weeks later.
- **One person, one profile** — user profiles are global (one file per
  human, keyed by Discord ID) with per-claim origin tags, so the bot knows
  the same person across every server while keeping what it learned where
  it learned it.
- **Long-term memory** — Markdown files (profiles, channel notes, server
  culture) the bot reads and writes itself.
- **Message history** — SQLite with FTS5 full-text search; the bot can search
  and quote its own channel history on demand.
- **Backfill once, then gaps only** — each channel's first sweep records a
  persistent completion marker. Later boots fetch only what was missed while
  offline; widening `backfill_days` (including to `0` for unlimited) deepens
  that channel's history automatically. `@bot reindex` forces a full sweep.
- **Attachments** — images, documents, spreadsheets, and code files are
  indexed and retrievable: the bot can pull any past attachment back into
  context with its `get_attachment` tool.
- **File repository** — a per-server local drive you can edit by hand and
  the bot manages with its `repository` tool; files survive Discord's CDN
  expiry.
- **DM memory** — DMs are a first-class memory surface: notes and episodes
  live in a global per-person tree (`global/dms/`) that belongs to the
  person, not to any server, and is mechanically invisible from everywhere
  else.
- **/memory commands** — in a DM, `/memory show` returns your profile
  verbatim; `/memory remember`, `forget`, and `feedback` let you teach or
  correct the bot directly, through a one-shot grant that opens exactly
  your own profile file for that turn.

### One mind across servers

A bot in several servers is one mind with separate rooms — and the rooms have
a hallway. The `ask_prime` tool lets the bot in one server ask "the Prime"
(itself, above all its servers) to pose a question or announce something in
another server. Mechanical gates run before any model judgment: vault
boundaries in both directions, daily budgets, DM refusal. Approved messages
are delivered by the target server's bot in its own voice. A **standing
watch** can ride along: the hourly loop watches the target channel for an
answer (one cheap model call per check) and relays it back — "relayed via
Prime, from {server}" — durably, into the asking channel. DMs sit above this
entirely: a DM is a conversation with the Prime itself.

### Native messaging

The model talks to Discord through tools, not just through whatever text it
ends its turn with:

- **`send_message`** — each call is one message, sent mid-turn. It can anchor
  itself as a real Discord reply (`reply_to_message_id`) and attach files
  created this turn (`attach_outputs`). The tool result reports ground truth —
  the sent message id and exactly which files attached — so phantom
  attachments are mechanically hard to sustain.
- **Multi-message turns** — several calls per turn, in guaranteed order, so an
  anchored reply can coexist with a general message for the rest of the room.
- **`stay_silent` and reactions** — explicit silence, or an `add_reaction`
  that is the whole response, instead of posting an acknowledgement nobody
  needed. Plain final text still posts in compat mode, exactly as before.

### Workshop and skills (optional)

- **Workshop** — a per-scope Linux microVM (microsandbox) with a shell, an
  editor, a persistent `/workspace`, and filtered internet. Package
  downloads use a preset allowlist; anything else sends you an Allow/Deny DM
  (or a dashboard decision), and approved hosts are remembered per scope.
  Long commands run as background jobs that report back when they finish.
  Projects and check-ins keep multi-turn work moving, and `delegate` hands
  bounded subtasks to helper workers. Disable it per bot or per scope on hosts
  without virtualization; the rest of the framework works without it.
- **Skills** — local folders under `skills/`, each with a `SKILL.md`. The bot
  lists them in context and reads one on demand with `request_skill`. Text-only
  guides (storytelling, fiction criticism) work everywhere; skills with
  scripts or templates run inside the workshop, where they are copied to
  `/skills/<name>/`.
- **Workshop integration** — files created in `/workspace` can ride a
  `send_message` attachment, and attachments sent to the bot are copied into
  `/workspace/inbox`. The dashboard's Workshop tab shows scope status, disk
  use, pending approvals, jobs, and helper transcripts.

### Capabilities

- **Presentations** — `create_pptx` builds a deck locally and attaches it
  directly to the bot's Discord reply.
- **Web search** — client-side search and page-fetch tools, with no API key
  required. Fetches are restricted to URLs seen in user messages or prior
  search results.
- **MCP integration** — connect remote MCP servers; their tools are
  auto-discovered and available to the bot.
- **Vision** — image attachments are processed and understood in context.
- **Model roles** — set a cheaper `background_model` for episode
  distillation and watch checks, and a `worker_model` for delegated workshop
  helpers. Unset roles fall back to the main model or `OPENAI_UTILITY_MODEL`.
- **Cost awareness** — the dashboard shows today's estimated spend per bot and
  for the fleet, with partial totals clearly marked for unpriced models.
  `scripts/cost_by_turn_kind.py` breaks spend down by bot, turn kind, and model.
- **Every surface** — text channels, threads (active and archived, with
  memory nested under the parent channel), voice-channel text chats, and
  private DMs; the bot always knows what kind of room it's in.
- **Optional Minecraft mode** — run the same memory and agent pipeline as a
  Mineflayer player instead of a Discord bot (`mode: minecraft`); see
  `bots/alpha-mc.yaml.example` and `PLAN-minecraft-bridge.md`.

### Operator surface

- **Supervisor daemon** — `python supervisor.py` runs a separate
  process-manager + localhost API (127.0.0.1:8642): start/stop/restart
  bots, crash recovery with exponential backoff, and a full read surface
  over every bot's artifacts (status, memory, logs, events). It reads
  files, never imports bot internals; every file route is path-jailed.
- **Dashboard authentication** — the supervisor refuses foreign `Host`
  headers and cross-origin writes, sends no-store for UI files, and requires
  a per-install token on every API route. The token is generated on first run
  at `persistence/supervisor_token` and embedded in the served page, so the
  dashboard and desktop app work without manual setup; scripts must send it
  as `X-DA-Token`.
- **Dashboard** — a fleet board and per-bot pages: Monitor (engine gauges,
  live-context fill, token/cost totals, and a channel monitor showing the
  bot's *x-ray stream*: what it read, what it thought, which tools it called,
  what it said, or why it stayed quiet), Configure (the YAML as a form,
  validated by the same code the bot boots with), Integrations (MCP health
  and skills), Workshop (scope status, approvals, jobs), Memories (browse and
  edit), and Repository.
- **Desktop app (self-contained)** — the Windows installer ships an
  embedded Python runtime and the framework: download, run, create a bot,
  set your OpenAI-compatible endpoint in `.env`, paste your Discord token in
  the app, press Start. No Python, no git, no terminal. Bot data lives in
  `%APPDATA%\Discord Agents` and survives updates; closing the window stops
  bots cleanly and they return on relaunch. The launcher updates itself,
  fast-forwards the framework, installs changed requirements, and surfaces
  paused/failed updates. Keep-awake and open-at-login are app settings. (A git
  checkout + `app-config.json` keeps the developer model working unchanged.)
- **Events substrate** — every bot turn (mention, DM, scan, *stayed silent*,
  proactive, follow-up, memory write, relay, watch, reseed) writes one
  structured row; the dashboard and the conversations log both read from it.

### Production posture

- Per-channel rate-limit presets with engagement-aware backoff
- Persistent conversation state across restarts; boot-once lifecycle,
  reconnect catch-up, crash detection, and clean supervised shutdown
- Per-channel locks so concurrent turns cannot double-post or race state
- **Vaults** — mark any channel or server and its content never leaves it:
  excluded from outside search and attachments, memory files sealed,
  repository writes contained
- **DM privacy is mechanical** — what's said in a DM is visible only inside
  that DM, enforced at the search, viewing, and attachment layers
- Multiple isolated bots from one codebase (separate configs, databases,
  memory trees, and logs)

---

## Prerequisites

- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **Discord Bot** — [Create application](https://discord.com/developers/applications)
  - Enable "Message Content Intent" in Bot settings
- **OpenAI-compatible API** — any `/chat/completions` endpoint and model.
  - Set `OPENAI_API_KEY` and `OPENAI_BASE_URL`, and either `OPENAI_MODEL` or
    `api.model` in the bot YAML. See `OPENAI_COMPATIBILITY.md`.
- **Optional workshop** — Linux with a virtualization backend supported by
  `microsandbox` (the bundled runtime is installed with requirements). If
  your host can't run it, set `workshop.enabled: false`; skills with scripts
  and the sandbox tools will be unavailable, but everything else runs.
- **Optional Minecraft mode** — Node.js 20+ in `mc_bridge/` (`npm install`),
  plus a Minecraft account/server.

---

## Quick Start

### The short way (no Python, no git)

Download **Discord Agents Setup** from the latest release, run it, and the
app walks you through the rest: configure your OpenAI-compatible endpoint in
`.env`, commission a bot, paste its Discord token on the bot's Configure tab,
pick its servers from a list, press Start. Everything below is the developer
path.

### 1. Clone and install

```bash
git clone https://github.com/CharlesTheFool/discord-agents.git
cd discord-agents
pip install -r requirements.txt
```

Requirements are pinned to the versions the suite and production run on.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ALPHA_BOT_TOKEN=your_discord_bot_token_here
OPENAI_API_KEY=your_provider_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
```

`OPENAI_MODEL` overrides `api.model` in the YAML. `OPENAI_MAX_OUTPUT_TOKENS`
and `OPENAI_UTILITY_MODEL` are optional; the utility model handles episode
distillation and watch checks.

### 3. Configure your bot

```bash
cp bots/alpha.yaml.example bots/alpha.yaml
```

Edit `bots/alpha.yaml`:

```yaml
discord:
  servers:
    - "YOUR_SERVER_ID_HERE"   # Right-click server → Copy ID (Developer Mode)
  timezone: "UTC"              # IANA format: America/New_York, Europe/London, ...

personality:
  base_prompt: |
    Your bot's character AND behavior style — tone, when to engage,
    formatting preferences. This prompt is the main behavioral control.
```

The example enables the workshop by default. Set `workshop.enabled: false`
if this host can't run microsandboxes.

### 4. Run

```bash
python bot_manager.py spawn alpha
```

The bot connects, backfills message history in the background on its first
run (later runs only fetch the gap left by downtime), starts its autonomous
loop, and responds to @mentions.

### 5. (Optional) Run the dashboard

```bash
python supervisor.py            # http://127.0.0.1:8642
```

Manage bots, watch the channel monitor, handle workshop approvals, edit
memories and config from the browser — or install the desktop app from the
release assets, which opens the same dashboard in its own window. The
dashboard token is generated automatically and embedded in the page; API
clients can read it from `persistence/supervisor_token` and send it as
`X-DA-Token`.

---

## Configuration

Configuration stays small and preset-driven. Behavioral style lives in the
personality prompt; operational tuning uses presets:

```yaml
reactive:
  rate_limit: "moderate"        # strict | moderate | permissive | unlimited

agentic:
  proactive:
    enabled: true
    intensity: "moderate"       # gentle | moderate | active
    quiet_hours: [0, 1, 2, 3, 4, 5, 6]   # LOCAL host-clock hours

api:
  model: ""                     # Empty = use OPENAI_MODEL from .env
  background_model: ""          # Optional: episodes, watch checks
  worker_model: ""              # Optional: delegated workshop helpers
  context_messages: 30          # Rolling window of Discord messages
  context_tokens: 80000         # Session threshold: episodize + reseed past this
  web_search:
    enabled: true               # Client-side web search/fetch tools

discord:
  backfill_days: 30             # 0 = unlimited; widening deepens indexed history

workshop:
  enabled: true                 # false = no sandbox execution anywhere
  default_setting: "container"  # container | off, per bot
  scopes: {}                    # per-ID overrides (server, channel, thread, DM)

skills:
  default_skills: []            # preload a frequently used guide into context
```

See `bots/alpha.yaml.example` for the complete annotated reference, and
`CHANGELOG.md` → *Upgrading from 0.4.x* if you're migrating an existing
config.

---

## Deployment (Self-Hosted)

### Systemd (Linux VPS)

```ini
# /etc/systemd/system/discord-bot.service
[Unit]
Description=Discord Agent
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/discord-agents
ExecStart=/usr/bin/python3 bot_manager.py spawn alpha
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now discord-bot
```

For the workshop, the process needs access to the virtualization backend
`microsandbox` uses; without it the bot exits blocked at startup. Set
`workshop.enabled: false` on hosts that cannot provide it. Run the supervisor
as the same user as the bots so process management, tokens, and workshop
state stay consistent.

### PM2

```bash
pm2 start bot_manager.py --name discord-bot --interpreter python3 -- spawn alpha
pm2 save && pm2 startup
```

### Docker

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python3", "bot_manager.py", "spawn", "alpha"]
```

```bash
docker build -t discord-agent .
docker run -d --name bot --env-file .env discord-agent
```

Workshop sandboxes need a Docker setup that permits the microsandbox
runtime; otherwise disable the workshop in the bot YAML.

### Screen/Tmux (simple)

```bash
screen -S discord-bot
python bot_manager.py spawn alpha    # Ctrl+A, D to detach
```

---

## Backup & Restore

```bash
# Export configuration + data to a portable zip
python deployment_tool.py export
python deployment_tool.py export --exclude logs

# Import on another machine (preview first)
python deployment_tool.py import --input backup.zip --dry-run
python deployment_tool.py import --input backup.zip
```

---

## Security & Safety

**Full policy:** [SECURITY.md](SECURITY.md) — including vulnerability
reporting via [GitHub Security Advisories](../../security/advisories/new)
(please don't open public issues for security problems).

- **API keys** live in environment variables only; `.env` is git-ignored.
  Rotate immediately if exposed.
- **The dashboard is local and authenticated** — loopback-only binding,
  `Host`/`Origin` checks against CSRF and DNS rebinding, framing denied, and a
  per-install `X-DA-Token` on every API route.
- **Workshop egress is default-deny** — the sandbox can reach package mirrors
  on its preset allowlist; any other host requires an operator approval DM or
  dashboard decision. Denials expire, requests expire after 24 hours, and
  operators are resolved from config or the Discord application owner.
- **Rate limiting** is per-channel with preset tiers; the bot also silences
  itself after consecutive ignored messages, with an automatic trial message
  after 30 minutes.
- **Web search** runs client-side through the bot's own process; page
  content is treated as untrusted data, and `web_fetch` rejects URLs that
  only appeared inside tool output.
- **Vaults** mechanically seal a channel's or server's content (search,
  memory, attachments, repository) — with normalized memory paths and
  write containment in the vault's own tree.
- **DM privacy** is enforced in the storage layer, not just the prompt: DM
  messages and files never surface outside their own DM.
- **Deletion handling** — deleting a Discord message purges it from the bot's
  storage and attachment pipeline, including messages older than the current
  process.
- **Graceful shutdown** on SIGTERM/SIGINT and supervised stdin; database
  connections close cleanly, and a stop is not mistaken for a crash.

---

## Documentation

- **[README.md](README.md)** — this file: quick start and overview
- **[OPENAI_COMPATIBILITY.md](OPENAI_COMPATIBILITY.md)** — supported
  endpoints, translation behavior, and what the OpenAI-only migration removed
- **[NATIVE_MESSAGING.md](NATIVE_MESSAGING.md)** — the `send_message` design,
  reply anchoring, attachments, and silence semantics
- **[skills/README.md](skills/README.md)** — skill layout, bundled skills, and
  how text-only vs workshop skills are offered
- **[ROADMAP.md](ROADMAP.md)** — where the project is headed
- **[CHANGELOG.md](CHANGELOG.md)** — version history and upgrade notes
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — running dev and production installs
  side by side, and the release/update workflow
- **[SECURITY.md](SECURITY.md)** — security policy
- **`PLAN-upstream-port-0.15.7.md` / `PROGRESS-upstream-port-0.15.7.md`** —
  the fork's upstream port plan and completion record
- **[REDESIGN.md](REDESIGN.md)** — the v0.6.0 architecture design document
  (episodic sessions, context layout); historical
- `docs/archive/` — historical design documents from earlier versions

---

## Project Stats

- ~50 core modules (including the workshop package and OpenAI-compatible
  client), 15 tool modules, and the supervisor package
- 73 regression tests covering the ported security, concurrency, lifecycle,
  history, skills, workshop, and model-role paths
- Validated by live scenario campaigns on a real Discord server: narrative
  scenarios, pre-release code audits, and release stress tests every cycle —
  including wire-level bugs that mocked tests structurally can't catch (see
  CHANGELOG)

---

## License

No license file yet — all rights reserved until one is added.

---

## Acknowledgments

Built with:

- [OpenAI](https://openai.com/) and the OpenAI-compatible ecosystem — model API
- [discord.py](https://discordpy.readthedocs.io/) — Discord integration
- [aiosqlite](https://github.com/omnilib/aiosqlite) — async SQLite
- [microsandbox](https://github.com/microsandbox/microsandbox) — optional
  workshop sandbox runtime
- [Mineflayer](https://github.com/PrismarineJS/mineflayer) — optional
  Minecraft bridge

---

## Roadmap

See [ROADMAP.md](ROADMAP.md). Native messaging and the provider-neutral
0.13–0.15 work (workshop, skills, model roles, lifecycle fixes) are in this
fork; next is **1.0** — polish, soak testing, and a config freeze. Anthropic-
only upstream themes remain out of scope for this fork.

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.
