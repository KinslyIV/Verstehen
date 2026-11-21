import { test, expect } from './fixtures';
import type { Account, BinaryStatus } from '../src/lib/api/client';
test.use({ script: 'verify/scripts/health.json' });
for (const theme of ['dark', 'light']) {
	for (const state of ['not_installed', 'too_old', 'untested', 'tested'] as const) {
		test(`settings-accounts-${theme}-${state}`, async ({ page, context }) => {
			await page.addInitScript((theme) => localStorage.setItem('mode-watcher-mode', theme), theme);
			let accounts: Account[] = [
				{ id: 'one', kind: 'chatgpt', label: 'learner@example.com', state: 'ready' },
				{
					id: 'two',
					kind: 'chatgpt',
					label: 'second@example.com',
					state: 'needs_sign_in',
					reason: 'Sign in again to use this account.'
				}
			];
			const reasons = {
				not_installed: 'Install Claude Code, then run claude to sign in.',
				too_old: 'Update Claude Code with claude update.',
				untested: "Claude Code 2.1.300 hasn't been tested with Verstehen.",
				tested: null
			};
			const claude: BinaryStatus = {
				state,
				version:
					state === 'not_installed'
						? null
						: state === 'tested'
							? '2.1.327'
							: state === 'too_old'
								? '2.1.100'
								: '2.1.300',
				minimum_version: '2.1.259',
				tested_version: '2.1.327',
				reason: reasons[state]
			};
			let pendingAccount = 'one';
			await page.route('**/api/accounts/**', async (route) => {
				const url = new URL(route.request().url());
				const path = url.pathname;
				const method = route.request().method();
				if (path === '/api/accounts/claude-code') return route.fulfill({ json: claude });
				if (path === '/api/accounts/chatgpt' && method === 'GET')
					return route.fulfill({ json: accounts });
				if (path.includes('/sign-in/')) {
					accounts = accounts.map((account) =>
						account.id === pendingAccount ? { ...account, state: 'ready', reason: null } : account
					);
					return route.fulfill({
						json: { id: 'attempt', state: 'connected', account: accounts[0] }
					});
				}
				if (method === 'DELETE') {
					accounts = accounts.filter((account) => !path.endsWith(`/${account.id}`));
					return route.fulfill({ status: 204 });
				}
				if (method === 'POST') {
					pendingAccount = path.endsWith('/two/sign-in') ? 'two' : 'one';
					return route.fulfill({
						json: { id: 'attempt', url: 'https://auth.openai.com/verify-only' }
					});
				}
				throw new Error(`Unmocked account route: ${method} ${path}`);
			});
			await context.route('https://code.claude.com/**', (route) =>
				route.fulfill({ contentType: 'text/html', body: '<p>Offline install fixture</p>' })
			);
			await context.route('https://auth.openai.com/**', (route) =>
				route.fulfill({ contentType: 'text/html', body: '<p>Offline sign-in fixture</p>' })
			);
			await page.goto('/settings');
			await page.getByRole('button', { name: 'Accounts', exact: true }).click();
			const chatgpt = page.getByRole('region', { name: 'ChatGPT accounts' });
			const cli = page.getByRole('region', { name: 'Claude Code account' });
			await expect(chatgpt.getByText('Connected', { exact: true })).toBeVisible();
			await expect(chatgpt.getByText('Needs sign-in', { exact: true })).toBeVisible();
			await expect(
				cli.getByText(
					{
						not_installed: 'Not installed',
						too_old: 'Too old',
						untested: 'Untested',
						tested: 'Tested'
					}[state],
					{ exact: true }
				)
			).toBeVisible();
			for (const region of [chatgpt, cli]) {
				const toggle = region.getByRole('switch', { name: 'Allow background use' });
				await expect(toggle).toBeChecked();
				await toggle.click();
				await expect(toggle).not.toBeChecked();
			}
			await expect
				.poll(async () => (await (await page.request.get('/api/settings')).json()).background)
				.toEqual({
					chatgpt: false,
					claude_code: false
				});
			if (state === 'tested') {
				const row = chatgpt.locator('div.rounded-lg').filter({ hasText: 'second@example.com' });
				const popupPromise = page.waitForEvent('popup');
				await row.getByRole('button', { name: 'Sign in again' }).click();
				const popup = await popupPromise;
				await popup.close();
				await expect(row.getByText('Connected', { exact: true })).toBeVisible();
				await row.getByRole('button', { name: 'Remove', exact: true }).click();
				await expect(chatgpt.getByText('second@example.com')).toHaveCount(0);
				const addPopupPromise = page.waitForEvent('popup');
				await chatgpt.getByRole('button', { name: 'Add account' }).click();
				await (await addPopupPromise).close();
				await expect(chatgpt.getByRole('button', { name: 'Add account' })).toBeEnabled();
			}
			const install = cli.getByRole('button', { name: 'Install Claude Code' });
			if (state === 'not_installed' || state === 'too_old') {
				await expect(install).toBeVisible();
				const popupPromise = page.waitForEvent('popup');
				await install.click();
				const popup = await popupPromise;
				expect(popup.url()).toBe('https://code.claude.com/docs/en/setup');
				await popup.close();
			} else {
				await expect(install).toHaveCount(0);
			}
		});
	}
}
