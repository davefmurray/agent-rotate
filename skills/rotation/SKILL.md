---
name: rotation
description: Set up Agent Rotate for Claude and Codex, inspect quota and routed session identity, manage project account pools, resume native sessions, and run explicitly requested delegated jobs. Use for Agent Rotate dashboards, credential health, MCP tools, or in-session HTTP 429 routing.
---

# Agent Rotate

Use the `agent-rotate` executable. Read the repository README and SETUP.md for installation and current transport limits.

## Status

Run `agent-rotate status --json` to fetch due usage through the shared collector, or `status --cached --json` for no provider requests. Use `agent-rotate watch` for the terminal dashboard, `sessions` for live router identities, and `history --session ROUTER_ID` for routing metadata. `health` reports quarantine and repair commands. Show account handles, usage/reset windows, and unknown/stale readings clearly. Forecasts are advisory, not guarantees. Do not dump credential files or process environments.

When available, prefer the cached `agent_rotate_accounts`, `agent_rotate_current_session`, `agent_rotate_sessions`, `agent_rotate_history`, `agent_rotate_pools`, and cancellable `agent_rotate_monitor` MCP tools. Current-session identity is meaningful only for a wrapper-launched host; never guess a global active account. Native account labels and connectors may still use the original login.

## Setup

Import existing Claude Rotate account references using `agent-rotate import-claude`. For Codex use `agent-rotate add-codex NAME --home PATH` or `agent-rotate login codex NAME` in an interactive terminal. The human completes browser OAuth. New Codex logins have separate credential homes. Never fabricate tokens or cancellation dates.

## Launch and limits

`agent-rotate run claude` and `agent-rotate run codex` start the native CLI behind a per-session local router. Pass native resume arguments to continue a specific saved session. A host session already running outside the wrapper is not automatically protected by this skill.

`agent-rotate sessions saved --provider PROVIDER` lists bounded native session headers. `agent-rotate resume PROVIDER SESSION_ID` resumes through the mapped directory; omitting the ID opens an interactive picker. Native CLIs own history; do not copy transcripts between accounts.

The router retries a model request only on explicit quota rejection before any stream content is delivered. It preserves the model, provider, native approvals, and sandbox flags. It does not replay partial responses or execute tool operations itself. If every account is cooling down, report exhaustion and the next reset; do not enable paid API fallback or change models.

## Changes

Enable/disable accounts and edit pools/mappings as requested. `pool set PROVIDER POOL ACCOUNT...` sets the ordered fallback chain; `map --provider PROVIDER --pool POOL PATH` binds a project. Explicit `run --pool POOL PROVIDER` or `--account NAME` overrides mapping; an account is a hard restriction. Missing/empty mapped pools fail closed. Never widen one silently.

Sticky routing is the default. Optional `--strategy consume-first` and `--threshold 90` are documented in `docs/commands.md`; thresholds only switch between independent requests with dwell/headroom safeguards. Enable proactive settings, desktop notifications, startup services or delegation only within user-requested scope. Do not replace aliases, remove the original Claude Rotate sync job, or log out active sessions as part of checks.

## Explicit jobs

`agent-rotate job start PROVIDER --cwd PATH --prompt-file FILE` launches a separate restricted native session and consumes real quota. Supply prompts through stdin/file, never process arguments. Use `job list`, `job result JOB_ID`, `job cancel JOB_ID`, and `job forget JOB_ID` for lifecycle and private final-result cleanup. Jobs never repair this host conversation and never restart automatically.

The shipped MCP server is read-only. `mcp --allow-delegation --workspace /absolute/path` explicitly enables workspace-bound delegate/list/result/cancel tools. Only invoke delegation for an explicitly requested delegated task; account capacity alone is not authorization. MCP jobs stay read-only; CLI workspace-write requires deliberate opt-in. Preserve native approvals and sandboxing.
