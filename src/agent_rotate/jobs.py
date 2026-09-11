"""Explicit native jobs. Prompts travel over stdin; only final results are retained."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from agent_rotate.store import Store

MAX_RESULT = 1024 * 1024


def job_dir(store: Store, ident: str) -> Path:
    if len(ident) != 32 or uuid.UUID(ident).hex != ident:
        raise ValueError("Invalid job ID")
    return store.root / "jobs" / ident


def rows(store: Store, ident: str | None = None) -> list[dict]:
    with store.connect() as db:
        records = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM jobs WHERE (? IS NULL OR id=?) ORDER BY created DESC LIMIT 100",
                (ident, ident),
            )
        ]
    for record in records:
        if (
            record["state"] in {"queued", "running"}
            and (record["heartbeat"] or record["created"]) < time.time() - 60
        ):
            record["state"] = "interrupted"
    return records


def cancel(store: Store, ident: str):
    if not rows(store, ident):
        raise ValueError("Job not found")
    with store.connect() as db:
        db.execute(
            "UPDATE jobs SET cancel=1 WHERE id=? AND state IN ('queued','running')", (ident,)
        )


def result(store: Store, ident: str) -> dict:
    records = rows(store, ident)
    if not records:
        raise ValueError("Job not found")
    record = records[0]
    path = job_dir(store, ident) / "result.txt"
    record["result"] = path.read_text()[:MAX_RESULT] if path.is_file() else None
    return record


def forget(store: Store, ident: str):
    records = rows(store, ident)
    if not records or records[0]["state"] in {"queued", "running"}:
        raise ValueError("Only a completed/interrupted job can be forgotten")
    directory = job_dir(store, ident)
    (directory / "result.txt").unlink(missing_ok=True)
    if directory.is_dir():
        directory.rmdir()
    with store.connect() as db:
        db.execute("DELETE FROM jobs WHERE id=?", (ident,))


async def submit(
    store: Store,
    provider: str,
    prompt: str,
    cwd: Path,
    *,
    account: str | None = None,
    pool: str | None = None,
    model: str | None = None,
    access: str = "read-only",
    timeout_seconds: int = 600,
) -> dict:
    cwd = await asyncio.to_thread(lambda: cwd.expanduser().resolve())
    if provider not in {"claude", "codex"} or not cwd.is_dir():
        raise ValueError("Choose a native provider and an existing working directory")
    if not prompt.strip() or len(prompt.encode()) > MAX_RESULT:
        raise ValueError("Prompt must be nonempty and at most 1 MiB")
    if access not in {"read-only", "workspace-write"} or not 10 <= timeout_seconds <= 3600:
        raise ValueError("Invalid job access or timeout (10–3600 seconds)")
    if account and pool:
        raise ValueError("Choose an account or a pool")
    if not account and not pool:
        pool = store.resolve_pool(provider, cwd)
    candidates = [
        a
        for a in store.accounts(provider)
        if a.enabled
        and (not account or a.name == account)
        and (not pool or a.name in store.pool_members(provider, pool))
    ]
    if not candidates:
        raise ValueError("No enabled accounts match the job selection")
    ident = uuid.uuid4().hex
    directory = job_dir(store, ident)
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    with store.connect() as db:
        db.execute(
            "INSERT INTO jobs(id,provider,account,pool,cwd,created,state) VALUES (?,?,?,?,?,?,?)",
            (ident, provider, account, pool, str(cwd), time.time(), "queued"),
        )
    env = dict(os.environ, AGENT_ROTATE_HOME=str(store.root))
    for key in ("AGENT_ROTATE_PROXY_KEY", "AGENT_ROTATE_SESSION_ID", "CLAUDECODE"):
        env.pop(key, None)

    def launch():
        child = subprocess.Popen(
            [sys.executable, "-m", "agent_rotate.jobs", ident],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        assert child.stdin
        try:
            child.stdin.write(
                json.dumps(
                    {"prompt": prompt, "model": model, "access": access, "timeout": timeout_seconds}
                ).encode()
            )
        finally:
            child.stdin.close()

    await asyncio.to_thread(launch)
    return {
        "id": ident,
        "state": "queued",
        "provider": provider,
        "cwd": str(cwd),
        "access": access,
        "retains_final_result": True,
    }


def native_args(provider: str, access: str, model: str | None) -> list[str]:
    if provider == "codex":
        args = ["exec", "--json", "--ephemeral", "--sandbox", access, "--skip-git-repo-check"]
    else:
        args = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
            "--permission-mode",
            "plan" if access == "read-only" else "acceptEdits",
            "--permission-prompts",
            "none",
        ]
    if model:
        args.extend(["--model", model])
    if provider == "codex":
        args.append("-")
    return args


async def worker(store: Store, ident: str, payload: dict):
    record = rows(store, ident)[0]
    command = [sys.executable, "-m", "agent_rotate", "run"]
    if record["account"]:
        command.extend(["--account", record["account"]])
    if record["pool"]:
        command.extend(["--pool", record["pool"]])
    command.extend(
        [record["provider"], *native_args(record["provider"], payload["access"], payload["model"])]
    )
    child = None
    state, code, final = "failed", None, None
    started = time.time()
    with store.connect() as db:
        db.execute(
            "UPDATE jobs SET state='running',started=?,heartbeat=? WHERE id=?",
            (started, started, ident),
        )
    try:
        child = await asyncio.create_subprocess_exec(
            *command,
            cwd=record["cwd"],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            limit=2 * MAX_RESULT,
        )

        async def consume():
            nonlocal final
            assert child.stdout and child.stdin
            child.stdin.write(payload["prompt"].encode())
            await child.stdin.drain()
            child.stdin.close()
            while line := await child.stdout.readline():
                with contextlib.suppress(ValueError, AttributeError, TypeError):
                    event = json.loads(line)
                    value = None
                    if event.get("type") == "result":
                        value = event.get("result")
                    elif (
                        event.get("type") == "item.completed"
                        and event.get("item", {}).get("type") == "agent_message"
                    ):
                        value = event["item"].get("text")
                    if isinstance(value, str):
                        if len(value.encode()) > MAX_RESULT:
                            raise RuntimeError(
                                "Final result exceeds the private artifact size limit"
                            )
                        final = value
            return await child.wait()

        reader = asyncio.create_task(consume())
        try:
            while not reader.done():
                with store.connect() as db:
                    db.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time(), ident))
                    cancelled = db.execute(
                        "SELECT cancel FROM jobs WHERE id=?", (ident,)
                    ).fetchone()[0]
                if cancelled or time.time() - started >= payload["timeout"]:
                    state = "cancelled" if cancelled else "timed_out"
                    break
                await asyncio.sleep(0.5)
            else:
                code = await reader
                state = "completed" if code == 0 and final is not None else "failed"
        finally:
            if not reader.done():
                reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError, ValueError, OSError):
                await reader
    except (RuntimeError, ValueError, OSError):
        state = "failed"
    finally:
        if child and child.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(child.wait(), 4)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                await child.wait()
        if state == "completed" and final is not None:
            path = job_dir(store, ident) / "result.txt"
            path.write_text(final)
            path.chmod(0o600)
        with store.connect() as db:
            db.execute(
                "UPDATE jobs SET state=?,exit_code=?,ended=?,heartbeat=? WHERE id=?",
                (state, code, time.time(), time.time(), ident),
            )


if __name__ == "__main__":
    os.umask(0o077)
    # The private parent pipe supplies the prompt; it is never a command argument.
    data = json.loads(sys.stdin.buffer.read(2 * MAX_RESULT))
    asyncio.run(worker(Store(), sys.argv[1], data))
