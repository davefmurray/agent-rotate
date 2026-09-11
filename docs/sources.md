# Sources and compatibility research

Reviewed 2026-09-11. Local binaries: Claude Code 2.1.265 and Codex CLI 0.154.0.

- [Official OpenAI app-server documentation](https://learn.chatgpt.com/docs/app-server): account/read, account/rateLimits/read, managed OAuth, initialization, and structured errors.
- [Official OpenAI authentication documentation](https://learn.chatgpt.com/docs/auth#credential-storage): CODEX_HOME/auth.json and file/keyring credential storage.
- [Official OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): model_providers base_url, requires_openai_auth, supports_websockets, env_http_headers. Provider overrides belong in user/CLI configuration, not project config.
- [Official Claude gateway documentation](https://code.claude.com/docs/en/llm-gateway-connect): ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, and ANTHROPIC_CUSTOM_HEADERS.
- [Codex provider implementation](https://github.com/openai/codex/blob/main/codex-rs/model-provider-info/src/lib.rs): the ChatGPT inference base is https://chatgpt.com/backend-api/codex; explicit base_url overrides it.
- [Codex client implementation](https://github.com/openai/codex/blob/main/codex-rs/core/src/client.rs): provider supports_websockets controls the transport; WebSocket incremental state uses previous_response_id.
- [Codex protocol models](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs): tool history includes `function_call_output` and `custom_tool_call_output`; outputs can contain plain text or structured content items.
- [Claude Rotate](https://github.com/evrenverse/claude-rotate), MIT, pinned commit d650deb5ac645cd9f01f400d58c44394e8dba996: OAuth login, authoritative account store, locked refresh and credential sync.

The implementation doesn't assume a skill can intercept a host model's 429. HTTP rejection routing and native session resumption are different mechanisms. Synthetic tests establish transport behavior; live quota transitions require separately recorded evidence.
