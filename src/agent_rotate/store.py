"""SQLite contains references and operational metadata, never credentials."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
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
                CREATE TABLE IF NOT EXISTS polls (
                    provider TEXT, name TEXT, owner TEXT, lease_until REAL DEFAULT 0,
                    next_poll REAL DEFAULT 0, interval REAL DEFAULT 180,
                    failures INTEGER DEFAULT 0, error TEXT,
                    PRIMARY KEY(provider,name));
                CREATE TABLE IF NOT EXISTS usage_samples (
                    provider TEXT, name TEXT, at REAL, windows TEXT);
                CREATE INDEX IF NOT EXISTS samples_account ON usage_samples(provider,name,at);
                CREATE TABLE IF NOT EXISTS health (
                    provider TEXT, name TEXT, state TEXT, reason TEXT, checked REAL,
                    PRIMARY KEY(provider,name));
                CREATE TABLE IF NOT EXISTS pools (
                    provider TEXT, name TEXT, members TEXT, PRIMARY KEY(provider,name));
                CREATE TABLE IF NOT EXISTS mappings (
                    provider TEXT, path TEXT, pool TEXT, PRIMARY KEY(provider,path));
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, provider TEXT, account TEXT, pool TEXT,
                    cwd TEXT, pid INTEGER, started REAL, heartbeat REAL, ended REAL,
                    reason TEXT, model TEXT, strategy TEXT);
                CREATE TABLE IF NOT EXISTS session_events (
                    id INTEGER PRIMARY KEY, at REAL, session TEXT, provider TEXT,
                    account TEXT, kind TEXT, status INTEGER, reason TEXT);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS alerts (
                    key TEXT PRIMARY KEY, state TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, provider TEXT, account TEXT, pool TEXT, cwd TEXT,
                    created REAL, started REAL, ended REAL, heartbeat REAL,
                    state TEXT, exit_code INTEGER, cancel INTEGER DEFAULT 0);
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
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO usage VALUES (?,?,?,?)",
                (account.provider, account.name, now, json.dumps(windows)),
            )
            db.execute(
                "INSERT INTO usage_samples VALUES (?,?,?,?)",
                (account.provider, account.name, now, json.dumps(windows)),
            )
            db.execute(
                "DELETE FROM usage_samples WHERE provider=? AND name=? AND rowid NOT IN "
                "(SELECT rowid FROM usage_samples WHERE provider=? AND name=? "
                "ORDER BY at DESC LIMIT 512)",
                (account.provider, account.name, account.provider, account.name),
            )

    def usage(self, account: Account) -> tuple[float, list[dict]]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM usage WHERE provider=? AND name=?", (account.provider, account.name)
            ).fetchone()
        return (row["checked"], json.loads(row["windows"])) if row else (0, [])

    def event(
        self,
        provider: str,
        account: str,
        kind: str,
        status: int,
        *,
        session: str | None = None,
        reason: str = "",
    ):
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
            if session:
                db.execute(
                    "INSERT INTO session_events(at,session,provider,account,kind,status,reason) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (time.time(), session, provider, account, kind, status, reason),
                )
                db.execute(
                    "DELETE FROM session_events WHERE id NOT IN "
                    "(SELECT id FROM session_events ORDER BY id DESC LIMIT 1000)"
                )

    def events(self, limit: int = 20, session: str | None = None) -> list[dict]:
        with self.connect() as db:
            if session:
                return [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM session_events WHERE session=? ORDER BY id DESC LIMIT ?",
                        (session, limit),
                    )
                ]
            return [
                dict(r)
                for r in db.execute(
                    "SELECT at,provider,account,kind,status FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            ]

    def samples(self, account: Account) -> list[tuple[float, list[dict]]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT at,windows FROM usage_samples WHERE provider=? AND name=? ORDER BY at",
                (account.provider, account.name),
            ).fetchall()
        return [(r["at"], json.loads(r["windows"])) for r in rows]

    def poll_state(self, account: Account) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM polls WHERE provider=? AND name=?", (account.provider, account.name)
            ).fetchone()
        return dict(row) if row else {"next_poll": 0, "interval": 180, "failures": 0, "error": None}

    def claim_poll(self, account: Account, now: float) -> str | None:
        owner = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO polls(provider,name) VALUES (?,?)",
                (account.provider, account.name),
            )
            claimed = db.execute(
                "UPDATE polls SET owner=?,lease_until=? WHERE provider=? AND name=? "
                "AND lease_until<=? AND next_poll<=?",
                (owner, now + 120, account.provider, account.name, now, now),
            )
        return owner if claimed.rowcount else None

    def finish_poll(
        self,
        account: Account,
        owner: str,
        *,
        next_poll: float,
        interval: float,
        failures: int = 0,
        error: str | None = None,
    ):
        with self.connect() as db:
            db.execute(
                "UPDATE polls SET owner=NULL,lease_until=0,next_poll=?,interval=?,"
                "failures=?,error=? WHERE provider=? AND name=? AND owner=?",
                (next_poll, interval, failures, error, account.provider, account.name, owner),
            )

    def set_health(self, account: Account, state: str, reason: str = ""):
        if state not in {"ready", "unknown", "relogin_required"}:
            raise ValueError("Invalid health state")
        if reason not in {"", "rejected_after_refresh", "revoked_login", "missing_login"}:
            raise ValueError("Invalid health reason")
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO health VALUES (?,?,?,?,?)",
                (account.provider, account.name, state, reason, time.time()),
            )

    def health(self, account: Account) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT state,reason,checked FROM health WHERE provider=? AND name=?",
                (account.provider, account.name),
            ).fetchone()
        return dict(row) if row else {"state": "unknown", "reason": "", "checked": None}

    def set_pool(self, provider: str, name: str, members: list[str]):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
            raise ValueError("Use a simple pool name")
        if not members or len(set(members)) != len(members):
            raise ValueError("A pool needs unique account names in fallback order")
        known = {a.name for a in self.accounts(provider)}
        if not set(members) <= known:
            raise ValueError("Pool contains unregistered accounts")
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO pools VALUES (?,?,?)", (provider, name, json.dumps(members))
            )

    def pools(self) -> list[dict]:
        with self.connect() as db:
            return [
                {"provider": r["provider"], "name": r["name"], "members": json.loads(r["members"])}
                for r in db.execute("SELECT * FROM pools ORDER BY provider,name")
            ]

    def pool_members(self, provider: str, name: str) -> list[str]:
        for p in self.pools():
            if p["provider"] == provider and p["name"] == name:
                return p["members"]
        raise ValueError("Selected pool does not exist")

    def remove_pool(self, provider: str, name: str):
        with self.connect() as db:
            # Retain mappings: a removed pool must fail closed on the next launch.
            db.execute("DELETE FROM pools WHERE provider=? AND name=?", (provider, name))

    def map_pool(self, provider: str, pool: str, path: Path):
        self.pool_members(provider, pool)
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO mappings VALUES (?,?,?)",
                (provider, str(path.expanduser().resolve()), pool),
            )

    def mappings(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM mappings ORDER BY provider,path")]

    def unmap(self, provider: str, path: Path):
        with self.connect() as db:
            db.execute(
                "DELETE FROM mappings WHERE provider=? AND path=?",
                (provider, str(path.expanduser().resolve())),
            )

    def resolve_pool(self, provider: str, cwd: Path) -> str | None:
        path = cwd.expanduser().resolve()
        matches = [
            m
            for m in self.mappings()
            if m["provider"] == provider and Path(m["path"]) in (path, *path.parents)
        ]
        return max(matches, key=lambda m: len(Path(m["path"]).parts))["pool"] if matches else None

    def start_session(self, ident: str, provider: str, pool: str | None, cwd: str, strategy: str):
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    provider,
                    None,
                    pool,
                    cwd,
                    os.getpid(),
                    now,
                    now,
                    None,
                    "starting",
                    "*",
                    strategy,
                ),
            )
            db.execute(
                "DELETE FROM sessions WHERE ended IS NOT NULL AND id NOT IN "
                "(SELECT id FROM sessions ORDER BY started DESC LIMIT 500)"
            )

    def update_session(
        self,
        ident: str,
        *,
        account: str | None = None,
        reason: str | None = None,
        model: str | None = None,
        ended: bool = False,
    ):
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET heartbeat=?, account=COALESCE(?,account),"
                "reason=COALESCE(?,reason),model=COALESCE(?,model),ended=? WHERE id=?",
                (time.time(), account, reason, model, time.time() if ended else None, ident),
            )

    def sessions(self, *, include_ended: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = [
                dict(r)
                for r in db.execute("SELECT * FROM sessions ORDER BY started DESC LIMIT 500")
            ]
        for row in rows:
            row["live"] = row["ended"] is None and row["heartbeat"] > time.time() - 45
        return rows if include_ended else [r for r in rows if r["live"]]

    def setting(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def alert_transition(self, key: str, state: str) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT state FROM alerts WHERE key=?", (key,)).fetchone()
            db.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?)", (key, state, time.time()))
        return old["state"] != state if old else state in {"exhausted", "relogin_required"}


def relevant_windows(account: Account, windows: list[dict], model: str) -> list[dict]:
    if account.provider == "codex":
        return [
            w
            for w in windows
            if w.get("bucket", "codex") == "codex"
            or (
                w.get("bucket", "").removeprefix("codex_") in model.lower()
                and w.get("bucket", "").startswith("codex_")
            )
        ]
    return [
        w
        for w in windows
        if w["name"] in {"five_hour", "seven_day"}
        or any(
            family in model.lower() and w["name"] == f"seven_day_{family}"
            for family in ("opus", "sonnet", "fable")
        )
    ]


def usage_fresh(store: Store, account: Account, now: float) -> bool:
    checked, _ = store.usage(account)
    poll = store.poll_state(account)
    ttl = min(900, max(120, poll["interval"] * 1.5))
    return -1 <= now - checked < ttl and not poll["error"]


def availability(store: Store, account: Account, model: str, now: float) -> tuple[float, float]:
    """Return (blocked-until, headroom); unknown/stale usage is not zero usage."""
    until = store.blocked_until(account, model)
    checked, windows = store.usage(account)
    headroom = 0.5
    if usage_fresh(store, account, now):
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
