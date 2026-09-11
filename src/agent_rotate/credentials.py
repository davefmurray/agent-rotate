"""Read existing stores; let their native owners perform OAuth refresh."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import aiohttp

from agent_rotate.rpc import AccountRPCError, account_rpc
from agent_rotate.store import Account


class CredentialError(RuntimeError):
    def __init__(self, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class UsageError(RuntimeError):
    def __init__(self, kind: str, retry_at: float = 0):
        super().__init__("Usage unavailable; check cached status")
        self.kind, self.retry_at = kind, retry_at


@dataclass(frozen=True)
class Credential:
    token: str = field(repr=False)
    account_id: str | None = field(default=None, repr=False)
    identity: str | None = field(default=None, repr=False)


def claude_paths():
    from claude_rotate.config import paths

    return paths()


def claude_accounts():
    from claude_rotate.accounts import Store

    return Store(claude_paths()).load()


def expiry(token: str) -> float:
    try:
        body = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["exp"])
    except (IndexError, ValueError, KeyError, TypeError):
        return 0


def timestamp(value) -> float | None:
    if isinstance(value, (float, int)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def claude_windows(payload: dict) -> list[dict]:
    return [
        {
            "name": name,
            "used_percent": float(w["utilization"]),
            "resets_at": timestamp(w.get("resets_at")),
            "period_seconds": 18000
            if name == "five_hour"
            else (604800 if name.startswith("seven_day") else None),
        }
        for name, w in payload.items()
        if isinstance(w, dict)
        and isinstance(w.get("utilization"), (int, float))
        and math.isfinite(w["utilization"])
        and w["utilization"] >= 0
    ]


def codex_windows(payload: dict) -> list[dict]:
    buckets = payload.get("rateLimitsByLimitId") or {"codex": payload.get("rateLimits") or {}}
    result = []
    for bucket, limits in buckets.items():
        for name in ("primary", "secondary"):
            w = limits.get(name)
            if (
                isinstance(w, dict)
                and isinstance(w.get("usedPercent"), (int, float))
                and math.isfinite(w["usedPercent"])
                and w["usedPercent"] >= 0
            ):
                result.append(
                    {
                        "name": name,
                        "bucket": bucket,
                        "used_percent": float(w["usedPercent"]),
                        "resets_at": timestamp(w.get("resetsAt")),
                        "period_seconds": (
                            w["windowDurationMins"] * 60
                            if isinstance(w.get("windowDurationMins"), (int, float))
                            else None
                        ),
                    }
                )
    return result


class Credentials:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._claude_synced = 0.0

    async def get(self, account: Account, *, refresh: bool = False) -> Credential:
        key = "claude" if account.provider == "claude" else account.home
        async with self._locks.setdefault(key, asyncio.Lock()):
            try:
                if account.provider == "claude":
                    return await self._claude(account, refresh)
                return await self._codex(account, refresh)
            except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
                if isinstance(exc, CredentialError):
                    raise
                raise CredentialError(
                    f"{account.provider}/{account.name}: credential unavailable; "
                    "check login/network",
                    permanent=isinstance(exc, AccountRPCError) and exc.permanent,
                ) from None

    async def _claude(self, account: Account, refresh: bool) -> Credential:
        if Path(account.home) != claude_paths().accounts_file:
            raise CredentialError("Claude Rotate store moved; run import-claude again")
        if refresh or time.monotonic() - self._claude_synced > 60:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "claude_rotate",
                "sync-credentials",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), 45)
            except (TimeoutError, asyncio.CancelledError):
                proc.kill()
                await proc.wait()
                raise
            if proc.returncode:
                raise CredentialError("Claude Rotate credential sync failed")
            self._claude_synced = time.monotonic()
        source = claude_accounts()[account.name]
        if source.disabled:
            raise CredentialError(f"claude/{account.name}: disabled in Claude Rotate")
        if not source.runtime_token:
            raise CredentialError(f"claude/{account.name}: no access token")
        return Credential(source.runtime_token, identity=(source.email or source.name).casefold())

    async def _codex(self, account: Account, refresh: bool) -> Credential:
        path = Path(account.home) / "auth.json"
        raw = json.loads(path.read_text())
        if raw.get("auth_mode") not in (None, "chatgpt"):
            raise CredentialError("Only ChatGPT subscription logins belong in the Codex pool")
        tokens = raw["tokens"]
        token = tokens["access_token"]
        if refresh or expiry(token) < time.time() + 300:
            await account_rpc(Path(account.home), "account/read", {"refreshToken": True})
            tokens = json.loads(path.read_text())["tokens"]
            token = tokens["access_token"]
        if not token or not tokens.get("account_id"):
            raise CredentialError(f"codex/{account.name}: incomplete subscription login")
        return Credential(token, tokens["account_id"])

    async def usage(self, account: Account) -> list[dict]:
        if account.provider == "codex":
            await self.get(account)
            return codex_windows(await account_rpc(Path(account.home), "account/rateLimits/read"))
        credential = await self.get(account)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as client:
            async with client.get(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {credential.token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": "claude-code/2.1.117",
                },
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    from agent_rotate.proxy import cooldown_until

                    kind = (
                        "usage_429"
                        if response.status == 429
                        else ("usage_auth" if response.status in (401, 403) else "usage_http")
                    )
                    raise UsageError(
                        kind,
                        cooldown_until(response.headers, b"{}", time.time())
                        if response.status == 429
                        else 0,
                    )
                return claude_windows(await response.json())
