# MCP Servers for Verstehen

MCP Servers ships with the Verstehen desktop app. Open **Settings → Plugins**, enable **MCP Servers**,
then open its **Settings**. The app uses the bundled code and loads settings from an earlier manual
installation using the same plugin ID.

## Connect Zotero

Enter **Zotero** as the name, the full path to your installed `zotero-mcp` as the command, leave
**Arguments** blank, and enter `{"ZOTERO_LOCAL": "true"}` in **Environment variables**. Keep Zotero
running with local application access enabled. Select **Test connection** to list its tools.

Use the **Agent** menu to choose tools for each agent. **Select all** and **Clear all** apply to
the selected agent and include tools hidden by the filter. Select **Save** to apply the changes. An empty selection
gives that agent no tools from this server. Retest to discover newly added tools and select them.
If you edit the command, arguments, or environment, retest and select tools for that configuration.
Running turns keep their original selection. The next turn uses the saved choices.

Other servers use the same setup. Enter the executable and, if needed, a JSON array of arguments
and a JSON object of environment variables. The executable runs on the desktop host with your
user permissions. The plugin saves these values as plain text in its local `mcp-servers/data/servers.json`.
