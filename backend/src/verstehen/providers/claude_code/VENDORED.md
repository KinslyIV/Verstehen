# Vendored Claude Code model

Source: [h0rv/pydantic-ai-claude-code](https://github.com/h0rv/pydantic-ai-claude-code),
commit **8a78bdda831d723a7eff3ad0667385b401cbeb5d** (`8a78bdd`).
Fetched through GitHub's contents API at that revision. All files from
`src/pydantic_ai_claude_code/` are retained here, alongside the original [MIT LICENSE](LICENSE).
Copyright notices: 2026 Armin Ronacher and 2026 chem.

Local patches to upstream files:

1. `_transport.py`: the generated SDK system prompt is the plain Pydantic AI instruction
   string, including an empty string when there are no instructions. Removed the Claude Code
   preset and its append field (Q10). The upstream conflicting SDK/pydantic prompt check remains.
2. `_transport.py`: clear stream-start usage and replace the held final message-delta usage
   with `ResultMessage.usage`. Pydantic AI maps those final counts, including cache reads/writes,
   into `RequestUsage`; assistant/partial stream counts are never summed.
3. `model.py` / `_transport.py`: an optional event callback exposes raw SDK messages to
   the app-owned `VERSTEHEN_PROVIDER_EVENTS` logger, without configuring logging inside the vendor.
4. Python files: repository Ruff import ordering and formatting (double quotes, wrapping).
   Relative imports already work under `verstehen.providers.claude_code`; no import remapping.
5. `__init__.py`: no package re-exports, so importing `binary` or `adapter` does not load
   `claude_agent_sdk`; import from the submodules (`model`, `exceptions`, `diagnostics`).

App-owned files (not upstream): `adapter.py`, `binary.py`, and `context.py`.
The adapter always supplies the discovered absolute CLI path and every lockdown option itself:
`tools=[]`, `max_turns=1`, `setting_sources=[]`, `skills=[]`, `strict_mcp_config=True`,
`extra_args={"no-session-persistence": None}`. It also disables Claude memory files through
`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, uses an empty temporary working directory, and passes SDK
adaptive thinking plus the selected effort. The SDK retains authentication ownership.

`context.py` follows LearnHarness's local control protocol: initialize, then
`get_context_usage` with `detail="summary"`, never a prompt. A positive integer `maxTokens`
feeds the adapter runtime cache, keyed by binary path, version, and model alias. No catalog
context estimate is used. Unsupported/failed probes leave the limit unknown.

The original diagnostics and module entry point remain vendored; the app uses only the
app-owned adapter and routes. The comment checker already excludes this directory.
The Anthropic extra on the existing pinned `pydantic-ai-slim` dependency supplies the vendor's
Anthropic client and model mapping; it does not change the provider's authentication path.

Offline verification: `make check` (live tests excluded by default).
To opt in on the laptop with an installed, signed-in `claude`, from the repository root:

```sh
uv run --project backend pytest -c backend/pyproject.toml -m live -s backend/tests/providers/test_claude_code_live.py
```

This sends one short Haiku request using the user's subscription and prints the discovered
CLI version/path. It uses a temporary data directory and never opens the login file itself.
The pinned tested version is 2.1.327; changing it or its pinned checksum requires the user-run
live check. The implementation agent did not run this test or download the binary.
