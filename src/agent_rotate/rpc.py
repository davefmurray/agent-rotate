"""Small bounded client for Codex's documented stdio account API."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path


async def account_rpc(home: Path, method: str, params: dict | None = None) -> dict:
    binary = shutil.which("codex")
    if not binary:
        raise RuntimeError("Codex CLI is not on PATH")
    env = dict(os.environ, CODEX_HOME=str(home))
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        env.pop(key, None)
    process = await asyncio.create_subprocess_exec(
        binary,
        "-c",
        'cli_auth_credentials_store="file"',
        "app-server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        limit=2**20,
    )

    async def request(ident: int, rpc_method: str, rpc_params: dict):
        assert process.stdin and process.stdout
        process.stdin.write(
            json.dumps({"id": ident, "method": rpc_method, "params": rpc_params}).encode() + b"\n"
        )
        await process.stdin.drain()
        while line := await process.stdout.readline():
            message = json.loads(line)
            if message.get("id") == ident and "method" not in message:
                if "error" in message:
                    # Do not surface arbitrary RPC error payloads (may include auth data).
                    raise RuntimeError(f"Codex {rpc_method} failed; check account login")
                return message["result"]
            if "id" in message and "method" in message:
                process.stdin.write(
                    json.dumps(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": "Account client does not execute tools",
                            },
                        }
                    ).encode()
                    + b"\n"
                )
                await process.stdin.drain()
        raise RuntimeError("Codex account server exited before responding")

    try:
        async with asyncio.timeout(30):
            await request(
                1,
                "initialize",
                {
                    "clientInfo": {
                        "name": "agent_rotate",
                        "title": "Agent Rotate",
                        "version": "0.1.0",
                    }
                },
            )
            assert process.stdin
            process.stdin.write(b'{"method":"initialized","params":{}}\n')
            await process.stdin.drain()
            return await request(2, method, params or {})
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except TimeoutError:
                process.kill()
                await process.wait()
