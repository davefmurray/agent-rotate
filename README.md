```text
    _    ____ _____ _   _ _____   ____   ___ _____  _  _____ _____
   / \  / ___| ____| \ | |_   _| |  _ \ / _ \_   _|/ \|_   _| ____|
  / _ \| |  _|  _| |  \| | | |   | |_) | | | || | / _ \ | | |  _|
 / ___ \ |_| | |___| |\  | | |   |  _ <| |_| || |/ ___ \| | | |___
/_/   \_\____|_____|_| \_| |_|   |_| \_\\___/ |_/_/   \_\_| |_____|

              CLAUDE CODE + CODEX  /  ONE LOCAL ROUTER
```

<h1 align="center">Agent Rotate</h1>

<p align="center"><strong>Keep coding when one account reaches its quota.</strong><br>
Automatic account failover for the real Claude Code and Codex terminal CLIs.</p>

<p align="center">
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/version-0.2.0-2563eb" alt="Version 0.2.0"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11 or newer"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-475569" alt="macOS and Linux"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-059669" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#features">Features</a> ·
  <a href="docs/commands.md">Command guide</a> ·
  <a href="#faq">FAQ</a> ·
  <a href="SETUP.md">Setup with an agent</a>
</p>

Agent Rotate routes model requests through an authenticated local proxy. When an account returns a quota rejection **before response delivery**, the router can retry that rejected request with another account of the same provider. Your native CLI process and conversation stay open.

