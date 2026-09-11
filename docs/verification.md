# Verification — 2026-09-11

Native binaries tested on macOS arm64: Claude Code 2.1.265 and Codex CLI 0.154.0.

## Native failover with injected rejection

`scripts/verify_live.py` was run separately for Claude and Codex with two distinct subscription accounts per provider. It registered existing credential references in a temporary metadata database, launched the real native CLI, injected one local HTTP 429, then forwarded the retried request to the actual provider using the fallback account.

| Provider | Injected 429 | Switch | Real successful requests | Native exit | Reply |
| --- | --- | --- | --- | --- | --- |
| Claude | 1 | First → second account | 1 | 0 | ROTATE_OK |
| Codex | 1 | First → second account | 1 | 0 | ROTATE_OK |

The native process stayed running during the switch. The actual providers accepted the second account and returned the expected response. These are **injected quota rejections with real fallback inference**, not naturally exhausted subscription windows. No prompts, token values, native transcripts, or account IDs were persisted by the verification script.

Run manually after account setup; this consumes a small amount of real provider quota:

```sh
uv run python scripts/verify_live.py --provider claude
uv run python scripts/verify_live.py --provider codex
```

## Other checks

- Normal native Claude and Codex requests succeeded through the router.
- Both providers' two account credentials and live quota endpoints were verified.
- The second Codex login used a separate credential directory; its subscription account ID differs from the first.
- Native Claude auth is preserved: the gateway-token override that disabled claude.ai connectors was removed and the live smoke rerun successfully.
- Automated tests cover local upstream rejection, streaming, child process continuity/exit, shared cooldowns, bounded attempts, request integrity, account headers, redirect refusal, auth refresh boundaries, and secret-free metadata.
- Ruff, package build, Codex plugin manifest validation, and skill validation pass.

Natural provider quota transitions, provider-side cache/encrypted-history portability over long conversations, all connectors, and all CLI commands are not exhaustively verified. The documented no-replay boundary applies after the first forwarded stream event.
