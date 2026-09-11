from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent_rotate import __version__
from agent_rotate.credentials import Credentials, claude_accounts, claude_paths
from agent_rotate.launcher import run
from agent_rotate.store import Store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Keep native Claude Code and Codex sessions running across account quotas"
    )
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "import-claude", help="Reference existing Claude Rotate accounts without copying tokens"
    )
    add = sub.add_parser("add-codex", help="Reference an existing file-based Codex login")
    add.add_argument("name")
    add.add_argument("--home", type=Path, default=Path.home() / ".codex")
    login = sub.add_parser("login", help="Sign in through the native OAuth owner")
    login.add_argument("provider", choices=["claude", "codex"])
    login.add_argument("name")
    login.add_argument("--email", help="Required for a Claude browser login")
    login.add_argument("--replace", action="store_true", help="Replace an existing Claude login")
    login.add_argument("--device-code", action="store_true", help="Use Codex device-code login")
    for name in ("enable", "disable"):
        control = sub.add_parser(name)
        control.add_argument("provider", choices=["claude", "codex"])
        control.add_argument("name")
    status = sub.add_parser("status", help="Live quota windows for both providers")
    status.add_argument("--cached", action="store_true")
    status.add_argument("--json", action="store_true")
    sub.add_parser("list", help="Account references only; no network calls")
    sub.add_parser(
        "doctor", help="Check binaries and credential availability without exposing tokens"
    )
    sub.add_parser("history", help="Recent routing outcomes, with no prompts or credentials")
    launch = sub.add_parser("run", help="Launch a real CLI behind an ephemeral local router")
    launch.add_argument("--account", help="Restrict routing to one account")
    launch.add_argument("provider", choices=["claude", "codex"])
    launch.add_argument("native_args", nargs=argparse.REMAINDER)
    return root


def import_claude(store: Store):
    sources = claude_accounts()
    for name, source in sources.items():
        store.add("claude", name, str(claude_paths().accounts_file))
        if source.disabled:
            store.enable("claude", name, False)
    print(f"Registered {len(sources)} Claude account references; no tokens copied")


async def status(store: Store, *, cached: bool, as_json: bool) -> int:
    credentials = Credentials()
    rows = []
    failed = False
    for account in store.accounts():
        error = None
        if not cached and account.enabled:
            try:
                store.set_usage(account, await credentials.usage(account))
            except (RuntimeError, OSError, ValueError, TimeoutError):
                error = "Live usage unavailable; check login/network"
                failed = True
        checked, windows = store.usage(account)
        rows.append(
            {
                "provider": account.provider,
                "account": account.name,
                "enabled": account.enabled,
                "checked_at": checked or None,
                "stale": checked < time.time() - 120,
                "windows": windows,
                "cooldowns": store.cooldowns(account),
                "error": error,
            }
        )
    if as_json:
        print(json.dumps({"accounts": rows}, indent=2))
    else:
        from rich.console import Console
        from rich.table import Table

        table = Table(title="Agent Rotate · quota usage")
        for col in ("Provider", "Account", "State", "Window", "Used", "Resets"):
            table.add_column(col)
        for row in rows:
            state = "disabled" if not row["enabled"] else ("stale" if row["stale"] else "ready")
            if row["error"]:
                state = "unavailable"
            elif row["cooldowns"] and row["enabled"]:
                state = "cooling"
            for window in row["windows"] or [{}]:
                reset = window.get("resets_at")
                table.add_row(
                    row["provider"],
                    row["account"],
                    state,
                    window.get("bucket", "") + "/" + window.get("name", "unknown"),
                    f"{window['used_percent']:.0f}%" if window else "—",
                    time.strftime("%a %H:%M", time.localtime(reset)) if reset else "—",
                )
        Console().print(table)
    return 1 if failed else 0