**Verified on both providers:** injected HTTP 429 → second real account → successful real response, including after a completed tool call. Version 0.2.0 has 82 passing automated tests and macOS/Linux CI. See [verification evidence](docs/verification.md) and [CI results](https://github.com/davefmurray/agent-rotate/actions/workflows/ci.yml). Natural provider quota exhaustion remains unverified.

<details>
<summary>On this page</summary>

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [A session at quota](#a-session-at-quota)
- [Everyday commands](#everyday-commands)
- [Usage dashboard and menu bar](#usage-dashboard-and-menu-bar)
- [Project account pools](#project-account-pools)
- [Optional routing policies](#optional-routing-policies)
- [Resume a saved session](#resume-a-saved-session)
- [Agent plugins and MCP](#agent-plugins-and-mcp)
- [Delegated jobs](#delegated-jobs)
- [Notifications and startup services](#notifications-and-startup-services)
- [How switching works](#how-switching-works)
- [Compatibility and limits](#compatibility-and-limits)
- [FAQ](#faq)
- [Update or uninstall](#update-or-uninstall)
- [Development and documentation](#development-and-documentation)
- [Credits and license](#credits-and-license)

</details>

## Features

| | Feature | What you get |
| :--: | --- | --- |
| 🔄 | In-session failover | Retry a quota-rejected request using another eligible account while the native CLI stays running. |
| 🧭 | Separate account pools | Claude and Codex keep their own accounts, with ordered fallback chains and project directory mappings. |
| 📊 | Shared quota monitoring | Coordinated polling, reset/cooldown timers, last-good readings, and visible stale/error state. |
| 🖥️ | Terminal + macOS displays | A live terminal dashboard and optional menu bar showing usage and actual routed session accounts. |
| 📈 | Quota planning | Advisory weekly pace and usage estimates, plus opt-in consume-first and proactive routing. |
| 🩺 | Credential health | Quarantine for revoked logins, recovery checks, and account-specific sign-in repair instructions. |
| ↩️ | Native session resume | Browse saved session headers and resume through the correct project pool. |
| 🔌 | Skills, plugins + MCP | Claude/Codex agent instructions and six cached, read-only MCP tools by default. |
| 🛠️ | Explicit native jobs | Separate restricted jobs with timeout, cancellation, private final results, and optional MCP delegation. |
| 🔔 | Optional desktop alerts | Local switch/health notifications and explicit launchd or user-systemd service installation. |
| 🐚 | Shell + automation support | Bash/zsh/fish completion scripts, structured JSON status, and a private local status feed. |
| 🔐 | Native credential ownership | Claude Rotate and Codex retain their credential stores and refresh logic; routing preserves model and native permissions. |

## Requirements

- **macOS or Linux**, **Python 3.11+**, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- The current native [Claude Code](https://code.claude.com/docs/en/setup) and/or [Codex CLI](https://github.com/openai/codex), installed and signed in for the providers you use.
- **Two available accounts for each provider where you want failover.** A Claude account cannot serve as a Codex fallback, or vice versa.
- GitHub access to this repository. It is currently **private**; the clone instructions below use the authenticated [GitHub CLI](https://cli.github.com/).

The menu bar requires macOS and the optional `menubar` extra. Native Windows, Desktop/IDE routing, and cloud sessions are outside the current scope.

## Quick start

### 1. Install

Clone using your existing GitHub login, then install the CLI:

```sh
gh repo clone davefmurray/agent-rotate
cd agent-rotate
uv tool install .
```

For the optional macOS menu bar, use this install command instead:

```sh
uv tool install '.[menubar]'
```

If you already installed the base package, add `--force` to replace that installation with the extra. If the clone needs authentication, run `gh auth login` with an account that has repository access. If `agent-rotate` is missing from your shell afterward, run `uv tool update-shell` and open a new terminal.

<details>
<summary>Direct Git installation</summary>

If Git is already authenticated for private GitHub repositories:

```sh
uv tool install git+https://github.com/davefmurray/agent-rotate

# With the macOS menu bar:
uv tool install 'agent-rotate[menubar] @ git+https://github.com/davefmurray/agent-rotate'
```

</details>

### 2. Register your accounts

Choose either provider, or set up both. Account names such as `personal` and `secondary` are local labels you choose.

**Codex:** reference your existing file-based ChatGPT login and sign in to a second account:

```sh
agent-rotate add-codex personal --home ~/.codex
agent-rotate login codex secondary
```

If your current Codex login uses the keychain or has no `auth.json`, use `agent-rotate login codex personal` for the first account too. New registrations use separate native credential homes. Repairing an existing registered name reuses its home.

**Claude:** import the accounts you already have in Claude Rotate:

```sh
agent-rotate import-claude
```

Or register accounts through Claude Rotate's browser login flow:

```sh
agent-rotate login claude personal --email you@example.com
agent-rotate login claude secondary --email you@another.example
```

Complete each browser sign-in yourself. Keep the normal native CLI login (`codex login` / `claude auth login`) for native account features and connectors. Agent Rotate changes model-request credentials; native connectors retain their original login.

### 3. Check and launch

```sh
agent-rotate list
agent-rotate doctor
agent-rotate status

agent-rotate run claude
# Or:
agent-rotate run codex
```

**Launch through `agent-rotate run` to get automatic failover.** Existing sessions and direct `claude` / `codex` launches keep their existing behavior. Installing the skill, MCP server, or monitor alone does not add routing to an already-running host.

## A session at quota

Illustrative router output; account labels and cooldown time are examples:

```text
$ agent-rotate run codex

[agent-rotate] codex: using personal
... native Codex session continues ...
[agent-rotate] personal: quota reached; cooling down for 120s
[agent-rotate] codex: personal → secondary
... the accepted response streams into the same session ...
```

The default is **sticky routing**: each session keeps its account while it remains eligible. Other sessions keep independent account choices, and shared cooldowns stop them from immediately reusing a quota-rejected account for the same model.

## Everyday commands

Put Agent Rotate options **before the provider** in `run`. Arguments after `claude` or `codex` belong to the native CLI.

| Task | Command |
| --- | --- |
| Start Claude / Codex | `agent-rotate run claude` / `agent-rotate run codex` |
| Pass native CLI arguments | `agent-rotate run codex exec --sandbox read-only 'Explain this repository'` |
| Use exactly one account | `agent-rotate run --account personal codex` |
| Check usage | `agent-rotate status` |
| Get cached JSON without provider requests | `agent-rotate status --cached --json` |
| Watch the terminal dashboard | `agent-rotate watch` |
| Open the macOS menu bar | `agent-rotate menubar` |
| See each live router's account | `agent-rotate sessions` |
| Inspect routing history | `agent-rotate history` |
| Filter history to one router | `agent-rotate history --session ROUTER_ID` |
| Check credential health | `agent-rotate health --check` |
| Disable / enable an account | `agent-rotate disable codex secondary` / `agent-rotate enable codex secondary` |
| Print shell completions | `agent-rotate completion zsh` (also `bash`, `fish`) |
| Get command help | `agent-rotate --help` / `agent-rotate pool --help` |

`--account` is a hard restriction: it leaves no fallback to another account. Completion commands print scripts for your shell's completion mechanism.

## Usage dashboard and menu bar

```sh
agent-rotate watch               # live terminal display; Ctrl-C closes it
agent-rotate watch --once        # one snapshot
agent-rotate watch --json        # recurring JSON snapshots
agent-rotate menubar             # macOS with the optional extra
```

See quota windows, usage bars, reset/cooldown countdowns, reading age, account health, and the account serving each live router. The menu bar also provides account enable/disable controls and an alerts toggle. Quitting it stops its collector.

Displays share a collector with the routers. Refreshing the screen does not require another provider request: per-account leases coordinate polls, and failures trigger backoff. A failed usage poll retains the last good reading with visible age/error markers. Usage-endpoint 429s are handled separately from inference cooldowns.

Weekly pace and exhaustion estimates are **advisory** and require sufficient fresh data. `watch` and `daemon` also publish a private `status.json` feed. See [monitoring details](docs/commands.md#watch-usage-and-actual-session-identity).

## Project account pools

Create a pool from account names you have already registered, then bind it to a directory:

```sh
agent-rotate pool set codex work personal secondary
agent-rotate map --provider codex --pool work ~/work
agent-rotate run --pool work --strategy ordered codex

# Claude pools are configured separately:
agent-rotate pool set claude work personal secondary
agent-rotate map --provider claude --pool work ~/work

agent-rotate pool list
agent-rotate map
```

Sessions started inside `~/work` or its subdirectories use the nearest mapped pool, including when Codex selects its directory with `-C`/`--cd`. Explicit `--pool` or `--account` overrides that mapping. `ordered` follows the member order when selecting an account, then stays sticky.

Failover stays within the selected pool. A missing or empty mapped pool stops routing until repaired or unmapped; it never silently expands to all accounts. Use `agent-rotate unmap codex ~/work` to remove a binding. [Pool reference](docs/commands.md#account-pools-and-automatic-directory-selection).

## Optional routing policies

| Setting | Default | Optional behavior |
| --- | --- | --- |
| `strategy` | `sticky` | `ordered` follows pool order; `consume-first` favors usable accounts with the soonest known weekly reset at selection/failover. |
| `threshold` | Unset | A value from 50–99 allows proactive switching between independent requests. |
| `notifications` | `false` | Local desktop alerts for routing/health transitions. |

```sh
# Apply only to this invocation:
agent-rotate run --strategy consume-first claude
agent-rotate run --threshold 90 codex

# Or save a default, inspect it, and restore it:
agent-rotate config set threshold 90
agent-rotate config
agent-rotate config unset threshold
```

Proactive switching requires fresh usage, at least five minutes since the previous account change, and a candidate below the threshold with at least ten percentage points of extra headroom. It is suppressed while another request is in flight or for compressed/incremental continuations. [Policy details](docs/commands.md#quota-planning-and-opt-in-proactive-switching).

## Resume a saved session

```sh
agent-rotate sessions saved --provider codex
agent-rotate resume codex                    # interactive picker
agent-rotate resume claude SESSION_ID

# Native resume commands also work through the wrapper:
agent-rotate run codex resume SESSION_ID
agent-rotate run claude --resume SESSION_ID
```

The picker reads a bounded set of native session headers and resumes through the session's directory mapping. Native CLIs retain ownership of their history. The browser does not copy transcripts between account homes; use native resume flags for older sessions outside its index.

## Agent plugins and MCP

The repo includes a `/rotation` skill, Claude/Codex plugin manifests, and `.mcp.json`. Load the local plugin through your client's plugin workflow; for a routed Claude session:

```sh
agent-rotate run claude --plugin-dir /absolute/path/to/agent-rotate
```

Alternatively, register the **read-only** MCP server directly:

```sh
codex mcp add agent-rotate -- agent-rotate mcp
claude mcp add --scope user agent-rotate -- agent-rotate mcp
```

Use plugin loading or direct MCP registration as appropriate; loading both can expose duplicate tools. Restart the host to discover new registrations.

| MCP tool | Purpose |
| --- | --- |
| `agent_rotate_accounts` | Cached usage, forecasts, and credential health |
| `agent_rotate_current_session` | This host's routed account, when launched through the wrapper |
| `agent_rotate_sessions` | Live routers and their account/pool/directory |
| `agent_rotate_history` | Bounded routing metadata |
| `agent_rotate_pools` | Account pools and directory bindings |
| `agent_rotate_monitor` | Cancellable wait for session state changes |

These tools read cached metadata. They do not make provider inference calls or repair their host's HTTP transport. For an agent-led install, start with [SETUP.md](SETUP.md); contributors should also read [AGENTS.md](AGENTS.md).

## Delegated jobs

Explicit jobs launch separate native sessions behind their own routers. They consume quota and default to Codex read-only sandboxing or Claude plan permissions.

```sh
# Put the requested task in task.txt; the prompt is passed privately through stdin.
agent-rotate job start codex --cwd ~/work/app --prompt-file task.txt
agent-rotate job list
agent-rotate job result JOB_ID
agent-rotate job cancel JOB_ID
agent-rotate job forget JOB_ID
```

Timeout defaults to ten minutes; `--timeout` accepts 10–3600 seconds. Only completed final answers are retained, in private artifacts capped at 1 MiB. `job forget` removes a finished/interrupted job and its result. Jobs never restart automatically.

MCP delegation is off in the shipped plugin. Explicitly enable it for a trusted workspace with `agent-rotate mcp --allow-delegation --workspace /absolute/project/path`. This adds workspace-bound delegate/list/result/cancel tools with restricted access. CLI workspace-write is a separate opt-in. [Full job guide](docs/commands.md#explicit-delegated-jobs).

## Notifications and startup services

All of these are opt-in:

```sh
agent-rotate config set notifications true
agent-rotate config set notifications false

agent-rotate daemon                  # foreground collector + status feed
agent-rotate service status
agent-rotate service install         # macOS launchd / Linux user-systemd
agent-rotate service remove
```

For macOS menu-bar startup, use `agent-rotate service install --kind menubar`; remove it with the same `--kind` option. OS notification permissions still apply. The background collector monitors usage; routed sessions must still start through `agent-rotate run`. [Service details](docs/commands.md#local-notifications-and-background-services).

## How switching works

```text
 Native Claude Code / Codex CLI
              |
              | authenticated localhost HTTP/SSE
              v
      Per-session router <----> Shared quota / cooldown metadata
              |
              +---- account A ----> Official provider
              |                         |
              |                  quota rejection
              |                  before delivery
              v
       Cool down account A
              |
              +---- account B ----> Official provider
                                        |
                                  accepted response
                                        |
                                        v
                              Same native CLI session
```

Each account is attempted at most once for a quota rejection within one incoming request. Retry-After and provider reset data control cooldowns. Once response bytes reach the client, the router cannot replay that request. If every eligible account is unavailable, it returns a bounded failure with a retry delay.

The proxy binds only to loopback, requires a per-process capability key, uses fixed official upstream hosts, and refuses credential-bearing redirects. Credentials remain with Claude Rotate or native Codex. Routing metadata excludes tokens, prompts, tool payloads, and response bodies; explicit job results are stored separately. Read [architecture](docs/architecture.md) and [security](SECURITY.md).

## Compatibility and limits

| Situation | Behavior |
| --- | --- |
| Inference HTTP 429 before response delivery | Cool down the account and try another eligible account of the same provider. |
| Initial structured SSE quota error | Fail over before forwarding any event. |
| Response already partially delivered | Forward/close the stream; never replay partial work. |
| Generic 5xx, connection loss, or timeout | Surface the error; the native CLI owns recovery. |
| HTTP 401 | Ask the credential owner to refresh once; a persistent rejection quarantines the account. |
| Opaque/compressed or incremental continuation | Preserve its account binding; it cannot switch to another account. |
| All eligible accounts unavailable | Return exhaustion and a retry delay; no retry loop. |
| Native account labels / connectors | May retain the original CLI login; inspect Agent Rotate sessions for routed identity. |
| Desktop, IDE, Remote Control, or cloud sessions | No automatic routing; current scope is the wrapper-launched local CLI. |

The requested provider, model, billing mode, approvals, and sandbox settings remain unchanged during failover. Account switches can cause prompt-cache misses and extra usage. Long encrypted/compacted history portability remains a compatibility limit. [Tested versions and evidence](docs/verification.md).

## FAQ

**Will it switch on 429 in the middle of a session?**

Yes, for eligible quota rejections before response delivery in a wrapper-launched session. The same native process stays open. A response that has already started streaming cannot be replayed.

**Does it keep checking usage while I work?**

Yes. Routers and displays share coordinated usage polling with backoff. The default account choice remains sticky; proactive thresholds are optional.

**Why does native Codex or Claude show a different account?**

Native account features can still reflect the original login. Use `agent-rotate sessions` or the current-session MCP tool to see the account serving routed model requests.

**How do I repair an expired or revoked login?**

Run `agent-rotate health`, then its suggested command. For example: `agent-rotate login codex personal` or `agent-rotate login claude personal --replace`. The account owner completes browser sign-in.

**Can I use one provider without setting up the other?**

Yes. Register the accounts for that provider and launch its wrapper. `doctor` also reports the other provider's installation state; fallback capacity stays within each provider.

**Does installation change my aliases or existing Claude Rotate sync?**

No. Launch the wrapper explicitly. The original sync remains responsible for Claude credentials, and your native CLI retains its terminal controls and permissions.

## Update or uninstall

For a clone-based installation, run this from the repository directory:

```sh
git pull --ff-only
uv tool install --force --reinstall-package agent-rotate --no-cache .

# Preserve the macOS menu-bar extra when installed:
uv tool install --force --reinstall-package agent-rotate --no-cache '.[menubar]'
```

Choose the install command matching your setup. The no-cache option ensures a local source update rebuilds the installed package. For a direct Git installation, rerun its install command with `--force --reinstall-package agent-rotate --no-cache`.

To uninstall, close routed sessions and the menu bar first. Remove only the optional registrations/services you installed, then remove the CLI:

```sh
# If these startup services were installed:
agent-rotate service remove
agent-rotate service remove --kind menubar  # macOS only

# If you used direct MCP registration:
codex mcp remove agent-rotate
claude mcp remove agent-rotate --scope user

uv tool uninstall agent-rotate
```

For a plugin installation, also remove it through the host's plugin workflow. Native credential stores and local account metadata remain in place. Intentional account/data removal should be handled separately.

## Development and documentation

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
uv build
```

Tests use fake upstreams and synthetic credentials. The manual native verification script consumes a small amount of real quota and is documented separately; synthetic quota errors are never presented as naturally exhausted provider accounts.

| Document | Start here for |
| --- | --- |
| [Command guide](docs/commands.md) | Every management feature, defaults, flags, and cleanup |
| [Setup checklist](SETUP.md) | Installation with a coding agent |
| [Agent instructions](AGENTS.md) | Engineering rules and required verification |
| [Architecture](docs/architecture.md) | Routing, retry boundaries, monitoring, and process lifecycle |
| [Security](SECURITY.md) | Credential ownership, local transport, and retained data |
| [Verification](docs/verification.md) | Native smoke checks, automated coverage, and limits |
| [MCP evaluation](docs/mcp-evaluation.md) | Agent-tool behavior scenarios |
| [Sources](docs/sources.md) · [Feature research](docs/feature-research.md) | Compatibility references and reviewed ideas |

## Credits and license

[MIT](LICENSE). See [NOTICE](NOTICE) for attribution.

- [evrenverse/claude-rotate](https://github.com/evrenverse/claude-rotate) — pinned dependency for Claude OAuth and account ownership.
- [vaskoyudha/CodexCLI-Rotate](https://github.com/vaskoyudha/CodexCLI-Rotate) — reviewed account-management ideas and README presentation inspiration.
- [realiti4/claude-swap](https://github.com/realiti4/claude-swap) and [uwuclxdy/clauth](https://github.com/uwuclxdy/clauth) — reviewed monitoring, session, and workflow ideas.

The routing and management implementation lives in this repository. External implementation code from the three feature-research projects was not copied.
