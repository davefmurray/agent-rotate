# Agent Rotate engineering instructions

Build a local account router for the real Claude Code and Codex CLIs. The product must keep an existing session alive when an inference request is rejected for quota. Skills/plugins expose the router; they cannot observe or recover the host model's own HTTP errors by themselves.

## Non-negotiable behavior

- Never switch accounts by overwriting global Claude/Codex credentials, or modify shell aliases during `run`. The existing credential owner may persist a legitimate token refresh for the same account.
- Keep provider pools separate. Do not change the requested model, provider, permissions, sandbox, or billing mode during failover.
- A request may be retried only after an explicit upstream HTTP 429 or an initial structured quota-error event before any stream bytes reach the client. Never replay a partial response, arbitrary 5xx, network timeout, tool result, or approval decision.
- Honor per-account cooldowns and Retry-After. Each account gets at most one quota attempt per incoming request. Exhaustion returns a bounded failure, not a spin loop.
- Keep sessions sticky by default. Explicit proactive thresholds may switch between independent requests after a five-minute dwell and at least ten percentage points of additional headroom. Never switch opaque/incremental continuations proactively. Do not rotate global files beneath other sessions.
- Bind only to loopback, authenticate every proxy request, reject browser origins, use fixed provider upstreams and explicit paths, and never follow redirects with credentials.
- Tokens stay in their existing credential stores. Never print, commit, log, or include them in exceptions, fixtures, screenshots, or issue bodies. Runtime records contain only allowlisted metadata.
- Usage-endpoint failures are not inference exhaustion. Coordinate polls through shared leases and honor usage backoff independently of model cooldowns.
- Local directory mappings and explicit account/pool restrictions must fail closed. No project-supplied settings may silently widen the pool.
- MCP is cached/read-only by default. Delegation requires explicit server opt-in and a fixed workspace; jobs use native restricted permissions, accept prompts over stdin, and retain only private final-result artifacts. Never restart a failed job automatically.
- Claude Rotate remains the sole owner of imported Claude OAuth refresh. Codex manages its own login/refresh via the official CLI app server. Do not implement competing refresh-token writers.
- Preserve MIT attribution for the pinned Claude Rotate dependency. Do not vendor or copy implementation without its license.
- Do not describe synthetic failover tests as live provider-quota verification. Keep the README compatibility/limitations table honest.

## Workflow

1. Read README.md, docs/architecture.md, docs/sources.md, and the affected modules.
2. Reproduce behavior with local fake upstreams; real provider credentials are not test fixtures.
3. Make the smallest fix, then run `rtk proxy uv run pytest` and `rtk proxy uv run ruff check .`.
4. Validate plugin and skill manifests after editing them. Build with `rtk proxy uv build`.
5. Update user instructions and documented limitations with behavior changes.

Use `rtk` for shell commands. Do not launch additional agents unless the user asks for delegation. Never install aliases, disable the original sync job, publish a release, or change repository visibility as a side effect of tests.

## Layout

- `src/agent_rotate/store.py`: account references, shared cooldowns, metadata history.
- `credentials.py`: existing Claude Rotate and native Codex credential sources.
- `proxy.py`: authenticated loopback HTTP/SSE transport and quota retry boundary.
- `launcher.py`: native CLI process lifecycle and per-invocation routing configuration.
- `cli.py`: setup, status, account controls, and launch commands.
- `tests/`: fake provider servers, protocol cases, and lifecycle checks.
- `skills/rotation/`: agent-facing operational instructions.

Success means native request flow is preserved; a rejected request reaches a different eligible account; completed content is not replayed; no credential escapes; and all tests pass.
