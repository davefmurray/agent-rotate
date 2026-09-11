"""A shared, versioned view for terminal, menu bar, status feed, and MCP."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import time
from pathlib import Path

from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from agent_rotate.collector import Collector
from agent_rotate.credentials import Credentials
from agent_rotate.store import Store, usage_fresh


def forecast(store: Store, account, window: dict, checked: float) -> dict:
    result = {
        "advisory": True,
        "expected_percent": None,
        "ahead_of_pace": None,
        "percent_per_hour": None,
        "exhaustion_at": None,
    }
    if not usage_fresh(store, account, time.time()):
        return result
    reset, period = window.get("resets_at"), window.get("period_seconds")
    used = window["used_percent"]
    if period and period >= 6 * 86400 and reset and 0 <= reset - checked <= period:
        elapsed = period - (reset - checked)
        if elapsed >= 86400:
            expected = 100 * elapsed / period
            result.update(expected_percent=round(expected, 1), ahead_of_pace=used - expected >= 15)
    points = []
    key = (window.get("bucket"), window["name"])
    for at, windows in store.samples(account):
        if not checked - 3600 <= at <= checked:
            continue
        sample = next((w for w in windows if (w.get("bucket"), w["name"]) == key), None)
        if not sample or sample.get("resets_at") != reset:
            continue
        val = sample["used_percent"]
        if points and (val < points[-1][1] or at - points[-1][0] > 900):
            points = []
        points.append((at, val))
    if len({v for _, v in points}) >= 3 and points[-1][0] - points[0][0] >= 180:
        rate = (points[-1][1] - points[0][1]) * 3600 / (points[-1][0] - points[0][0])
        if rate > 0 and math.isfinite(rate):
            result["percent_per_hour"] = round(rate, 2)
            eta = checked + max(0, 100 - used) / rate * 3600
            if reset and checked <= eta < reset:
                result["exhaustion_at"] = eta
    return result


def snapshot(store: Store, *, session: str | None = None) -> dict:
    now = time.time()
    rows = []
    for account in store.accounts():
        checked, windows = store.usage(account)
        poll = store.poll_state(account)
        health = store.health(account)
        rows.append(
            {
                "provider": account.provider,
                "account": account.name,
                "enabled": account.enabled,
                "checked_at": checked or None,
                "age_seconds": max(0, now - checked) if 0 < checked <= now else None,
                "stale": not usage_fresh(store, account, now),
                "next_poll_at": poll["next_poll"] or None,
                "error": poll["error"],
                "health": health,
                "cooldowns": store.cooldowns(account),
                "windows": [
                    dict(w, forecast=forecast(store, account, w, checked)) for w in windows
                ],
                "relogin_command": f"agent-rotate login {account.provider} {account.name}"
                + (" --replace" if account.provider == "claude" else ""),
                "credential_owner": "Claude Rotate"
                if account.provider == "claude"
                else "Codex native",
            }
        )
    sessions = store.sessions()
    current = next((s for s in sessions if s["id"] == session), None)
    return {
        "schema_version": 1,
        "generated_at": now,
        "accounts": rows,
        "sessions": sessions,
        "current_session": current,
        "pools": store.pools(),
        "history": store.events(20, session),
    }


def countdown(until: float | None) -> str:
    if not until:
        return "—"
    seconds = max(0, int(until - time.time()))
    return (
        f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
        if seconds >= 86400
        else (
            f"{seconds // 3600}h {(seconds % 3600) // 60}m"
            if seconds >= 3600
            else f"{seconds // 60}m"
        )
    )


def render(data: dict):
    table = Table(title="Agent Rotate · Claude + Codex", expand=True)
    for column in ("Provider / account", "State", "Quota window", "Used", "Resets", "Age / pace"):
        table.add_column(column)
    for row in data["accounts"]:
        state = "disabled" if not row["enabled"] else row["health"]["state"]
        if row["enabled"] and state != "relogin_required":
            state = "stale" if row["stale"] else "ready"
            if row["cooldowns"]:
                state = "cooling " + countdown(max(c["until"] for c in row["cooldowns"]))
        age = "unknown" if row["age_seconds"] is None else f"{int(row['age_seconds']) // 60}m ago"
        for w in row["windows"] or [{}]:
            used = w.get("used_percent")
            count = max(0, min(10, int(used / 10))) if used is not None else 0
            bar = ("█" * count + "░" * (10 - count) + f" {used:.0f}%") if used is not None else "—"
            pace = " · ahead of weekly pace" if w.get("forecast", {}).get("ahead_of_pace") else ""
            estimate = w.get("forecast", {})
            if estimate.get("percent_per_hour") is not None:
                pace += f" · ~{estimate['percent_per_hour']:.1f}%/h"
            if estimate.get("exhaustion_at"):
                pace += " · est. full in " + countdown(estimate["exhaustion_at"])
            name = "/".join(filter(None, [w.get("bucket"), w.get("name", "unknown")]))
            table.add_row(
                Text(f"{row['provider']} / {row['account']}"),
                Text(state),
                Text(name),
                Text(bar),
                countdown(w.get("resets_at")),
                age + pace,
            )
    sessions = Table(title="Live routed sessions", expand=True)
    for c in ("Session", "Provider", "Account / pool", "Last decision", "Directory"):
        sessions.add_column(c)
    for s in data["sessions"]:
        sessions.add_row(
            s["id"][:8],
            s["provider"],
            Text(f"{s['account'] or 'starting'} / {s['pool'] or 'all'}"),
            Text(s["reason"]),
            Text(s["cwd"]),
        )
    return Group(table, sessions)


def write_feed(store: Store, data: dict):
    import tempfile

    fd, name = tempfile.mkstemp(prefix=".status-", dir=store.root)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(name, store.root / "status.json")
    finally:
        Path(name).unlink(missing_ok=True)


async def watch(store: Store, *, once: bool = False, as_json: bool = False, daemon: bool = False):
    from agent_rotate.notifications import check_alerts

    collector = Collector(store, Credentials())
    await collector.once()
    if once:
        data = snapshot(store)
        if as_json:
            print(json.dumps(data))
        else:
            from rich.console import Console

            Console().print(render(data))
        return
    background = asyncio.create_task(collector.run())
    try:
        with (
            Live(refresh_per_second=1) if not as_json and not daemon else contextlib.nullcontext()
        ) as live:
            while True:
                data = snapshot(store)
                write_feed(store, data)
                await check_alerts(store, data)
                if as_json:
                    print(json.dumps(data), flush=True)
                elif live:
                    live.update(render(data))
                await asyncio.sleep(5)
    finally:
        background.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await background
