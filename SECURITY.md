# Security

The router handles subscription access tokens in memory. Keep the local account directories private. Never attach auth.json, Claude Rotate accounts.json, environment dumps, HTTP captures, or full process environments to issues.

- The router binds only to loopback and requires a per-process random header.
- It rejects browser Origin requests and only accepts predefined provider routes.
- Provider destinations are fixed; redirects are never followed with credentials.
- Credentials remain in their original owners' stores. Only account references and metadata are in Agent Rotate's SQLite database, mode 0600 under a 0700 directory.
- Access logs are disabled. Routing history contains provider, local handle, event category, status, timestamp, an opaque router session ID, and an allowlisted decision reason. Session metadata additionally contains working directory, model, pool, and process/heartbeat data.
- No request/response payloads are persisted by the router. The native CLIs still maintain their normal session history.
- No account cleanup, logout, destructive migration, global alias install, or background cron replacement is performed automatically.
- Usage polling is leased per account. Usage-endpoint 429s back off without marking the inference account exhausted. Old readings are visibly stale and cannot drive proactive switching.
- Pools and directory mappings are local metadata; a missing selected pool never widens access. Optional proactive switching preserves the no-partial-replay boundary.
- MCP is stdio-only and cached/read-only by default. Optional delegation has a fixed workspace and read-only native permissions. CLI write access requires an explicit flag, and no permission-bypass flag is added.
- Explicit jobs retain only a final-answer artifact (0600, at most 1 MiB). That artifact can contain task-sensitive text and is separate from routing metadata. Prompts are not command arguments or stored job inputs. Use `job forget` to remove completed results. Agent Rotate does not retain job stderr/tool transcripts; native hooks and provider-side retention remain governed by their owners.
- Desktop alerts are local and opt-in. Menu-bar/daemon services are installed only through explicit service commands. No public status listener, remote webhook, or credential export is provided.

For suspected leaks, do not paste credentials into a public issue. Contact the repository owner privately with a redacted description. Tests must use synthetic values and local servers.
