"""Authenticated loopback router. Retry only before committing the response."""

from __future__ import annotations

import contextlib
import hmac
import json
import math
import secrets
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime

import aiohttp
from aiohttp import web

from agent_rotate.credentials import Credential, CredentialError, Credentials
from agent_rotate.store import Account, Store, availability

UPSTREAMS = {
    "claude": "https://api.anthropic.com",
    "codex": "https://chatgpt.com/backend-api/codex",
}
PATHS = {
    "claude": {
        ("POST", "/v1/messages"),
        ("POST", "/v1/messages/count_tokens"),
        ("GET", "/v1/models"),
        ("GET", "/api/oauth/usage"),
    },
    "codex": {("POST", "/responses"), ("POST", "/responses/compact"), ("GET", "/models")},
}
INFERENCE = {"claude": "/v1/messages", "codex": "/responses"}
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
IDENTITY_HEADERS = {
    "authorization",
    "x-api-key",
    "chatgpt-account-id",
    "openai-organization",
    "openai-project",
    "cookie",
    "x-agent-rotate-key",
    "x-codex-turn-state",
    "x-openai-actor-authorization",
}


def clean_headers(headers, *, request: bool = False) -> dict[str, str]:
    blocked = HOP_HEADERS | {"set-cookie", "x-codex-turn-state"}
    blocked |= {s.strip().lower() for s in headers.get("Connection", "").split(",")}
    if request:
        blocked |= IDENTITY_HEADERS
    return {k: v for k, v in headers.items() if k.lower() not in blocked}


def auth_headers(headers, provider: str, credential: Credential) -> dict[str, str]:
    result = clean_headers(headers, request=True)
    result["Authorization"] = f"Bearer {credential.token}"
    if provider == "codex":
        result["ChatGPT-Account-Id"] = credential.account_id or ""
    else:
        # OAuth subscription requests need this beta, including when Claude uses a gateway.
        current = next((v for k, v in result.items() if k.lower() == "anthropic-beta"), "")
        result = {k: v for k, v in result.items() if k.lower() != "anthropic-beta"}
        result["anthropic-beta"] = ",".join(
            dict.fromkeys([x for x in current.split(",") if x] + ["oauth-2025-04-20"])
        )
    return result


def cooldown_until(headers, body: bytes, now: float) -> float:
    """Use provider reset data when available; default to a short account cooldown."""
    times = []
    retry = headers.get("Retry-After") or headers.get("retry-after")
    if retry:
        try:
            times.append(now + max(0, float(retry)))
        except ValueError:
            with contextlib.suppress(ValueError, TypeError, OverflowError):
                times.append(parsedate_to_datetime(retry).timestamp())
    try:
        data = json.loads(body)
        error = data.get("error", data)
        if isinstance(error, dict):
            for key in ("resets_at", "reset_at"):
                if isinstance(error.get(key), (float, int)):
                    times.append(float(error[key]))
            for key in ("resets_in_seconds", "retry_after"):
                if isinstance(error.get(key), (float, int)):
                    times.append(now + max(0, float(error[key])))
    except (ValueError, TypeError, AttributeError):
        pass
    valid = [t for t in times if math.isfinite(t) and t > now]
    return max(valid) if valid else now + 60


def initial_quota_event(data: bytes) -> bool:
    """Only the first SSE event can qualify; arbitrary assistant text never does."""
    try:
        lines = data.decode().splitlines()
        payload = json.loads(
            "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
        )
        if payload.get("type") == "error":
            error = payload.get("error") or {}
        elif payload.get("type") == "response.failed":
            error = (payload.get("response") or {}).get("error") or {}
        else:
            return False
        return error.get("type") in {"rate_limit_error", "usage_limit_reached"} or error.get(
            "code"
        ) in {"rate_limit_exceeded", "usage_limit_reached", "insufficient_quota"}
    except (ValueError, UnicodeError, AttributeError, TypeError):
        return False