async def doctor(store: Store) -> int:
    failed = False
    credentials = Credentials()
    for provider in ("claude", "codex"):
        binary = shutil.which(provider)
        print(f"{'OK' if binary else 'MISSING'} {provider}: {binary or 'install native CLI'}")
        if not binary:
            failed = True
        accounts = [a for a in store.accounts(provider) if a.enabled]
        if not accounts:
            print(f"NOTE {provider}: no enabled accounts")
        elif len(accounts) < 2:
            print(f"NOTE {provider}: one account; failover needs another login")
        for account in accounts:
            try:
                await credentials.get(account)
                print(f"OK {provider}/{account.name}: credential readable")
            except (RuntimeError, OSError, ValueError, TimeoutError):
                failed = True
                print(f"FAIL {provider}/{account.name}: sign in again")
    print("INFO run starts a loopback-only router; saved aliases/configs are untouched")
    return 1 if failed else 0


def login(store: Store, args) -> int:
    # Validate before using the name as a directory component.
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.name):
        raise ValueError("Use a simple account name (letters, digits, dots, - or _)")
    if args.provider == "claude":
        if not args.email:
            raise ValueError("Use --email for a Claude subscription login")
        command = [sys.executable, "-m", "claude_rotate", "login", args.email, args.name]
        if args.replace:
            command.append("--replace")
        code = subprocess.call(command)
        if not code:
            import_claude(store)
        return code
    home = store.root / "codex" / args.name
    if any(a.name == args.name and Path(a.home) != home for a in store.accounts("codex")):
        raise ValueError("Name already references another login; choose a new account name")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    # Dedicated login storage; don't link or replace the current Codex auth.json.
    env = dict(os.environ, CODEX_HOME=str(home))
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        env.pop(key, None)
    binary = shutil.which("codex")
    if not binary:
        raise ValueError("Install Codex CLI first")
    command = [binary, "-c", 'cli_auth_credentials_store="file"', "login"]
    if args.device_code:
        command.append("--device-auth")
    code = subprocess.call(command, env=env)
    if not code:
        auth = home / "auth.json"
        if not auth.is_file():
            raise ValueError(
                "Login did not create file credentials; check managed auth requirements"
            )
        auth.chmod(0o600)
        store.add("codex", args.name, str(home))
        print(f"Registered codex/{args.name}")
    return code


def main():
    args = parser().parse_args()
    os.umask(0o077)
    try:
        store = Store()
        if args.command == "import-claude":
            import_claude(store)
            code = 0
        elif args.command == "add-codex":
            auth = args.home.expanduser().resolve() / "auth.json"
            if not auth.is_file():
                raise ValueError("No auth.json there; use agent-rotate login codex NAME")
            # Verify shape without exposing values or copying credentials.
            raw = json.loads(auth.read_text())
            if not (raw.get("tokens") or {}).get("account_id"):
                raise ValueError("Not a ChatGPT subscription credential store")
            store.add("codex", args.name, str(auth.parent))
            print(f"Registered codex/{args.name}; existing credentials remain in place")
            code = 0
        elif args.command == "login":
            code = login(store, args)
        elif args.command in ("enable", "disable"):
            store.enable(args.provider, args.name, args.command == "enable")
            print(f"{args.provider}/{args.name}: {args.command}d")
            code = 0
        elif args.command == "list":
            for a in store.accounts():
                print(f"{a.provider:7} {a.name:20} {'enabled' if a.enabled else 'disabled'}")
            code = 0
        elif args.command == "status":
            code = asyncio.run(status(store, cached=args.cached, as_json=args.json))
        elif args.command == "doctor":
            code = asyncio.run(doctor(store))
        elif args.command == "history":
            print(json.dumps(store.events(), indent=2))
            code = 0
        else:
            native_args = args.native_args
            if native_args[:1] == ["--"]:
                native_args = native_args[1:]
            code = asyncio.run(run(store, args.provider, native_args, args.account))
    except KeyboardInterrupt:
        code = 130
    except (ValueError, RuntimeError, OSError) as exc:
        # Only known, human-authored errors are useful; raw network/JSON exceptions
        # can contain credentials or response bodies.
        if isinstance(exc, json.JSONDecodeError):
            message = "Invalid local JSON; check account configuration"
        elif type(exc) in (ValueError, RuntimeError):
            message = str(exc)
        else:
            message = "Operation failed; check local files, network, and login state"
        print(f"agent-rotate: {message}", file=sys.stderr)
        code = 1
    raise SystemExit(code)
