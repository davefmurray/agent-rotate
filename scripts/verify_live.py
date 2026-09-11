"""Opt-in native CLI smoke: inject one 429, then make one real provider request.

Run manually with --provider claude|codex. Not part of CI. Uses existing registered
accounts and their credential owners, isolated temporary routing metadata, and a
read-only/no-tools prompt. No credentials, bodies, or native transcripts are saved.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web

from agent_rotate.credentials import Credentials
from agent_rotate.launcher import invocation
from agent_rotate.proxy import INFERENCE, UPSTREAMS, Router, clean_headers
from agent_rotate.store import Store


async def verify(provider: str):
    accounts = [a for a in Store().accounts(provider) if a.enabled]
    if len(accounts) < 2:
        raise RuntimeError("This verification requires two registered accounts")
    injected = 0
    upstream_success = 0
    async with aiohttp.ClientSession(
        auto_decompress=False,
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=90),
    ) as client:

        async def relay(request):
            nonlocal injected, upstream_success
            inference = request.method == "POST" and request.path == INFERENCE[provider]
            if inference and not injected:
                injected += 1
                return web.json_response(
                    {"error": {"type": "rate_limit_error", "code": "usage_limit_reached"}},
                    status=429,
                    headers={"Retry-After": "60"},
                )
            async with client.request(
                request.method,
                UPSTREAMS[provider] + str(request.rel_url),
                data=await request.read(),
                headers=clean_headers(request.headers),
                allow_redirects=False,
            ) as response:
                if inference and response.status == 200:
                    upstream_success += 1
                stream = web.StreamResponse(
                    status=response.status, headers=clean_headers(response.headers)
                )
                await stream.prepare(request)
                async for chunk in response.content.iter_chunked(65536):
                    await stream.write(chunk)
                return stream

        app = web.Application(client_max_size=32 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", relay)
        runner = web.AppRunner(app, access_log=None, auto_decompress=False)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        upstream = f"http://127.0.0.1:{runner.addresses[0][1]}"
        try:
            with tempfile.TemporaryDirectory(prefix="agent-rotate-live-") as directory:
                store = Store(Path(directory) / "state")
                for account in accounts[:2]:
                    store.add(account.provider, account.name, account.home)
                router = Router(store, provider, Credentials(), upstream=upstream)
                router.active = accounts[0].name
                process = None
                try:
                    await router.start()
                    prompt = "Reply exactly ROTATE_OK. Do not use tools or inspect files."
                    args = (
                        [
                            "-p",
                            "--tools",
                            "",
                            "--strict-mcp-config",
                            "--mcp-config",
                            '{"mcpServers":{}}',
                            "--",
                            prompt,
                        ]
                        if provider == "claude"
                        else ["exec", "--skip-git-repo-check", "--sandbox", "read-only", prompt]
                    )
                    command, env = invocation(provider, args, router.url, router.key)
                    env.pop("OPENAI_API_KEY", None)
                    env.pop("CODEX_API_KEY", None)
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        env=env,
                        cwd=directory,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    async with asyncio.timeout(120):
                        output, _ = await process.communicate()
                    events = store.events()
                    switches = [e for e in events if e["kind"] == "switch"]
                    result = {
                        "provider": provider,
                        "native_exit": process.returncode,
                        "initial_account": accounts[0].name,
                        "fallback_account": switches[0]["account"] if switches else None,
                        "injected_quota_rejections": injected,
                        "real_successful_requests": upstream_success,
                        "reply_ok": b"ROTATE_OK" in output,
                    }
                    print(json.dumps(result))
                    if not (
                        process.returncode == 0
                        and result["reply_ok"]
                        and injected == 1
                        and upstream_success >= 1
                        and result["fallback_account"] != result["initial_account"]
                        and switches
                    ):
                        raise RuntimeError("Native failover verification did not pass")
                finally:
                    if process and process.returncode is None:
                        process.terminate()
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(process.wait(), 3)
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                    await router.close()
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=["claude", "codex"])
    asyncio.run(verify(parser.parse_args().provider))
