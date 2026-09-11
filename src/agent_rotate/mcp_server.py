"""Local stdio MCP; read-only by default, explicit workspace-bound jobs optional."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent_rotate import jobs
from agent_rotate.dashboard import snapshot
from agent_rotate.store import Store


def server(
    store: Store, *, allow_delegation: bool = False, workspace: Path | None = None
) -> FastMCP:
    if allow_delegation and (workspace is None or not workspace.expanduser().resolve().is_dir()):
        raise ValueError("Delegation needs an explicit existing --workspace directory")
    workspace = workspace.expanduser().resolve() if workspace else None
    mcp = FastMCP(
        "Agent Rotate",
        instructions="Inspect cached Claude/Codex quota and native routing. "
        "Unknown and stale usage is not available capacity. Jobs require explicit user intent.",
    )
    readonly = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    ident = os.environ.get("AGENT_ROTATE_SESSION_ID")

    @mcp.tool(annotations=readonly, structured_output=True)
    def agent_rotate_accounts(provider: Literal["claude", "codex"] | None = None) -> dict[str, Any]:
        """Cached quota, advisory forecasts and credential health; no provider requests."""
        data = snapshot(store)
        return {
            "schema_version": 1,
            "accounts": [
                r for r in data["accounts"] if provider is None or r["provider"] == provider
            ],
        }

    @mcp.tool(annotations=readonly, structured_output=True)
    def agent_rotate_current_session() -> dict[str, Any]:
        """Identify this session's routed account, or report an unrouted/closed session."""
        return {
            "schema_version": 1,
            "session": snapshot(store, session=ident)["current_session"],
            "routed_environment": ident is not None,
        }

    @mcp.tool(annotations=readonly, structured_output=True)
    def agent_rotate_sessions() -> dict[str, Any]:
        """Live router sessions with their own account, pool, model and working directory."""
        return {"schema_version": 1, "sessions": store.sessions()}

    @mcp.tool(annotations=readonly, structured_output=True)
    def agent_rotate_history(session_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Bounded routing metadata; no prompts, transcripts, or credentials."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return {"schema_version": 1, "events": store.events(limit, session_id or ident)}

    @mcp.tool(annotations=readonly, structured_output=True)
    def agent_rotate_pools() -> dict[str, Any]:
        """Configured provider-specific account pools and directory bindings."""
        return {"schema_version": 1, "pools": store.pools(), "mappings": store.mappings()}

    @mcp.tool(annotations=readonly, structured_output=True)
    async def agent_rotate_monitor(seconds: int = 10) -> dict[str, Any]:
        """Wait up to 30 seconds for a live session's account/state to change; cancellable."""
        if not 0 <= seconds <= 30:
            raise ValueError("seconds must be between 0 and 30")

        def signature():
            return [(s["id"], s["account"], s["reason"]) for s in store.sessions()]

        previous, deadline = signature(), time.monotonic() + seconds
        while signature() == previous and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
        return {
            "schema_version": 1,
            "changed": signature() != previous,
            "sessions": store.sessions(),
        }

    if allow_delegation:

        def require_workspace_job(job_id):
            records = jobs.rows(store, job_id)
            if not records or records[0]["cwd"] != str(workspace):
                raise ValueError("Job is not in this MCP server's workspace")

        spending = ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
        )

        @mcp.tool(annotations=spending, structured_output=True)
        async def agent_rotate_delegate(
            provider: Literal["claude", "codex"],
            prompt: str,
            account: str | None = None,
            pool: str | None = None,
            model: str | None = None,
            timeout_seconds: int = 600,
        ) -> dict[str, Any]:
            """Start a separate read-only native job in the server's configured workspace.

            Consumes real subscription quota. Only call for a user-requested delegated task.
            It does not continue or repair this conversation. Final output is stored privately.
            """
            return await jobs.submit(
                store,
                provider,
                prompt,
                workspace,
                account=account,
                pool=pool,
                model=model,
                timeout_seconds=timeout_seconds,
            )

        @mcp.tool(annotations=readonly, structured_output=True)
        def agent_rotate_jobs() -> dict[str, Any]:
            """Recent delegated job metadata, without prompt or output content."""
            return {
                "schema_version": 1,
                "jobs": [r for r in jobs.rows(store) if r["cwd"] == str(workspace)],
            }

        @mcp.tool(annotations=readonly, structured_output=True)
        def agent_rotate_job_result(job_id: str) -> dict[str, Any]:
            """Collect the private final result of an explicitly started job."""
            require_workspace_job(job_id)
            return {"schema_version": 1, "job": jobs.result(store, job_id)}

        @mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
            )
        )
        def agent_rotate_cancel_job(job_id: str) -> dict[str, Any]:
            """Cancel a delegated job; its worker stops the native process group."""
            require_workspace_job(job_id)
            jobs.cancel(store, job_id)
            return {"schema_version": 1, "cancel_requested": True, "job_id": job_id}

    return mcp
