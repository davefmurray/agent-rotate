from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agent_rotate import __version__
from agent_rotate.collector import Collector
from agent_rotate.credentials import Credentials, claude_accounts, claude_paths
from agent_rotate.dashboard import render, snapshot, watch
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
    sub.add_parser("list", help="Account references only; no network calls").add_argument(
        "--names", action="store_true"
    )
    sub.add_parser(
        "doctor", help="Check binaries and credential availability without exposing tokens"
    )
    history = sub.add_parser(
        "history", help="Recent routing outcomes, with no prompts or credentials"
    )
    history.add_argument("--session")
    launch = sub.add_parser("run", help="Launch a real CLI behind an ephemeral local router")
    launch.add_argument("--account", help="Restrict routing to one account")
    launch.add_argument("--pool", help="Restrict routing to a named pool")
    launch.add_argument("--strategy", choices=["sticky", "consume-first", "ordered"])
    launch.add_argument("--threshold", type=float, help="Opt-in proactive usage threshold, 50–99")
    launch.add_argument("provider", choices=["claude", "codex"])
    launch.add_argument("native_args", nargs=argparse.REMAINDER)
    for name in ("watch", "tui", "daemon"):
        display = sub.add_parser(name, help="Shared live quota and routed-session dashboard")
        display.add_argument("--once", action="store_true")
        display.add_argument("--json", action="store_true")
    sub.add_parser("menubar", help="macOS menu bar; requires the menubar extra")
    service = sub.add_parser("service", help="Explicit user-service installation/removal")
    service.add_argument("action", choices=["install", "remove", "status"])
    service.add_argument("--kind", choices=["daemon", "menubar"], default="daemon")
    pool = sub.add_parser("pool", help="Edit ordered provider-specific account pools")
    poolsub = pool.add_subparsers(dest="action", required=True)
    poolsub.add_parser("list").add_argument("--names", action="store_true")
    for name in ("set", "remove"):
        p = poolsub.add_parser(name)
        p.add_argument("provider", choices=["claude", "codex"])
        p.add_argument("name")
        if name == "set":
            p.add_argument("members", nargs="+")
    mapping = sub.add_parser(
        "map", help="Bind a directory to a provider's pool; no args lists mappings"
    )
    mapping.add_argument("--provider", choices=["claude", "codex"])
    mapping.add_argument("--pool")
    mapping.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    unmap = sub.add_parser("unmap")
    unmap.add_argument("provider", choices=["claude", "codex"])
    unmap.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    sessions = sub.add_parser(
        "sessions", help="List live routers or bounded saved native session metadata"
    )
    sessions.add_argument("kind", choices=["live", "saved"], nargs="?", default="live")
    sessions.add_argument("--provider", choices=["claude", "codex"])
    resume = sub.add_parser(
        "resume", help="Pick a saved native session and resume through its directory's pool"
    )
    resume.add_argument("provider", choices=["claude", "codex"])
    resume.add_argument("id", nargs="?")
    resume.add_argument("--pool")
    resume.add_argument("--account")
    health = sub.add_parser("health", help="Credential owner, quarantine and re-login diagnostics")
    health.add_argument(
        "--check",
        action="store_true",
        help="Poll due accounts through their native credential owner",
    )
    config = sub.add_parser("config", help="Validated opt-in settings")
    config.add_argument("action", choices=["list", "set", "unset"], nargs="?", default="list")
    config.add_argument("key", choices=["notifications", "strategy", "threshold"], nargs="?")
    config.add_argument("value", nargs="?")
    mcp = sub.add_parser("mcp", help="Local stdio MCP (cached, read-only by default)")
    mcp.add_argument("--allow-delegation", action="store_true")
    mcp.add_argument("--workspace", type=Path)
    job = sub.add_parser("job", help="Explicit native jobs with private final results")
    jobsub = job.add_subparsers(dest="action", required=True)
    jobsub.add_parser("list")
    for name in ("result", "cancel", "forget"):
        jobsub.add_parser(name).add_argument("id")
    submit = jobsub.add_parser("start")
    submit.add_argument("provider", choices=["claude", "codex"])
    submit.add_argument("--cwd", type=Path, default=Path.cwd())
    submit.add_argument("--account")
    submit.add_argument("--pool")
    submit.add_argument("--model")
    submit.add_argument("--access", choices=["read-only", "workspace-write"], default="read-only")
    submit.add_argument("--timeout", type=int, default=600)
    submit.add_argument("--prompt-file", type=Path, help="Default: read the prompt from stdin")
    sub.add_parser("completion", help="Print a shell completion script").add_argument(
        "shell", choices=["bash", "zsh", "fish"]
    )
    return root


def import_claude(store: Store):
    sources = claude_accounts()
    for name, source in sources.items():
        store.add("claude", name, str(claude_paths().accounts_file))
        if source.disabled:
            store.enable("claude", name, False)
    print(f"Registered {len(sources)} Claude account references; no tokens copied")


async def status(store: Store, *, cached: bool, as_json: bool) -> int:
    if not cached:
        await Collector(store, Credentials()).once()
    data = snapshot(store, session=os.environ.get("AGENT_ROTATE_SESSION_ID"))
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        from rich.console import Console

        Console().print(render(data))
    return int(any(r["error"] for r in data["accounts"] if r["enabled"]))


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
            source = claude_accounts().get(args.name)
            args.email = source.email if source else None
        if not args.email:
            raise ValueError("Use --email for a Claude subscription login")
        command = [sys.executable, "-m", "claude_rotate", "login", args.email, args.name]
        if args.replace:
            command.append("--replace")
        code = subprocess.call(command)
        if not code:
            import_claude(store)
            for a in store.accounts("claude"):
                if a.name == args.name:
                    store.set_health(a, "unknown")
        return code
    existing = next((a for a in store.accounts("codex") if a.name == args.name), None)
    home = Path(existing.home) if existing else store.root / "codex" / args.name
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
        store.set_health(next(a for a in store.accounts("codex") if a.name == args.name), "unknown")
        print(f"Registered codex/{args.name}")
    return code


