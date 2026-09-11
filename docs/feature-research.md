# Features worth adapting

Reviewed 2026-09-11. The roadmap below records the original source review. **Version 0.2.0 implements its shared collector, dashboard/menu bar, alerts, pools/mappings, advisory forecasts, optional routing strategies, cached MCP, credential health, session browser, completion, and explicit delegated jobs.** See [the command guide](commands.md) for shipped behavior and boundaries. External tools were not runtime-tested, and no external implementation was copied or executed. Signed standalone distribution, quota-window priming and remote control remain outside this update.

## Sources and licenses

| Project | Reviewed revision | License | Most useful contributions |
| --- | --- | --- | --- |
| [CodexCLI-Rotate](https://github.com/vaskoyudha/CodexCLI-Rotate) | `6518dbcfa3cec67d3c66d0d849bb2622d8ae57bc` | MIT, vaskoyudha and contributors | Account groups, notifications, shell completions, operational dashboard |
| [claude-swap](https://github.com/realiti4/claude-swap) | `7187ce83b444c6af7b61ec8ee092623566a2d8fa` | MIT, Onur Cetinkol | Shared adaptive usage polling, directory mappings, quota strategies, weekly pace, TUI/menu bar, credential quarantine |
| [clauth](https://github.com/uwuclxdy/clauth) | `f89b558199fb52a73b96bdc009b267c9cc1257e6` | MIT, cloudy | Session-aware MCP tools, versioned status feed, usage-rate estimates, fallback editor, session browser |

The crates.io `clauth` package is `uwuclxdy/clauth`, version 0.15.1. Its registry archive checksum matched the sparse index, and its Cargo metadata confirmed that repository and MIT license. The GitHub revision above was inspected separately from the published archive. Retain the relevant copyright and MIT notice if implementation code is later adapted; the current proposals describe behavior only.

## Recommended first batch

### 1. Shared usage collector

Adapt the architecture of claude-swap's [poll policy](https://github.com/realiti4/claude-swap/blob/7187ce83b444c6af7b61ec8ee092623566a2d8fa/src/claude_swap/poll_policy.py) and [usage store](https://github.com/realiti4/claude-swap/blob/7187ce83b444c6af7b61ec8ee092623566a2d8fa/src/claude_swap/usage_store.py).

Agent Rotate currently fetches usage at launch and on an uncached `status`. These calls are not coordinated between processes; routing uses a reading for only 120 seconds, then treats its usage as unknown. Shared cooldowns already work, but continuous usage monitoring does not exist.

Add a bounded collector with a per-account polling lease in SQLite. UI refreshes should read cached state independently of provider fetches. Persist successful observation time, next allowed poll, and an allowlisted failure reason. Preserve old readings for display while explicitly marking whether a reading is fresh enough for selection. Observe Retry-After and add backoff/jitter for usage-endpoint failures. A usage-endpoint 429 must not be recorded as inference exhaustion.

Start with conservative provider-specific intervals. The source project's measured rate-limit constants are observations, not a stable provider API contract; do not copy them as guarantees. Keep native credential owners and avoid a separate OAuth refresh loop.

Acceptance: two simultaneous monitors produce one eligible poll per account, failed fetches retain visibly stale last-good data, usage 429s back off independently of model requests, and polling stops when its owning process exits.

### 2. Live dashboard and local alerts

Borrow the watch/TUI and menu-bar experience from claude-swap, plus clauth's [versioned status feed](https://github.com/uwuclxdy/clauth/blob/f89b558199fb52a73b96bdc009b267c9cc1257e6/src/daemon/status_json.rs) and session identity reporting. CodexCLI-Rotate's [notification integration](https://github.com/vaskoyudha/CodexCLI-Rotate/blob/6518dbcfa3cec67d3c66d0d849bb2622d8ae57bc/bin/codex-rotate#L155) is another useful interface reference.

Proposed `agent-rotate watch`: both providers, quota bars, reset/cooldown countdowns, stale-data age, account health, active router sessions, and last switch reason. Add an opaque router session ID and heartbeat so the UI reports the account actually serving each session. There is no single global active account in our architecture. Never put the router capability key or conversation text into the status feed.

Opt-in desktop alerts should cover switches, exhausted pools, and recovery once per transition. A versioned cached JSON view can serve a later macOS menu-bar app and MCP tools without extra provider polling. Launch-at-login/service installation remains a separate explicit action.

Acceptance: two concurrent sessions can show different active accounts; a mid-session switch updates only the affected row; dead sessions age out; local alerts deduplicate and do not corrupt the native terminal UI.

### 3. Account pools with directory mappings

Combine CodexCLI-Rotate's account groups with claude-swap's [nearest-ancestor directory mapping](https://github.com/realiti4/claude-swap/blob/7187ce83b444c6af7b61ec8ee092623566a2d8fa/src/claude_swap/mappings.py).

Our existing `--account` pins a single account, which disables failover. A named pool should allow several accounts while limiting routing to that set. A local directory mapping can select a work or personal pool automatically, including from nested directories. Keep maps in the user's local metadata, so an untrusted repository cannot silently select billing identity. Explicit CLI selection should win; a missing or empty mapped pool should fail clearly rather than widening access.

Potential command shape, **not implemented**:

```sh
agent-rotate run --pool work codex
agent-rotate map --provider codex --pool work ~/work
```

Acceptance: selection and failover never leave the chosen provider/pool; subdirectories inherit the nearest mapping; symlink paths are normalized; the existing single-account restriction remains hard.

## Second batch

| Feature | Inspiration and adaptation | Verification needed |
| --- | --- | --- |
| Weekly pace and usage-rate estimates | claude-swap's [pace calculation](https://github.com/realiti4/claude-swap/blob/7187ce83b444c6af7b61ec8ee092623566a2d8fa/src/claude_swap/pace.py), clauth's [sampled usage rate](https://github.com/uwuclxdy/clauth/blob/f89b558199fb52a73b96bdc009b267c9cc1257e6/src/usage/burn.rs). Show an advisory estimate only with enough observations and a known window duration. | Resets, idle periods, stale/future timestamps, and sparse samples produce no misleading ETA. Do not call API-equivalent cost an actual subscription bill. |
| Optional quota strategies | claude-swap's `consume-first` can favor weekly quota resetting soonest. An opt-in threshold policy can move before exhaustion with a minimum dwell time and a meaningful headroom advantage. Start by applying reset-aware ranking at launch/failover. | Model-relevant windows, no account ping-pong, no mid-request changes, sticky behavior unchanged by default. Proactive switching is a new policy requiring an explicit design change to the current sticky-until-quota rule. |
| Read-only MCP operations | clauth's [profiles/session/monitor tools](https://github.com/uwuclxdy/clauth/blob/f89b558199fb52a73b96bdc009b267c9cc1257e6/src/mcp/mod.rs). Expose cached accounts, current router session, cooldowns and routing history to both agents. | Return correct per-session identity and versioned metadata; no secret or transcript access; no inference calls just to answer status. A skill still cannot intercept its own host model's 429. |
| Credential health and quarantine | claude-swap's permanent-refresh-failure handling and source-labelled diagnostics. Distinguish an expired access token from a revoked login, and show a concrete native re-login action. | Network/usage failures never quarantine an account; a repaired login clears the health state; native OAuth ownership is preserved. |
| Session browser and resume launcher | clauth's `sessions`, `info`, and `resume`. Provide a local picker that invokes the native resume command through our wrapper. | Do not copy/migrate transcripts across credential homes. A selected session resolves to the correct provider and working directory. |

Shell completions are a small independent usability improvement. A macOS menu-bar UI fits after the shared status feed. Signed standalone distribution may be useful later; it is less urgent while this is a private Python/uv project.

## Keep the existing routing foundation

CodexCLI-Rotate's [run loop](https://github.com/vaskoyudha/CodexCLI-Rotate/blob/6518dbcfa3cec67d3c66d0d849bb2622d8ae57bc/bin/codex-rotate#L1790) inspects stderr after a CLI exit, switches the global auth reference, and reruns the command. Its daemon also mutates the global login. claude-swap and clauth offer global credential switching as well as isolated launch modes. These mechanisms would change Agent Rotate's per-session ownership and retry boundary; adopt useful controls and policies around our request router instead.

Keep bounded retries of explicitly rejected inference requests, same-provider/model routing, native permissions, and no partial-stream replay. Do not add global auth-file swapping, silent paid API fallback, or model substitution as part of this roadmap.

clauth's cross-account task delegation is interesting but would be a separate job-runner feature: explicit launches, retained permissions, cancellation, and clear separation from continuing the current conversation. Scheduled requests that open quota windows, automatic credential export, and remotely exposed account-switch APIs are outside the recommended first batches. External notifications would require their own user configuration and authorization.
