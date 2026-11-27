# MCP Servers desktop plugin

The plugin adds a settings page for local MCP commands. Test connection lists the server's tools.
Each of Prober, Teacher, Practice, and Chat has its own tool selection. Saving applies on the next
turn. Side Chat and server mode have no plugin tool hook.

- Put the installable plugin in `plugins/mcp-servers/dist/`. The frontend edits the command,
  arguments, environment, and per-agent selections. The backend discovers tools and stores the
  configuration in the plugin data directory. No database migration is needed.
- Use the existing plugin agent hook and Pydantic AI MCP toolsets. Snapshot settings for each
  run. Close the subprocesses after use and continue with the remaining tools if a server is
  unavailable. New tools are unselected until chosen.
- LearnHarness plugins target agents from code. Verstehen already adds MCP toolsets to its host
  API. This plugin makes the tool selection configurable without changing the host API.
- Verify with a local fixture server, a fake-model backend test, and the `mcp-servers-settings`
  flow. Confirm Zotero tool discovery with the installed executable and no library tool calls.
