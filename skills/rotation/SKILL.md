---
name: rotation
description: Check Claude and Codex account pools, explain live quota and cooldown state, register account references, and launch native sessions with Agent Rotate request-level quota failover. Use for Agent Rotate setup, account availability, or in-session HTTP 429 routing.
---

# Agent Rotate

Use the `agent-rotate` executable. Read the repository README and SETUP.md for installation and current transport limits.

## Status

Run `agent-rotate status --json` for live provider quota windows; `agent-rotate list` for local registration; `agent-rotate history` for recent routing metadata. Show provider, account handle, usage windows, reset times, disabled state, and unknown/stale readings clearly. Do not dump credential files or process environments.

## Setup

Import existing Claude Rotate account references using `agent-rotate import-claude`. For Codex use `agent-rotate add-codex NAME --home PATH` or `agent-rotate login codex NAME` in an interactive terminal. The human completes browser OAuth. New Codex logins have separate credential homes. Never fabricate tokens or cancellation dates.

## Launch and limits

`agent-rotate run claude` and `agent-rotate run codex` start the native CLI behind a per-session local router. Pass native resume arguments to continue a specific saved session. A host session already running outside the wrapper is not automatically protected by this skill.

The router retries a model request only on explicit quota rejection before any stream content is delivered. It preserves the model, provider, native approvals, and sandbox flags. It does not replay partial responses or execute tool operations itself. If every account is cooling down, report exhaustion and the next reset; do not enable paid API fallback or change models.

## Changes

Enable/disable accounts only as requested. `--account NAME` is a hard restriction, not a preference. Do not replace shell aliases, remove the original Claude Rotate sync job, or log out active sessions as part of status checks.
