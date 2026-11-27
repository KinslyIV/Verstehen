import { fileURLToPath } from 'node:url';
import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json', pluginsEnabled: true });

test('mcp-servers-settings', async ({ page }) => {
	await page.goto('/settings?section=plugins');
	const plugin = page.getByTestId('plugin-mcp-servers');
	await expect(plugin).toContainText('Built in');
	await expect(page.getByTestId('plugin-status-mcp-servers')).toHaveText('disabled');
	await page.screenshot({
		path: test.info().outputPath('core-mcp-servers.png'),
		animations: 'disabled'
	});
	await plugin.getByRole('switch', { name: 'Enable MCP Servers' }).click();
	await expect(page.getByTestId('plugin-status-mcp-servers')).toHaveText('active');
	await plugin.getByTestId('plugin-open-settings-mcp-servers').click();

	const body = page.getByTestId('plugin-settings-body');
	await body.getByRole('textbox', { name: 'Name', exact: true }).fill('Local fixture');
	const command = body.getByRole('textbox', { name: 'Command', exact: true });
	await command.fill('/missing/mcp-server');
	const testConnection = body.getByRole('button', { name: 'Test connection' });
	await testConnection.click();
	const connectionStatus = body.locator('[data-connection-status]');
	await expect(connectionStatus).toContainText('Executable not found');

	await command.fill(fileURLToPath(new URL('../../../backend/.venv/bin/python', import.meta.url)));
	await body
		.getByRole('textbox', { name: /Arguments/ })
		.fill(
			JSON.stringify([
				fileURLToPath(new URL('../../../backend/tests/fixtures/mcp_servers.py', import.meta.url))
			])
		);
	await testConnection.click();
	await expect(connectionStatus).toHaveText('Found 2 tools.');

	const echo = body.getByRole('checkbox', { name: 'echo' });
	const shout = body.getByRole('checkbox', { name: 'shout' });
	const agent = body.getByRole('combobox', { name: 'Agent' });
	await expect(agent).toHaveValue('chat');
	await expect(echo).not.toBeChecked();
	await expect(shout).not.toBeChecked();
	await shout.check();
	await agent.selectOption('teacher');
	await expect(shout).not.toBeChecked();
	await echo.check();
	await body.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(body.locator('[data-status]')).toHaveText('Saved. Changes apply on the next turn.');

	await page.reload();
	await expect(body.getByRole('combobox', { name: 'Server' })).toHaveValue(/^local_fixture_/);
	await expect(shout).toBeChecked();
	await expect(echo).not.toBeChecked();
	await agent.selectOption('teacher');
	await expect(echo).toBeChecked();
	await expect(shout).not.toBeChecked();
	await body.getByRole('button', { name: 'Save', exact: true }).scrollIntoViewIfNeeded();
	await page.screenshot({
		path: test.info().outputPath('mcp-agent-tools.png'),
		animations: 'disabled'
	});

	await body.getByRole('button', { name: 'Remove server' }).click();
	await body.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(body.locator('[data-status]')).toContainText('Server removed.');
	await expect(body.getByRole('combobox', { name: 'Server' })).toHaveValue('');
});
