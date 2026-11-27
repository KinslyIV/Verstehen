# MCP Servers for Verstehen

1. In the Verstehen desktop app, open **Settings → Plugins** and find the plugin directory.
2. Copy this `mcp-servers` folder into that directory, or extract the plugin ZIP there. The manifest goes at
   `<plugin directory>/mcp-servers/dist/manifest.json`.
3. Select **Refresh**, enable **MCP Servers**, then open its **Settings**.

## Connect Zotero

Enter **Zotero** as the name, the full path to your installed `zotero-mcp` as the command, leave
**Arguments** blank, and enter `{"ZOTERO_LOCAL": "true"}` in **Environment variables**. Keep Zotero
running with local application access enabled. Select **Test connection** to list its tools.

Use the **Agent** menu to choose tools for each agent, then select **Save**. An empty selection
gives that agent no tools from this server. Retest to discover newly added tools and select them.
If you edit the command, arguments, or environment, retest and select tools for that configuration.
Running turns keep their original selection. The next turn uses the saved choices.

Other servers use the same setup. Enter the executable and, if needed, a JSON array of arguments
and a JSON object of environment variables. The executable runs on the desktop host with your
user permissions. The plugin saves these values as plain text in its local `mcp-servers/data/servers.json`.