def settings(store, args):
    defaults = {"notifications": False, "strategy": "sticky", "threshold": None}
    if args.action != "list":
        if not args.key:
            raise ValueError("Choose a settings key")
        value = defaults[args.key]
        if args.action == "set":
            if args.key == "notifications":
                if args.value not in {"true", "false"}:
                    raise ValueError("notifications must be true or false")
                value = args.value == "true"
            elif args.key == "strategy":
                if args.value not in {"sticky", "consume-first", "ordered"}:
                    raise ValueError("strategy must be sticky, consume-first, or ordered")
                value = args.value
            else:
                try:
                    value = float(args.value)
                except (ValueError, TypeError):
                    raise ValueError("threshold must be 50–99") from None
                if not 50 <= value <= 99:
                    raise ValueError("threshold must be 50–99")
        store.set_setting(args.key, value)
    return {k: store.setting(k, v) for k, v in defaults.items()}


def extended(store, args):
    """Management commands share the same state used by the router and MCP."""
    code, value = 0, None
    if args.command in {"watch", "tui", "daemon"}:
        asyncio.run(
            watch(store, once=args.once, as_json=args.json, daemon=args.command == "daemon")
        )
    elif args.command == "menubar":
        from agent_rotate.menubar import run as menubar

        menubar(store)
    elif args.command == "service":
        from agent_rotate.service import manage

        value = manage(store, args.action, args.kind)
    elif args.command == "pool":
        if args.action == "set":
            store.set_pool(args.provider, args.name, args.members)
        elif args.action == "remove":
            store.remove_pool(args.provider, args.name)
        if args.action == "list" and args.names:
            print("\n".join(sorted({p["name"] for p in store.pools()})))
        else:
            value = {"pools": store.pools()}
    elif args.command == "map":
        if bool(args.provider) != bool(args.pool):
            raise ValueError("Set both --provider and --pool, or omit both to list mappings")
        if args.pool:
            store.map_pool(args.provider, args.pool, args.path)
        value = {"mappings": store.mappings()}
    elif args.command == "unmap":
        store.unmap(args.provider, args.path)
        value = {"mappings": store.mappings()}
    elif args.command == "sessions":
        from agent_rotate.sessions import saved_sessions

        value = {
            "sessions": (
                [s for s in store.sessions() if not args.provider or s["provider"] == args.provider]
                if args.kind == "live"
                else [
                    s
                    for provider in ("claude", "codex")
                    if not args.provider or provider == args.provider
                    for s in saved_sessions(provider)
                ]
            )
        }
    elif args.command == "resume":
        from agent_rotate.sessions import resume

        code = asyncio.run(
            resume(store, args.provider, args.id, pool=args.pool, account=args.account)
        )
    elif args.command == "health":
        if args.check:
            asyncio.run(Collector(store, Credentials()).once())
        data = snapshot(store)
        value = {
            "accounts": [
                {
                    k: r[k]
                    for k in (
                        "provider",
                        "account",
                        "health",
                        "error",
                        "next_poll_at",
                        "relogin_command",
                    )
                }
                for r in data["accounts"]
            ]
        }
    elif args.command == "config":
        value = settings(store, args)
    elif args.command == "completion":
        from agent_rotate.completion import script

        print(script(args.shell), end="")
    elif args.command == "mcp":
        from agent_rotate.mcp_server import server

        server(store, allow_delegation=args.allow_delegation, workspace=args.workspace).run(
            transport="stdio"
        )
    elif args.command == "job":
        from agent_rotate import jobs

        if args.action == "start":
            prompt = (
                args.prompt_file.read_text()
                if args.prompt_file
                else sys.stdin.read(jobs.MAX_RESULT + 1)
            )
            value = asyncio.run(
                jobs.submit(
                    store,
                    args.provider,
                    prompt,
                    args.cwd,
                    account=args.account,
                    pool=args.pool,
                    model=args.model,
                    access=args.access,
                    timeout_seconds=args.timeout,
                )
            )
        elif args.action == "list":
            value = {"jobs": jobs.rows(store)}
        elif args.action == "result":
            value = jobs.result(store, args.id)
        elif args.action == "cancel":
            jobs.cancel(store, args.id)
            value = {"cancel_requested": args.id}
        else:
            jobs.forget(store, args.id)
            value = {"forgotten": args.id}
    if value is not None:
        print(json.dumps({"schema_version": 1, **value}, indent=2))
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
                print(
                    a.name
                    if args.names
                    else f"{a.provider:7} {a.name:20} {'enabled' if a.enabled else 'disabled'}"
                )
            code = 0
        elif args.command == "status":
            code = asyncio.run(status(store, cached=args.cached, as_json=args.json))
        elif args.command == "doctor":
            code = asyncio.run(doctor(store))
        elif args.command == "history":
            print(json.dumps(store.events(session=args.session), indent=2))
            code = 0
        elif args.command == "run":
            native_args = args.native_args
            if native_args[:1] == ["--"]:
                native_args = native_args[1:]
            code = asyncio.run(
                run(
                    store,
                    args.provider,
                    native_args,
                    args.account,
                    pool=args.pool,
                    strategy=args.strategy or store.setting("strategy", "sticky"),
                    threshold=args.threshold
                    if args.threshold is not None
                    else store.setting("threshold"),
                )
            )
        else:
            code = extended(store, args)
    except KeyboardInterrupt:
        code = 130
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
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
