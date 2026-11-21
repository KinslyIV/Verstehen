import { test, expect } from './fixtures';
import type { BrowserDownloadProgress, DemoBrowser, SearchKeysStatus } from '../src/lib/api/client';

test.use({ script: 'verify/scripts/health.json' });
for (const theme of ['dark', 'light']) {
	for (const state of ['idle', 'downloading', 'failed', 'found'] as const) {
		test(`settings-tools-${theme}-${state}`, async ({ page }) => {
			await page.addInitScript((value) => localStorage.setItem('mode-watcher-mode', value), theme);
			let browser: DemoBrowser = { path: null, source: null };
			let progress: BrowserDownloadProgress = { state: 'idle' };
			let keys: SearchKeysStatus = {
				tavily: { present: false, masked: null, source: 'none' },
				brave: { present: true, masked: '…abcd (24 chars)', source: 'env' },
				effective_engine: 'brave'
			};
			await page.route('**/api/search-keys**', async (route) => {
				if (route.request().method() === 'PUT')
					keys = {
						...keys,
						tavily: { present: true, masked: '…qrst (25 chars)', source: 'file' },
						effective_engine: 'tavily'
					};
				if (route.request().method() === 'DELETE')
					keys = {
						...keys,
						tavily: { present: false, masked: null, source: 'none' },
						effective_engine: 'brave'
					};
				await route.fulfill({ json: keys });
			});
			await page.route('**/api/demo-browser**', async (route) => {
				if (route.request().url().endsWith('/download')) {
					if (route.request().method() === 'POST')
						progress = {
							state: 'downloading',
							message: 'Downloading Chromium · 50% of 120 MiB',
							percent: 50
						};
					return route.fulfill({ json: progress });
				}
				return route.fulfill({ json: browser });
			});
			await page.goto('/settings');
			await page.getByRole('button', { name: 'Tools', exact: true }).click();
			for (const tool of ['research', 'demo', 'visual', 'pdf']) {
				const toggle = page.getByRole('switch', { name: `tool ${tool}`, exact: true });
				await expect(toggle).toBeChecked();
				await toggle.click();
				await expect(toggle).not.toBeChecked();
			}
			const concurrency = page.getByRole('spinbutton', { name: 'Concurrent worker requests' });
			await concurrency.fill('1.5');
			await concurrency.press('Enter');
			await expect(page.getByRole('alert')).toHaveText(
				'Enter a positive, safely representable whole number.'
			);
			await concurrency.fill('4');
			await concurrency.press('Enter');
			await expect
				.poll(
					async () =>
						(await (await page.request.get('/api/settings')).json()).worker_request_concurrency
				)
				.toBe(4);
			await expect(concurrency).toBeEnabled();
			await concurrency.fill('');
			await page.getByRole('heading', { name: 'Background tools' }).click();
			await expect
				.poll(
					async () =>
						(await (await page.request.get('/api/settings')).json()).worker_request_concurrency
				)
				.toBeNull();
			const engine = page.getByRole('combobox', { name: 'Search engine' });
			await expect(engine.locator('option[value="tavily"]')).toBeDisabled();
			await page.getByLabel('Tavily', { exact: true }).fill('tvly-abcdefghijklmnopqrst');
			await page.getByRole('button', { name: 'Set Tavily key' }).click();
			await expect(page.getByText('…qrst (25 chars)')).toBeVisible();
			await engine.selectOption('tavily');
			await expect(engine).toBeEnabled();
			await page.getByRole('button', { name: 'Clear Tavily key' }).click();
			await expect(page.getByText('Key missing, using Brave Search.')).toBeVisible();
			await expect(page.getByLabel('Brave Search', { exact: true })).toBeDisabled();
			const path = page.getByRole('textbox', { name: 'Browser path' });
			await path.fill('/opt/demo/chromium');
			await path.press('Enter');
			await expect
				.poll(async () => (await (await page.request.get('/api/settings')).json()).demo_browser)
				.toBe('/opt/demo/chromium');
			await expect(path).toBeEnabled();
			const button = page.getByRole('button', { name: 'Download Chromium for demos' });
			await button.click();
			await expect(page.getByRole('progressbar', { name: 'Chromium download' })).toHaveAttribute(
				'value',
				'50'
			);
			progress = { state: 'failed', error: 'Offline download failed. Try again.' };
			await expect(page.getByText('Offline download failed. Try again.')).toBeVisible();
			await button.click();
			progress = { state: 'complete', percent: 100 };
			browser = { path: '/opt/demo/chromium', source: 'setting' };
			await expect(page.getByText('/opt/demo/chromium · setting')).toBeVisible();
			await expect(button).toHaveCount(0);
			if (state !== 'found') {
				browser = { path: null, source: null };
				progress =
					state === 'downloading'
						? { state, percent: 50, message: 'Downloading Chromium · 50% of 120 MiB' }
						: state === 'failed'
							? { state, error: 'Offline download failed. Try again.' }
							: { state };
				await page.getByRole('button', { name: 'Appearance', exact: true }).click();
				await page.getByRole('button', { name: 'Tools', exact: true }).click();
				await expect(button).toBeVisible();
			}
			if (state === 'idle') {
				await concurrency.fill('1.5');
				await concurrency.press('Enter');
				await expect(page.getByRole('alert')).toHaveText(
					'Enter a positive, safely representable whole number.'
				);
			}
		});
	}
}