class Router:
    def __init__(
        self,
        store: Store,
        provider: str,
        credentials: Credentials,
        *,
        account: str | None = None,
        reporter: Callable[[str], None] | None = None,
        upstream: str | None = None,
    ):
        self.store, self.provider, self.credentials = store, provider, credentials
        self.restrict_account = account
        self.report = reporter or (lambda _: None)
        self.upstream = upstream or UPSTREAMS[provider]
        self.key = secrets.token_urlsafe(32)
        self.active: str | None = None
        self.client: aiohttp.ClientSession | None = None
        self.runner: web.AppRunner | None = None
        self.url = ""

    async def start(self):
        # Forward compression unchanged, including Codex zstd request bodies.
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=300),
            auto_decompress=False,
            skip_auto_headers={"Accept-Encoding"},
        )
        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.runner = web.AppRunner(
            app, access_log=None, auto_decompress=False, handler_cancellation=True
        )
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{self.runner.addresses[0][1]}"
        return self

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
        if self.client:
            await self.client.close()

    def choose(self, model: str, tried: set[str]) -> Account | None:
        now = time.time()
        choices = []
        for account in self.store.accounts(self.provider):
            if not account.enabled or account.name in tried:
                continue
            if self.restrict_account and account.name != self.restrict_account:
                continue
            until, headroom = availability(self.store, account, model, now)
            if until <= now:
                choices.append((account.name == self.active, headroom, account.name, account))
        return max(choices, key=lambda c: c[:3])[-1] if choices else None

    def exhausted(self, model: str) -> web.Response:
        now = time.time()
        waits = [
            availability(self.store, a, model, now)[0]
            for a in self.store.accounts(self.provider)
            if a.enabled and (not self.restrict_account or a.name == self.restrict_account)
        ]
        wait = max(1, math.ceil(min((t for t in waits if t > now), default=now + 60) - now))
        self.store.event(self.provider, "", "exhausted", 429)
        message = (
            "All eligible accounts are cooling down or unavailable. Check agent-rotate status."
        )
        error = {"type": "rate_limit_error", "code": "usage_limit_reached", "message": message}
        return web.json_response(
            {"type": "error", "error": error}, status=429, headers={"Retry-After": str(wait)}
        )

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if request.headers.get("Origin") or not hmac.compare_digest(
            request.headers.get("x-agent-rotate-key", "").encode(), self.key.encode()
        ):
            return web.json_response({"error": "Unauthorized local request"}, status=401)
        if (request.method, request.path) not in PATHS[
            self.provider
        ] or "%" in request.raw_path.split("?", 1)[0]:
            return web.json_response({"error": "Unsupported provider route"}, status=404)
        if request.headers.get("Upgrade"):
            return web.json_response({"error": "Use HTTP streaming"}, status=426)
        body = await request.read()
        model = "*"
        if not request.headers.get("Content-Encoding"):
            with contextlib.suppress(ValueError, UnicodeError, AttributeError):
                value = json.loads(body).get("model")
                if isinstance(value, str):
                    model = value[:200]
        may_rotate = (
            request.method == "POST"
            and request.path == INFERENCE[self.provider]
            and not request.headers.get("Content-Encoding")
        )
        # Incremental/account-bound request state cannot be replayed to another account.
        with contextlib.suppress(ValueError, UnicodeError, AttributeError):
            if json.loads(body).get("previous_response_id"):
                may_rotate = False
        tried: set[str] = set()
        tried_identities: set[str] = set()
        assert self.client
        while account := self.choose(model, tried):
            tried.add(account.name)
            try:
                credential = await self.credentials.get(account)
            except CredentialError:
                self.store.cooldown(account, "*", time.time() + 60, "auth")
                self.store.event(self.provider, account.name, "auth", 401)
                self.report(f"{account.name}: login unavailable; skipping")
                continue
            identity = credential.identity or credential.account_id or credential.token
            if identity in tried_identities:
                continue
            tried_identities.add(identity)
            if self.active and self.active != account.name:
                self.store.event(self.provider, account.name, "switch", 0)
                self.report(f"{self.provider}: {self.active} → {account.name}")
            elif not self.active:
                self.report(f"{self.provider}: using {account.name}")
            self.active = account.name
            try:
                for auth_attempt in range(2):
                    response = await self.client.request(
                        request.method,
                        self.upstream + str(request.rel_url),
                        data=body,
                        headers=auth_headers(request.headers, self.provider, credential),
                        allow_redirects=False,
                    )
                    if response.status != 401 or auth_attempt:
                        break
                    response.release()
                    fresh = await self.credentials.get(account, refresh=True)
                    credential = fresh
                async with response:
                    if 300 <= response.status < 400:
                        # Also prevent the native client from following a redirect while
                        # carrying its own credentials or the local capability header.
                        return web.json_response(
                            {
                                "error": {
                                    "type": "api_error",
                                    "message": "Provider redirect refused",
                                }
                            },
                            status=502,
                        )
                    if response.status == 429 and may_rotate:
                        error_body = await response.content.read(65536)
                        self.quota(account, model, response.headers, error_body)
                        continue
                    prefix = bytearray()
                    if (
                        may_rotate
                        and response.status == 200
                        and "text/event-stream" in response.headers.get("Content-Type", "")
                        and not response.headers.get("Content-Encoding")
                    ):
                        # Buffer only the first complete SSE event, bounded by 64 KiB.
                        # A comment/ping/lifecycle event commits the stream too.
                        while len(prefix) < 65536:
                            piece = await response.content.read(1)
                            if not piece:
                                break
                            prefix += piece
                            if prefix.endswith((b"\n\n", b"\r\n\r\n")):
                                break
                        if initial_quota_event(prefix):
                            self.quota(account, model, response.headers, b"{}")
                            continue
                    self.store.event(self.provider, account.name, "request", response.status)
                    outgoing = web.StreamResponse(
                        status=response.status, headers=clean_headers(response.headers)
                    )
                    await outgoing.prepare(request)
                    try:
                        if prefix:
                            await outgoing.write(prefix)
                        async for chunk in response.content.iter_chunked(65536):
                            await outgoing.write(chunk)
                        await outgoing.write_eof()
                    except (aiohttp.ClientError, ConnectionError, TimeoutError):
                        # Headers/content already committed: close, never synthesize a success
                        # or replay the request. Native CLI owns stream recovery.
                        if request.transport:
                            request.transport.close()
                    return outgoing
            except CredentialError:
                self.store.event(self.provider, account.name, "auth", 401)
                return web.json_response(
                    {
                        "error": {
                            "type": "authentication_error",
                            "message": "Account refresh failed; sign in again",
                        }
                    },
                    status=401,
                )
            except (aiohttp.ClientError, TimeoutError):
                self.store.event(self.provider, account.name, "transport", 502)
                return web.json_response(
                    {
                        "error": {
                            "type": "api_error",
                            "message": "Provider connection failed; request was not replayed",
                        }
                    },
                    status=502,
                )
        return self.exhausted(model)

    def quota(self, account: Account, model: str, headers, body: bytes):
        until = cooldown_until(headers, body, time.time())
        self.store.cooldown(account, model, until)
        self.store.event(self.provider, account.name, "quota", 429)
        self.report(
            f"{account.name}: quota reached; cooling down for {math.ceil(until - time.time())}s"
        )
