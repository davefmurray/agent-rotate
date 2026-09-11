# Setup with a coding agent

1. Confirm macOS/Linux, Python 3.11+, uv, and real Claude/Codex binaries on PATH. Read AGENTS.md and README limitations.
2. Install from this GitHub repository with uv. Don't replace native executable files or aliases.
3. Run `agent-rotate import-claude` for existing Claude Rotate accounts. This registers references, not copied secrets.
4. Run `agent-rotate add-codex personal --home ~/.codex` if a ChatGPT auth.json exists; otherwise use `agent-rotate login codex personal`.
5. For additional Codex accounts, run `agent-rotate login codex NAME` one at a time. **Pause for the human's browser sign-in.** Do not handle passwords, fabricate OAuth tokens, or paste callback data into chat.
6. Run `agent-rotate doctor` and `agent-rotate status`. Report missing logins, unknown usage, and one-account pools honestly.
7. Demonstrate `agent-rotate run claude` and `agent-rotate run codex`. For an existing session, pass the native resume option and exact session ID.
8. Run tests with fake upstreams before claiming failover works. Distinguish passing transport tests from a naturally occurring live quota switch.
9. The plugin skill can report status and teach launching. It does not activate routing in a host session that was already running.
10. Record installation version, machine, source paths, and limitations in the user's durable operations notes. Never record secrets.

Stop and explain actual errors. Diagnose against evidence; do not retry OAuth refresh blindly, change models, or switch to API billing to make a smoke test pass.
