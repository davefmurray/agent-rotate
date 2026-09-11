# Agent Rotate 0.2 commands

The router remains sticky by default and only retries explicitly quota-rejected requests before response delivery. New displays and MCP tools use the same local metadata. Optional policies, notifications, and services start only when you enable them.

## Watch usage and actual session identity

```sh
agent-rotate status                  # fetch due usage; display cached readings otherwise
agent-rotate status --cached --json  # no provider requests
agent-rotate watch                   # live terminal dashboard; Ctrl-C closes it
agent-rotate watch --once            # one dashboard snapshot
agent-rotate watch --json            # JSON snapshots every five seconds
agent-rotate sessions                # live routers and the account serving each
agent-rotate history --session ROUTER_ID
agent-rotate menubar                 # macOS, with the optional menubar extra
```

The dashboard includes quota bars, reset/cooldown countdowns, reading age, health, actual per-router accounts, and last routing decisions. The macOS menu bar shows cached usage and live sessions and can enable/disable accounts and toggle alerts. Closing it stops the usage monitor it owns.

[View the dashboard previews](../README.md#preview) for sample quota, cooldown, stale-reading, and login-health states. The images use the actual terminal renderer with synthetic data.

Display refresh does not imply an API request. A shared SQLite lease allows one eligible poll per account across processes; normal polling backs off for idle accounts, failures, and usage-endpoint 429s. The last successful reading stays visible, with stale/error markers. Polling starts conservatively around 2–5 minutes and may slow further. Provider-specific limits can change; these intervals are not provider guarantees. Native credential owners still perform refresh.

`watch` and `daemon` atomically publish `status.json` in the Agent Rotate data directory, mode 0600. It contains `schema_version: 1`, generation/observation times, accounts, pools, and live sessions. It contains no gateway capability key, tokens, prompts, or response bodies. Consumers must check observation age; a file can outlive its publisher.

## Account pools and automatic directory selection

```sh
agent-rotate pool set codex work work-primary work-secondary
agent-rotate pool set claude work work-primary work-secondary
agent-rotate pool list
agent-rotate run --pool work codex
agent-rotate run --pool work --strategy ordered claude

agent-rotate map --provider codex --pool work ~/work
agent-rotate map --provider claude --pool work ~/work
agent-rotate map
agent-rotate unmap codex ~/work
agent-rotate pool remove codex work
```

Use already registered account names; a pool cannot contain accounts from another provider. `pool set` replaces the ordered member list and acts as the fallback-chain editor. `ordered` follows that order when choosing an account; normal sticky routing stays with its current eligible account. A disabled or quarantined member is skipped, and failover never leaves the selected pool.

The nearest mapped ancestor wins, including from subdirectories and normalized symlink paths. Codex's native `-C`/`--cd` directory flag also participates. Explicit `--pool` or `--account` overrides a mapping. `--account` remains a hard single-account restriction. A deleted/missing/empty mapped pool fails closed; remove the mapping explicitly to restore default selection. Mappings are local user metadata, never loaded from a repository configuration file.

## Quota planning and opt-in proactive switching

```sh
agent-rotate run --strategy consume-first claude
agent-rotate run --threshold 90 codex
agent-rotate config set strategy consume-first
agent-rotate config set threshold 90
agent-rotate config unset threshold
agent-rotate config unset strategy
agent-rotate config
```

`consume-first` favors usable accounts whose known weekly quota resets soonest when initially selecting or failing over. It does not continuously churn accounts. Unknown reset durations are not guessed. Codex windows use provider-reported durations; unknown model buckets remain conservatively unmapped unless their identifier matches the requested model.

The optional 50–99% threshold can select another account **between independent requests** when the active account is near exhaustion. It requires fresh readings, five minutes since the previous account change, and at least ten percentage points of additional headroom on a candidate below the threshold. It is suppressed when another request is in flight or the request is compressed/incremental. Native permissions, provider, model, and billing mode remain unchanged.

Weekly pace warnings require a known weekly duration and at least a day of elapsed time. Short-term usage-rate/ETA estimates require at least three distinct readings in a recent active period, discard resets/long gaps, and disappear with stale data. These are explicitly advisory; bursty usage makes exact exhaustion times unreliable. They never trigger switching by themselves and never claim API-equivalent cost is an actual subscription bill.

## Local notifications and background services

```sh
agent-rotate config set notifications true
agent-rotate config set notifications false
agent-rotate daemon                  # foreground shared usage collector + status feed
agent-rotate service status
agent-rotate service install         # explicit macOS launchd / Linux user-systemd opt-in
agent-rotate service remove
agent-rotate service install --kind menubar  # macOS only
agent-rotate service remove --kind menubar
```

Local desktop notifications report account switches, exhaustion/recovery, and health changes, deduplicated through shared state. OS notification permissions still apply. Services manage only Agent Rotate's own files. They do not change Claude Rotate's sync job, shell aliases, or global native credentials. Remote webhooks and remote account-control APIs are not enabled or implemented.

## Credential health and repair

```sh
agent-rotate health
agent-rotate health --check
agent-rotate doctor
agent-rotate login codex ACCOUNT
agent-rotate login claude ACCOUNT --replace
```

Explicit revoked-login errors or a model request still returning 401 after native refresh quarantine that account. Network failures and usage API 429s do not. Health checks honor the shared usage polling schedule. A successful authenticated usage read recovers a quarantined account. A successful re-login clears its quarantine; registering an existing Codex name reuses its original credential home. Claude re-login can use the email already held by Claude Rotate without displaying it. New Claude registrations still require `--email`.

## Native session browser and resume

```sh
agent-rotate sessions saved --provider codex
agent-rotate sessions saved --provider claude
agent-rotate resume codex             # local interactive picker
agent-rotate resume claude SESSION_ID
agent-rotate resume codex SESSION_ID --pool work
```

The browser reads only bounded native session headers and returns IDs, directories, and modification times. It inspects at most 1,000 files and lists at most 500 entries; it is not an exhaustive transcript search. The native CLI owns the history and resume behavior. Older sessions can still be resumed with `agent-rotate run PROVIDER` and native resume flags. No transcripts are copied between account homes.

## MCP and plugin

The repository's `.mcp.json` supplies `agent-rotate mcp` through either plugin manifest. It exposes six cached/read-only operations by default: accounts/forecasts, this session, live sessions, history, pools/mappings, and a cancellable state monitor. Every tool has annotations and a structured output schema. If the host was not launched through the wrapper, the current-session tool reports that truth instead of guessing a global account.

To register the read-only server directly in native clients:

```sh
codex mcp add agent-rotate -- agent-rotate mcp
claude mcp add --scope user agent-rotate -- agent-rotate mcp
```

Use direct registration or plugin loading as appropriate; loading both can expose duplicate tool entries. Restart the host to discover newly registered tools. This cannot retrofit HTTP routing into an already-running host process.

## Explicit delegated jobs

```sh
# Task text is supplied through stdin or a file, never as a process argument.
agent-rotate job start codex --account work-secondary --cwd ~/work/app --prompt-file task.txt
agent-rotate job start claude --pool work --cwd ~/work/app --model sonnet --prompt-file task.txt
agent-rotate job list
agent-rotate job result JOB_ID
agent-rotate job cancel JOB_ID
agent-rotate job forget JOB_ID
```

A job launches a separate native session behind its own router. It does not continue, replay, or repair the current conversation. It consumes real quota and is never automatically restarted. Defaults are a read-only Codex sandbox or Claude plan permissions, with native session persistence disabled. `--access workspace-write` is an explicit CLI opt-in to Codex workspace-write / Claude acceptEdits; permission prompts are not bypassed. Hooks and managed native policies still follow the native CLI's own behavior.

Timeout defaults to ten minutes (`--timeout 10` through `--timeout 3600` seconds). Cancellation and timeout stop the worker's native process group. Crashed workers show as interrupted after their heartbeat expires; they are not resumed automatically.

Only completed final answers are retained, at most 1 MiB, in a private per-job `result.txt`. Prompts remain in the parent/worker stdin pipe and memory. Tool transcripts and stderr are not retained by Agent Rotate. Job results can contain task-sensitive information: `job forget` deletes a completed/interrupted job and its result. Normal routing metadata still has no task content.

MCP delegation is disabled in the shipped plugin. To enable it in an explicitly trusted workspace, configure a separate stdio server with:

```sh
agent-rotate mcp --allow-delegation --workspace /absolute/project/path
```

This adds delegate/list/result/cancel tools. Delegation is fixed to that workspace and read-only access; results and cancellation are scoped to jobs in that workspace. The agent must have explicit user intent to launch a job. The CLI remains available for deliberate workspace-write jobs.

## Completion

```sh
agent-rotate completion bash
agent-rotate completion zsh
agent-rotate completion fish
```

These print completion scripts with dynamic account/pool names. Install them using your shell's normal completion mechanism; no startup file is edited automatically.
