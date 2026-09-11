"""Keep native UX and approvals; apply routing only to the launched process."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import sys
from pathlib import Path

from agent_rotate.collector import Collector
from agent_rotate.credentials import Credentials
from agent_rotate.proxy import Router
from agent_rotate.store import Store


def invocation(
    provider: str, args: list[str], url: str, key: str, *, env: dict[str, str] | None = None
) -> tuple[list[str], dict[str, str]]:
    binary = shutil.which(provider)
    if not binary:
        raise ValueError(f"Install {provider} and put its real binary on PATH")
    child_env = dict(os.environ if env is None else env)
    child_env["AGENT_ROTATE_PROXY_KEY"] = key
    if provider == "claude":
        child_env["ANTHROPIC_BASE_URL"] = url
        # Keep native claude.ai auth for connectors and account features. Tokens
        # supplied as environment auth overrides disable those native features.
        for auth_key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
            child_env.pop(auth_key, None)
        custom = child_env.get("ANTHROPIC_CUSTOM_HEADERS", "")
        custom = "\n".join(
            line
            for line in custom.splitlines()
            if not line.lower().startswith("x-agent-rotate-key:")
        )
        child_env["ANTHROPIC_CUSTOM_HEADERS"] = (custom + f"\nx-agent-rotate-key: {key}").strip()
        return [binary, *args], child_env
    if any(
        a in {"--remote", "--oss", "--local-provider", "app", "app-server", "login", "logout"}
        or a.startswith(("--remote=", "--local-provider="))
        for a in args
    ):
        raise ValueError("Launch a local Codex session, exec, review, or resume through the router")
    if any(a.startswith(("model_provider=", "model_providers.", "openai_base_url=")) for a in args):
        raise ValueError("Provider overrides conflict with account routing")
    settings = {
        "model_provider": "agent_rotate",
        "model_providers.agent_rotate.name": "OpenAI",
        "model_providers.agent_rotate.base_url": url,
        "model_providers.agent_rotate.wire_api": "responses",
        "model_providers.agent_rotate.requires_openai_auth": True,
        "model_providers.agent_rotate.supports_websockets": False,
        "features.enable_request_compression": False,
        "model_providers.agent_rotate.env_http_headers": {
            "x-agent-rotate-key": "AGENT_ROTATE_PROXY_KEY"
        },
    }
    overrides = []
    for name, value in settings.items():
        if isinstance(value, dict):
            encoded = '{ "x-agent-rotate-key" = "AGENT_ROTATE_PROXY_KEY" }'
        else:
            encoded = json.dumps(value)
        overrides.extend(["-c", f"{name}={encoded}"])
    return [binary, *overrides, *args], child_env


async def run(
    store: Store,
    provider: str,
    args: list[str],
    account: str | None = None,
    *,
    pool: str | None = None,
    strategy: str = "sticky",
    threshold: float | None = None,
    cwd: Path | None = None,
) -> int:
    cwd = (cwd or Path.cwd()).expanduser().resolve()
    args = list(args)
    if provider == "codex":
        # Account mapping follows Codex's actual project directory, including -C.
        for i, arg in enumerate(args):
            if arg == "--":
                break
            if arg in {"-C", "--cd"} and i + 1 < len(args):
                cwd = await asyncio.to_thread(
                    lambda base=cwd, value=args[i + 1]: (base / Path(value).expanduser()).resolve()
                )
                args[i + 1] = str(cwd)
                break
            if arg.startswith("--cd="):
                cwd = await asyncio.to_thread(
                    lambda base=cwd, value=arg: (
                        base / Path(value.split("=", 1)[1]).expanduser()
                    ).resolve()
                )
                args[i] = "--cd=" + str(cwd)
                break
    if not cwd.is_dir():
        raise ValueError("Working directory does not exist")
    if account and pool:
        raise ValueError("Choose an account or a pool, not both")
    if not account and not pool:
        pool = store.resolve_pool(provider, cwd)
    if not any(a.enabled for a in store.accounts(provider)):
        raise ValueError(f"No enabled {provider} accounts; run agent-rotate login/import first")
    if account and not any(a.name == account and a.enabled for a in store.accounts(provider)):
        raise ValueError("Selected account does not exist or is disabled")
    if pool and not any(
        a.enabled and a.name in store.pool_members(provider, pool) for a in store.accounts(provider)
    ):
        raise ValueError("Selected pool has no enabled accounts")
    credentials = Credentials()
    collector = Collector(store, credentials)
    await collector.once(provider)
    router = Router(
        store,
        provider,
        credentials,
        account=account,
        pool=pool,
        strategy=strategy,
        threshold=threshold,
        cwd=str(cwd),
        reporter=lambda m: print(f"\r\n[agent-rotate] {m}", file=sys.stderr),
    )
    child = None
    loop = asyncio.get_running_loop()
    installed = []
    background = None
    try:
        await router.start()
        command, env = invocation(provider, args, router.url, router.key)
        env["AGENT_ROTATE_SESSION_ID"] = router.session_id
        if provider == "codex":
            env.pop("OPENAI_API_KEY", None)
            env.pop("CODEX_API_KEY", None)
        child = await asyncio.create_subprocess_exec(*command, env=env, cwd=cwd)
        background = asyncio.create_task(collector.run(provider))
        # Ctrl-C belongs to the native CLI (often cancels one turn). It must not kill
        # the router out from under an otherwise live session.
        loop.add_signal_handler(signal.SIGINT, lambda: None)
        installed.append(signal.SIGINT)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            loop.add_signal_handler(
                sig,
                lambda s=sig: child.send_signal(s) if child and child.returncode is None else None,
            )
            installed.append(sig)
        code = await child.wait()
        return code if code >= 0 else 128 - code
    finally:
        if background:
            background.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await background
        for sig in installed:
            loop.remove_signal_handler(sig)
        if child and child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 3)
            except TimeoutError:
                child.kill()
                await child.wait()
        await router.close()
