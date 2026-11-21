import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import SettingsAccounts from './settings-accounts.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn(),
	saveSettings: vi.fn(),
	listChatGPTAccounts: vi.fn(),
	getClaudeCode: vi.fn(),
	openExternal: vi.fn()
}));

const claudeStates = [
	{
		state: 'not_installed',
		label: 'Not installed',
		version: null,
		reason: 'Install Claude Code, then run claude to sign in.',
		login: false,
		install: true
	},
	{
		state: 'too_old',
		label: 'Too old',
		version: '2.1.100',
		reason: 'Update Claude Code with claude update.',
		login: false,
		install: true
	},
	{
		state: 'untested',
		label: 'Untested',
		version: '2.1.300',
		reason: "Claude Code 2.1.300 hasn't been tested with Verstehen.",
		login: true,
		install: false
	},
	{
		state: 'tested',
		label: 'Tested',
		version: '2.1.327',
		reason: null,
		login: true,
		install: false
	}
] as const;

beforeEach(() => {
	vi.clearAllMocks();
	vi.mocked(api.getSettings).mockResolvedValue({});
	vi.mocked(api.listChatGPTAccounts).mockResolvedValue([
		{ id: 'one', kind: 'chatgpt', label: 'learner@example.com', state: 'ready' },
		{
			id: 'two',
			kind: 'chatgpt',
			label: 'second@example.com',
			state: 'needs_sign_in',
			reason: 'Sign in again to use this account.'
		}
	]);
});

test.each(claudeStates)(
	'claude_code_$state_shows_its_status_login_note_and_install_button',
	async (expected) => {
		vi.mocked(api.getClaudeCode).mockResolvedValue({
			state: expected.state,
			version: expected.version,
			minimum_version: '2.1.259',
			tested_version: '2.1.327',
			reason: expected.reason
		});
		const screen = await render(SettingsAccounts);
		const chatgpt = screen.getByRole('region', { name: 'ChatGPT accounts' });
		const cli = screen.getByRole('region', { name: 'Claude Code account' });
		await expect.element(chatgpt.getByText('Connected', { exact: true })).toBeVisible();
		await expect.element(chatgpt.getByText('Needs sign-in', { exact: true })).toBeVisible();
		await expect.element(cli.getByText(expected.label, { exact: true })).toBeVisible();
		await expect
			.element(
				cli.getByText(expected.version ? `Version ${expected.version}` : 'No version detected')
			)
			.toBeVisible();
		if (expected.reason) await expect.element(cli.getByText(expected.reason)).toBeVisible();
		const login = cli.getByText('Uses your Claude Code login. Run claude to sign in.');
		const install = cli.getByRole('button', { name: 'Install Claude Code' });
		if (expected.login) await expect.element(login).toBeVisible();
		else await expect.element(login).not.toBeInTheDocument();
		if (!expected.install) return expect.element(install).not.toBeInTheDocument();
		await install.click();
		expect(api.openExternal).toHaveBeenCalledWith('https://code.claude.com/docs/en/setup');
	}
);
