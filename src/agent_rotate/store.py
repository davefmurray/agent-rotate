"""SQLite contains references and operational metadata, never credentials."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Account:
    provider: str
    name: str
    home: str
    enabled: bool = True


class Store:
    def __init__(self, root: Path | None = None):
        self.root = (
            root
            or Path(os.environ.get("AGENT_ROTATE_HOME", "~/.local/share/agent-rotate")).expanduser()
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.path = self.root / "state.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    provider TEXT, name TEXT, home TEXT, enabled INTEGER DEFAULT 1,
                    PRIMARY KEY(provider, name));
                CREATE TABLE IF NOT EXISTS cooldowns (
                    provider TEXT, name TEXT, model TEXT, until REAL, reason TEXT,
                    PRIMARY KEY(provider, name, model));
                CREATE TABLE IF NOT EXISTS usage (
                    provider TEXT, name TEXT, checked REAL, windows TEXT,
                    PRIMARY KEY(provider, name));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, at REAL, provider TEXT, account TEXT,
                    kind TEXT, status INTEGER);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, provider: str, name: str, home: str) -> Account:
        if provider not in ("claude", "codex"):
            raise ValueError("Provider must be claude or codex")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
            raise ValueError("Use an account name with 1–64 letters, digits, dots, - or _")
        account = Account(provider, name, str(Path(home).expanduser().resolve()))
        with self.connect() as db:
            if provider == "codex":
                same = db.execute(
                    "SELECT name FROM accounts WHERE provider=? AND home=? AND name!=?",
                    (provider, account.home, name),
                ).fetchone()
                if same:
                    raise ValueError("This Codex credential directory is already registered")
            old = db.execute(
                "SELECT home FROM accounts WHERE provider=? AND name=?", (provider, name)
            ).fetchone()
            if old and old["home"] != account.home:
                raise ValueError("That account name already refers to another credential store")
            db.execute(
                "INSERT OR IGNORE INTO accounts(provider,name,home) VALUES (?,?,?)",
                (provider, name, account.home),
            )
        return account

    def accounts(self, provider: str | None = None) -> list[Account]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM accounts WHERE (? IS NULL OR provider=?) ORDER BY provider,name",
                (provider, provider),
            ).fetchall()
        return [Account(r["provider"], r["name"], r["home"], bool(r["enabled"])) for r in rows]

    def enable(self, provider: str, name: str, enabled: bool):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE accounts SET enabled=? WHERE provider=? AND name=?",
                (int(enabled), provider, name),
            )
            if not cursor.rowcount:
                raise ValueError("Account not found")

    def cooldown(self, account: Account, model: str, until: float, reason: str = "quota"):
        with self.connect() as db:
            db.execute(
                "INSERT INTO cooldowns VALUES (?,?,?,?,?) ON CONFLICT(provider,name,model) "
                "DO UPDATE SET until=MAX(until,excluded.until),reason=excluded.reason",
                (account.provider, account.name, model, until, reason),
            )

    def blocked_until(self, account: Account, model: str) -> float:
        with self.connect() as db:
            row = db.execute(
                "SELECT MAX(until) AS until FROM cooldowns WHERE provider=? AND name=? "
                "AND model IN (?, '*')",
                (account.provider, account.name, model),
            ).fetchone()
        return row["until"] or 0

    def cooldowns(self, account: Account) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT model,until,reason FROM cooldowns "
                    "WHERE provider=? AND name=? AND until>?",
                    (account.provider, account.name, time.time()),
                )
            ]

    def set_usage(self, account: Account, windows: list[dict]):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO usage VALUES (?,?,?,?)",
                (account.provider, account.name, time.time(), json.dumps(windows)),
            )

    def usage(self, account: Account) -> tuple[float, list[dict]]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM usage WHERE provider=? AND name=?", (account.provider, account.name)
            ).fetchone()
        return (row["checked"], json.loads(row["windows"])) if row else (0, [])

    def event(self, provider: str, account: str, kind: str, status: int):
        if kind not in {"request", "switch", "quota", "auth", "transport", "exhausted"}:
            raise ValueError("Invalid event kind")
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(at,provider,account,kind,status) VALUES (?,?,?,?,?)",
                (time.time(), provider, account, kind, status),
            )
            db.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events "
                "ORDER BY id DESC LIMIT 500)"
            )

    def events(self, limit: int = 20) -> list[dict]:
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT at,provider,account,kind,status FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            ]


def relevant_windows(account: Account, windows: list[dict], model: str) -> list[dict]:
    if account.provider == "codex":
        return [w for w in windows if w.get("bucket", "codex") == "codex"]
    return [
        w
        for w in windows
        if w["name"] in {"five_hour", "seven_day"}
        or any(
            family in model.lower() and w["name"] == f"seven_day_{family}"
            for family in ("opus", "sonnet", "fable")
        )
    ]


def availability(store: Store, account: Account, model: str, now: float) -> tuple[float, float]:
    """Return (blocked-until, headroom); unknown/stale usage is not zero usage."""
    until = store.blocked_until(account, model)
    checked, windows = store.usage(account)
    headroom = 0.5
    if checked > now - 120:
        valid = [
            w
            for w in relevant_windows(account, windows, model)
            if not w.get("resets_at") or w["resets_at"] > now
        ]
        if valid:
            headroom = min(1 - w["used_percent"] / 100 for w in valid)
        for w in valid:
            if w["used_percent"] >= 100:
                until = max(until, w.get("resets_at") or now + 60)
    return until, headroom
