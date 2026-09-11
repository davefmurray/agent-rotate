# MCP evaluation scenarios

Use an isolated metadata store with synthetic account references for these checks. Never use real credentials as fixtures. Read-only tools should return structured content, and tool errors should describe a corrective action without exposing secrets.

| Scenario | Expected result |
| --- | --- |
| List Claude quota while one reading is old and the other failed to poll. | Accounts tool reports age/stale/error state without interpreting unknown usage as free capacity or making a provider request. |
| Ask which account serves a host started outside the wrapper. | Current-session tool returns no session and `routed_environment=false`. |
| Two routers use different accounts in different projects. | Sessions tool preserves each router's ID, account, pool and directory. |
| One router has switched after a quota rejection. | Session-filtered history shows bounded metadata for that router, with no prompts, bodies or credentials. |
| A directory binding refers to a removed pool. | Pools tool exposes the mapping and available pools; the agent must explain the broken binding rather than widen it. |
| Wait for an account switch, then cancel the wait. | Monitor stops promptly on MCP cancellation and never launches work. |
| Request delegation from the shipped plugin server. | Delegate/job mutation tools are absent; the server is read-only by default. |
| Enable delegation without a workspace. | Server creation fails with the requirement for an explicit existing workspace. |
| Explicitly delegate a small read-only task in the configured workspace. | A separate native job is queued with restricted access and a private final result; it does not resume the host conversation. Use fake native CLIs for automated checks. |
| Read or cancel a job owned by another workspace. | Workspace-bound MCP tools refuse it; job listing omits it. |
