# MCP Servers desktop plugin

The plugin adds a settings page for local MCP commands. Test connection lists the server's tools.
Each of Prober, Teacher, Practice, and Chat has its own tool selection. Saving applies on the next
turn. Side Chat and server mode have no plugin tool hook.

- Ship the core plugin from `backend/src/verstehen/core_plugins/mcp-servers/dist/` with the
  desktop app and list it as **Built in**, disabled by default. The core ID takes precedence over
  an old manual installation. Reuse its saved enable state and data directory without a migration.
- The frontend edits commands and selections. The backend discovers tools and persists settings
  in the existing plugin data directory.
- Use the existing plugin agent hook and Pydantic AI MCP toolsets. Snapshot settings for each
  run. Close the subprocesses after use and continue with the remaining tools if a server is
  unavailable. New tools are unselected until chosen.
- LearnHarness's core plugins also ship with the app and start disabled. Its agent plugin
  contributions are defined in code. This plugin configures the existing MCP toolset hook.
- Verify with a local fixture server, a fake-model backend test, and the `mcp-servers-settings`
  flow. Confirm Zotero tool discovery with the installed executable and no library tool calls.
- Run the frozen app's self-check to prove bundled plugin discovery and activation. Verify a fresh
  profile and an upgrade with a temporary profile containing the old manual plugin.
