"""Read bounded native session headers; never copy conversation transcripts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path


def saved_sessions(provider: str, limit: int = 100, *, root: Path | None = None) -> list[dict]:
    if provider not in {"claude", "codex"} or not 1 <= limit <= 500:
        raise ValueError("Choose claude/codex and a limit from 1 to 500")
    if root is None:
        home = Path(
            os.environ.get(
                "CODEX_HOME" if provider == "codex" else "CLAUDE_CONFIG_DIR",
                str(Path.home() / (".codex" if provider == "codex" else ".claude")),
            )
        )
        root = home / ("sessions" if provider == "codex" else "projects")
    found = []
    scanned = 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted((d for d in dirs if d != "subagents"), reverse=True)
        for name in sorted(files, reverse=True):
            if not name.endswith(".jsonl"):
                continue
            scanned += 1
            path = Path(directory) / name
            with contextlib.suppress(OSError, ValueError, TypeError, KeyError):
                with path.open() as stream:
                    for _ in range(16):
                        line = stream.readline(65536)
                        if not line:
                            break
                        with contextlib.suppress(ValueError):
                            event = json.loads(line)
                            meta = (
                                event.get("payload", {})
                                if event.get("type") == "session_meta"
                                else event
                            )
                            ident, cwd = meta.get("sessionId", meta.get("id")), meta.get("cwd")
                            if ident and isinstance(cwd, str) and Path(cwd).is_absolute():
                                ident = str(uuid.UUID(ident))
                                found.append(
                                    {
                                        "provider": provider,
                                        "id": ident,
                                        "cwd": cwd,
                                        "updated_at": path.stat().st_mtime,
                                    }
                                )
                                break
            if scanned >= 1000:
                break
        if scanned >= 1000:
            break
    unique = {r["id"]: r for r in sorted(found, key=lambda r: r["updated_at"])}
    return sorted(unique.values(), key=lambda r: r["updated_at"], reverse=True)[:limit]


async def resume(store, provider: str, ident: str | None, *, pool=None, account=None):
    from agent_rotate.launcher import run

    rows = saved_sessions(provider, 500)
    if ident is None:
        if not rows:
            raise ValueError("No saved native sessions found in the current native home")
        for i, row in enumerate(rows[:30], 1):
            print(f"{i:2}. {row['id']}  {row['cwd']}")
        try:
            index = int(await asyncio.to_thread(input, "Session number: "))
            if not 1 <= index <= min(30, len(rows)):
                raise ValueError
        except (ValueError, EOFError):
            raise ValueError("Choose a displayed session number") from None
        ident = rows[index - 1]["id"]
    row = next((r for r in rows if r["id"] == ident), None)
    if not row:
        raise ValueError(
            "Session not in the bounded local index; use run PROVIDER with native resume flags"
        )
    args = ["--resume", ident] if provider == "claude" else ["resume", ident]
    return await run(store, provider, args, account, pool=pool, cwd=Path(row["cwd"]))
