# Agent Rotate

Keep the real **Claude Code and Codex terminal sessions** running when a subscription reaches its quota. Agent Rotate routes model requests through an authenticated local HTTP/SSE proxy. A rejected request can move to another account without restarting the CLI or replaying the conversation.

**0.2.0 adds shared quota monitoring, a terminal dashboard and macOS menu bar, project account pools, optional proactive policies, credential health, cached MCP tools, and explicit native jobs.** Both real CLIs have passed injected-429 tests followed by successful inference on the second real account, including a switch after one completed tool call ([verification](docs/verification.md)). It combines [Claude Rotate](https://github.com/evrenverse/claude-rotate)'s OAuth/account ownership with a native Codex account adapter and request router.

See the [complete command guide](docs/commands.md) for the new features, opt-in settings, and limits.

## What improves on launch-time rotation

- Automatic failover on HTTP 429, inside the existing native session.
- Separate Claude and Codex account pools; the requested model stays unchanged.
- Sticky routing per session, avoiding unnecessary account/cache churn.
- Shared per-model cooldowns across concurrently running routers; honors Retry-After and provider reset times.
- Live usage windows, enable/disable controls, account restriction, and a metadata-only routing history.
- Existing credential references instead of a second copied token vault.
- Loopback-only ephemeral ports, a per-process capability key, fixed upstream routes, no credential-bearing redirects.
- Native CLI approvals and sandbox flags pass through unchanged.
- Agent instructions and Claude/Codex plugin manifests.

## Install and register accounts

Requires macOS/Linux, Python 3.11+, [uv](https://docs.astral.sh/uv/), and current native Claude Code / Codex CLIs. Windows native is not supported yet.

```sh
uv tool install git+https://github.com/davefmurray/agent-rotate

# macOS, including the optional menu-bar interface:
uv tool install 'agent-rotate[menubar] @ git+https://github.com/davefmurray/agent-rotate'

# Reuse the accounts already registered with Claude Rotate. No token copies.
agent-rotate import-claude

# Reference the current Codex file-based subscription login.
agent-rotate add-codex personal --home ~/.codex

# Sign into another ChatGPT subscription in a separate native credential directory.
agent-rotate login codex work

# Optional: add another Claude subscription using Claude Rotate's OAuth flow.
agent-rotate login claude work --email you@example.com

agent-rotate doctor
agent-rotate status
```

Browser OAuth is completed by the account owner. No tokens belong in arguments, chat, shell history, or Git. Codex `login` writes only inside Agent Rotate's dedicated account home. `add-codex` requires file-based ChatGPT credentials; for an existing keychain login use the separate `login` command. Both native CLIs must also have their normal subscription login for account features (`claude auth login` / `codex login`). Native connectors keep that original account; the router changes model-request credentials only.

## Run

```sh
agent-rotate run claude
agent-rotate run codex

# Existing sessions and normal CLI flags still work.
agent-rotate run claude --resume SESSION_ID
agent-rotate run codex resume SESSION_ID
agent-rotate run codex exec --sandbox read-only 'Explain this repository'

# A hard restriction: no fallback to other accounts.
agent-rotate run --account work codex

agent-rotate disable codex work
agent-rotate enable codex work
agent-rotate status --json
agent-rotate status --cached
agent-rotate history
agent-rotate watch
agent-rotate menubar  # macOS with the optional extra
```

Run the wrapper to get in-session routing. Your existing `claude` alias and direct `codex` command keep their existing behavior. Open sessions aren't retrofitted automatically. Ctrl-C remains owned by the native CLI. Closing the native CLI shuts down its router.

## What happens at quota

1. The native CLI submits its next model request through the local router.
2. If the provider returns HTTP 429, the router puts that account into cooldown.
3. It sends the **same rejected request** to another eligible account of the same provider.
4. The successful response streams back into the same native terminal session.
5. If all accounts are unavailable, the router returns 429 with the next retry delay. It does not spin or silently enable API billing.

This is request-level switching. A switch can cause a provider prompt-cache miss and additional quota consumption. A skill alone cannot perform this recovery because the skill's host model is the component being rate-limited.

## Boundaries

| Situation | Behavior |
| --- | --- |
| HTTP 429 before response delivery | Cool down that account and try another, once per account per request |
| First SSE event is a structured quota rejection | Same failover, before forwarding any event |
| Some response bytes already reached the CLI | Forward/close the stream; never replay it |
| Generic 5xx, connection loss, or timeout | Surface error; native CLI owns recovery |
| HTTP 401 | Ask credential owner to refresh once; no quota-style account switching |
| Codex WebSocket continuation | Routed sessions use HTTP/SSE and uncompressed requests; incremental `previous_response_id` and opaque compressed requests are not switched |
| Remote Control, IDE, Desktop app, cloud sessions | Not automatically routed; scope is the local CLI process launched by `run` |
| Native account/usage display | May show the original CLI login; use `agent-rotate status`/`history` for routed accounts |
| All quota windows full / one account only | Cannot manufacture capacity; returns exhaustion |

Routing is to the official provider hosts. No provider-to-provider fallback, API billing fallback, automatic model downgrade, or approval bypass is implemented. Provider subscription availability and account restrictions still apply.

## Agent plugin

The repository includes `.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, and `skills/rotation/SKILL.md`. Install the plugin through your agent's local/plugin workflow, or load it in Claude with `claude --plugin-dir /path/to/agent-rotate`. The skill exposes setup/status/launch instructions; the CLI router does the switching. See [AGENTS.md](AGENTS.md) for implementation rules and [SETUP.md](SETUP.md) for an agent-led installation checklist.

The plugin also loads `.mcp.json` for cached, read-only account/session tools. Delegated jobs require separate explicit opt-in; see [MCP and jobs](docs/commands.md#mcp-and-plugin).

## Develop

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
uv build
```

Tests use local fake upstreams and synthetic credentials. They test rejection/retry, cooldown persistence, stream delivery, no partial replay, account identity headers, redirects, and credential-safe metadata. They do not assert that real provider accounts have hit quota. See [architecture](docs/architecture.md), [sources](docs/sources.md), and [security](SECURITY.md).
