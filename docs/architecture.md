# Architecture

Each `agent-rotate run PROVIDER` owns one ephemeral loopback router and one native CLI child. Other sessions have independent sticky account choices. Shared SQLite metadata stores account references, usage snapshots, cooldowns, and the latest 500 routing outcomes; it never stores OAuth secrets, prompts, tool arguments, response bodies, or session transcripts.

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

## Deliberate next work

See [feature research](feature-research.md) for a source-reviewed proposal covering shared usage polling, a session dashboard, account pools, and later MCP/usage-planning features. These are proposals, not shipped capabilities.

- Live verification of a natural provider quota transition, separately for Claude and Codex.
- Per-session UI showing routing state instead of the native original-account label.
- Better model/bucket mapping as providers expose new rate-limit windows.
- Native desktop/IDE integration through explicit supported routing configuration.
- Recovery for quota errors after streaming begins requires provider-native session continuation; do not add blind replay or screen scraping.
