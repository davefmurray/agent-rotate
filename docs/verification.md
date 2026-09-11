# Verification — 2026-09-11

Agent Rotate 0.2.0. Native binaries tested on macOS arm64: Claude Code 2.1.265 and Codex CLI 0.154.0.

## Native failover with injected rejection

`scripts/verify_live.py` was run separately for Claude and Codex with two distinct subscription accounts per provider. It registered existing credential references in a temporary metadata database, launched the real native CLI, injected one local HTTP 429, then forwarded the retried request to the actual provider using the fallback account.

| Provider | Injected 429 | Switch | Real successful requests | Native exit | Reply |
| --- | --- | --- | --- | --- | --- |
| Claude | 1 | First → second account | 1 | 0 | ROTATE_OK |
| Codex | 1 | First → second account | 1 | 0 | ROTATE_OK |

The native process stayed running during the switch. The actual providers accepted the second account and returned the expected response. Both checks were repeated successfully against 0.2.0. These are **injected quota rejections with real fallback inference**, not naturally exhausted subscription windows. No prompts, token values, native transcripts, or account IDs were persisted by the verification script.

Run manually after account setup; this consumes a small amount of real provider quota:

```sh
uv run python scripts/verify_live.py --provider claude
uv run python scripts/verify_live.py --provider codex
```

## Switching after a completed tool call

The `--after-tool` variant lets the native CLI execute one harmless `printf ROTATE_TOOL_OK`, then injects a 429 on the next model request. Both providers completed this check with the second real account. The successful fallback request included the diagnostic tool result in its history; the native process executed exactly one tool call and returned `ROTATE_OK`.

| Provider | Injected 429 | Real successful requests | Tool calls | Tool result in request history | Native exit |
| --- | --- | --- | --- | --- | --- |
| Claude | 1 | 2 | 1 | Yes | 0 |
| Codex | 1 | 2 | 1 | Yes | 0 |

```sh
uv run python scripts/verify_live.py --provider claude --after-tool
uv run python scripts/verify_live.py --provider codex --after-tool
```

The Claude diagnostic uses Sonnet and allows only its Bash tool with the `printf` command. The Codex diagnostic uses its configured model and a read-only sandbox. These choices apply to the verification script only; normal routing preserves the user's model and permissions. The detector recognizes Claude tool results and Codex function/custom tool outputs, including structured text content. Local regression tests distinguish actual results from marker text in prompts or tool-call arguments.

During development, some Codex runs completed successfully with one tool call and two accepted model requests but did not expose the marker in a recognized tool result. They were treated as failed verification, not counted as proof of history preservation. The passing run above did expose it. This short test does not establish portability of every encrypted or compacted history format.

## 0.2 management and interface checks

- All four real account usage reads succeeded through the shared collector and migrated metadata database.
- `watch --once` rendered both provider pools with quota windows and reset countdowns.
- The optional macOS menu bar constructed real account menus and ran the Cocoa event loop. Native quit was verified to stop its collector. No startup service was installed.
- One explicit restricted native job per provider completed with exit 0 and the expected `JOB_OK` final answer. Temporary results and metadata were removed with `job forget`.
- The official MCP SDK initialized the stdio server, discovered six annotated structured read-only tools, and read cached session identity without provider calls. Tests also check delegation opt-in, monitor cancellation, and cross-workspace result/cancellation refusal.
- Local fake-native tests cover job completion, private artifacts, cancellation and timeout stopping the native process/router.
- Tests cover shared poll leases/backoff, usage-429 separation from inference cooldowns, last-good/stale readings, quarantine/recovery, pool boundaries, removed mappings, Codex `-C`, proactive dwell/headroom rules, forecasts, alert deduplication, bounded session headers, and launchd file generation/removal.
- launchd behavior is checked with mocked system calls; Linux service installation and desktop notification delivery require their respective OS environment. Native account menus were smoke-tested, but every interactive click path is not exhaustively automated.

## Other checks

- Normal native Claude and Codex requests succeeded through the router.
- Both providers' two account credentials and live quota endpoints were verified.
- The second Codex login used a separate credential directory; its subscription account ID differs from the first.
- Native Claude auth is preserved: the gateway-token override that disabled claude.ai connectors was removed and the live smoke rerun successfully.
- Automated tests cover local upstream rejection, streaming, child process continuity/exit, shared cooldowns, bounded attempts, request integrity, account headers, redirect refusal, auth refresh boundaries, and secret-free metadata.
- Ruff, package build, Codex plugin manifest validation, and skill validation pass.
- 82 automated tests pass locally. GitHub CI runs the suite, Ruff and package builds on macOS/Linux with Python 3.11/3.12; see the repository's Actions results for each pushed commit.

Natural provider quota transitions, provider-side cache/encrypted-history portability over long conversations, all connectors, and all CLI commands are not exhaustively verified. The documented no-replay boundary applies after the first forwarded stream event.
