# Architecture

Each `agent-rotate run PROVIDER` owns one ephemeral loopback router and one native CLI child. Other sessions have independent sticky account choices. Shared SQLite metadata stores account references, usage snapshots, cooldowns, the latest 500 routing outcomes, and bounded session events; it never stores OAuth secrets, prompts, tool arguments, response bodies, or session transcripts. Explicit delegated jobs retain their final answer separately in a private artifact.

```text
native Claude / Codex CLI
        │ authenticated HTTP/SSE, localhost only
        ▼
per-session router ─── account selection + shared cooldown database
        │             credential owner adapter
        ▼
official provider host
    429 → cooldown → next eligible account → retry rejected request
    2xx → stream directly; request is no longer replayable
```

Claude uses the supported ANTHROPIC_BASE_URL and custom headers. Its full request shape, tools, conversation, and permission handling remain in the native CLI. The existing Claude Rotate package owns OAuth login/refresh and its authoritative account store. Agent Rotate invokes its lock-aware reconciliation before using those tokens; it never creates a second refresh-token store.

Codex uses a per-invocation custom Responses provider with `requires_openai_auth=true`, `supports_websockets=false`, and `features.enable_request_compression=false`. This keeps subscription authentication while avoiding account-bound WebSocket incremental state. Uncompressed requests let the router inspect model and continuation fields; opaque compressed requests pass through but aren't retried. The router replaces Authorization and ChatGPT-Account-Id together. Native Codex owns browser login and refresh through its documented app-server account API. Separate logins use separate CODEX_HOME directories; `run` doesn't repoint the user's global CODEX_HOME.

## Retry boundary

Only HTTP 429 from an inference endpoint or an initial structured SSE quota error qualifies. The body is retained only in request memory. All other routes and failures retain their native behavior. Once any first SSE event has been delivered, neither a later quota error nor a broken connection is retried by the router. A tool result appearing earlier in the request's conversation is context, not a tool invocation replayed by the router.

The tried-account set bounds each incoming request. Retry-After applies to the account that was rejected; other subscriptions can be tried immediately. SQLite cooldowns prevent another local session from immediately reusing that account for the same model. Unknown or stale usage never becomes a fabricated zero-percent quota reading.

## Security and process lifecycle

Only 127.0.0.1 is bound. Every request requires a random capability header, and browser Origin requests are rejected. Upstream hosts are compiled constants and paths are allowlisted. No redirects are followed, inherited auth/org/cookie headers are removed, and routing keys never leave the machine. HTTP compression is passed through unchanged. The native process inherits its terminal; native permissions are never relaxed. Router lifetime ends with the child, and Ctrl-C cancels native work without terminating the router.

## Shared monitoring and selection

The shared collector uses atomic per-account SQLite leases, at most two concurrent fetches per collector, adaptive intervals, and separate usage-endpoint backoff. Wrappers, dashboards and the daemon cooperate through those leases. A usage API 429 never creates an inference cooldown. Failed polls retain last-good readings with visible age/error state; only fresh readings influence proactive policy.

Each router publishes an opaque session ID, heartbeat, selected account, pool, directory, model and last routing reason. The CLI, terminal dashboard, menu bar and cached MCP tools consume one versioned snapshot. Watch/daemon write a private atomic JSON feed. Optional local desktop alerts deduplicate transitions in shared metadata.

Provider-specific pools contain ordered registered account names. A nearest-ancestor directory mapping chooses a pool, including Codex's native directory flag; explicit account/pool options take precedence. Missing or empty mapped pools fail closed. Default routing remains sticky. Optional consume-first ordering favors known weekly resets. An explicit proactive threshold requires fresh usage, a five-minute dwell, ten percentage points of headroom improvement, and an independent request with no other request in flight. Opaque/incremental continuations remain bound to their original account.

Explicit permanent credential errors quarantine an account; a successful authenticated usage check or re-login can recover it. Claude Rotate and native Codex retain sole refresh ownership. Forecasts are advisory, require enough recent samples or known weekly duration, and never drive account changes.

## MCP and native jobs

The official Python MCP SDK supplies a local stdio server with six cached/read-only tools. The wrapper passes its session ID to native child servers, allowing accurate per-session identity. No MCP tool can retrofit routing into its host.

Delegation requires explicit server opt-in and a fixed workspace. A job worker receives its prompt over a private stdin pipe and starts a separate native CLI behind its own router. MCP jobs use Codex read-only sandboxing or Claude plan permissions; CLI workspace-write is explicit. Native history persistence is disabled. Only a completed final result, capped at 1 MiB, is written privately; stdout tool events and stderr are not retained. Cancellation/timeout stop the native process group. Interrupted jobs are reported and never automatically restarted. Result/list/cancel MCP operations stay within the configured workspace.

Background launchd/user-systemd installation, menu-bar use, proactive thresholds, alerts, and delegation are opt-in. [Commands](commands.md) documents installation, controls and cleanup. [Feature research](feature-research.md) records the reviewed source ideas implemented in 0.2.

## Remaining compatibility limits

- Live verification of a natural provider quota transition, separately for Claude and Codex.
- Better model/bucket mapping as providers expose new rate-limit windows.
- Native desktop/IDE integration through explicit supported routing configuration.
- Recovery for quota errors after streaming begins requires provider-native session continuation; do not add blind replay or screen scraping.
