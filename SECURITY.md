# Security

The router handles subscription access tokens in memory. Keep the local account directories private. Never attach auth.json, Claude Rotate accounts.json, environment dumps, HTTP captures, or full process environments to issues.

- The router binds only to loopback and requires a per-process random header.
- It rejects browser Origin requests and only accepts predefined provider routes.
- Provider destinations are fixed; redirects are never followed with credentials.
- Credentials remain in their original owners' stores. Only account references and metadata are in Agent Rotate's SQLite database, mode 0600 under a 0700 directory.
- Access logs are disabled. Routing history contains provider, local handle, event category, status, and timestamp only.
- No request/response payloads are persisted by the router. The native CLIs still maintain their normal session history.
- No account cleanup, logout, destructive migration, global alias install, or background cron replacement is performed automatically.

For suspected leaks, do not paste credentials into a public issue. Contact the repository owner privately with a redacted description. Tests must use synthetic values and local servers.
