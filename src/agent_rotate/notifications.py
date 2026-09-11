"""Opt-in local desktop alerts. No webhook credentials or remote messaging."""

from __future__ import annotations

import asyncio
import shutil
import sys


async def send_desktop(message: str):
    if sys.platform == "darwin":
        command = [
            "osascript",
            "-e",
            'on run argv\ndisplay notification (item 1 of argv) with title "Agent Rotate"\nend run',
            message,
        ]
    elif shutil.which("notify-send"):
        command = ["notify-send", "Agent Rotate", message]
    else:
        return
    try:
        child = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError:
        return  # Desktop availability must not interrupt routing or collection.
    try:
        await asyncio.wait_for(child.wait(), 3)
    except TimeoutError:
        child.kill()
        await child.wait()


async def check_alerts(store, data, *, send=send_desktop):
    if not store.setting("notifications", False):
        return
    for session in data["sessions"]:
        state = (
            "exhausted" if session["reason"] == "exhausted" else session["account"] or "starting"
        )
        if store.alert_transition("session:" + session["id"], state):
            await send(f"{session['provider']} session {session['id'][:8]}: {state}")
    for row in data["accounts"]:
        if not row["enabled"]:
            continue
        state = row["health"]["state"]
        if state != "relogin_required" and not row["stale"]:
            state = "cooling" if row["cooldowns"] else "ready"
        if state in {"ready", "cooling", "relogin_required"} and store.alert_transition(
            f"account:{row['provider']}:{row['account']}", state
        ):
            await send(f"{row['provider']} / {row['account']}: {state.replace('_', ' ')}")
