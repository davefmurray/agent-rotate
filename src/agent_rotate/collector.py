"""One usage poll per account across concurrent routers and display processes."""

from __future__ import annotations

import asyncio
import random
import time

import aiohttp

from agent_rotate.credentials import CredentialError, Credentials, UsageError
from agent_rotate.rpc import AccountRPCError
from agent_rotate.store import Store


class Collector:
    def __init__(self, store: Store, credentials: Credentials):
        self.store, self.credentials = store, credentials

    async def poll(self, account, *, active: bool = False) -> bool:
        now = time.time()
        owner = self.store.claim_poll(account, now)
        if not owner:
            return False
        old = self.store.poll_state(account)
        _, previous = self.store.usage(account)
        interval, error, failures = 180.0, None, 0
        retry_at = 0
        try:
            async with asyncio.timeout(90):
                windows = await self.credentials.usage(account)
            self.store.set_usage(account, windows)
            self.store.set_health(account, "ready")
            prior = {(w.get("bucket"), w["name"]): w["used_percent"] for w in previous}
            moving = any(
                abs(w["used_percent"] - prior.get((w.get("bucket"), w["name"]), w["used_percent"]))
                >= 1
                for w in windows
            )
            floor = 180 if account.provider == "claude" else 120
            interval = (
                max(floor, old["interval"] / 2)
                if moving
                else min(300 if active else 600, max(floor, old["interval"] * 1.5))
            )
        except (CredentialError, AccountRPCError) as exc:
            error = "relogin_required" if exc.permanent else "credential_unavailable"
            if exc.permanent:
                self.store.set_health(account, "relogin_required", "revoked_login")
        except UsageError as exc:
            error, retry_at = exc.kind, exc.retry_at
        except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError):
            error = "usage_unavailable"
        except asyncio.CancelledError:
            error = "poll_cancelled"
            raise
        finally:
            if error:
                failures = old["failures"] + 1
                interval = min(1800, 180 * 2 ** min(failures, 4))
            self.store.finish_poll(
                account,
                owner,
                next_poll=max(time.time() + interval * random.uniform(1, 1.1), retry_at),
                interval=interval,
                failures=failures,
                error=error,
            )
        return error is None

    async def once(self, provider: str | None = None):
        active = {(s["provider"], s["account"]) for s in self.store.sessions()}
        # Bound subprocess/network concurrency as account pools grow.
        semaphore = asyncio.Semaphore(2)

        async def one(account):
            async with semaphore:
                await self.poll(account, active=(account.provider, account.name) in active)

        await asyncio.gather(*(one(a) for a in self.store.accounts(provider) if a.enabled))

    async def run(self, provider: str | None = None):
        while True:
            await self.once(provider)
            if self.store.setting("notifications", False):
                from agent_rotate.dashboard import snapshot
                from agent_rotate.notifications import check_alerts

                await check_alerts(self.store, snapshot(self.store))
            await asyncio.sleep(10)
