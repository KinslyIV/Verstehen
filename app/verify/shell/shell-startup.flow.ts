import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json' });

declare global {
	interface Window {
		__settleSidecar: { ready: (port: number) => void; fail: (reason: string) => void };
		__startupMarks: string[];
	}
}

test('shell-startup', async ({ page, baseURL }) => {
	const port = Number(new URL(baseURL!).port);
	await page.addInitScript(() => {
		const tauri = window as unknown as Record<string, unknown>;
		tauri.isTauri = true;
		window.__startupMarks = [];
		const connection = new Promise((resolve, reject) => {
			window.__settleSidecar = {
				ready: (port) => resolve({ port, token: 'desktop-token' }),
				fail: (reason) => reject(reason)
			};
		});
		tauri.__TAURI_INTERNALS__ = {
			invoke: async (command: string, args?: { name: string }) => {
				if (command === 'sidecar_connection') return connection;
				if (command === 'startup_mark') return void window.__startupMarks.push(args!.name);
				throw new Error(`Unexpected command ${command}`);
			}
		};
	});
	const marks = () => page.evaluate(() => window.__startupMarks);

	let releaseCatalog!: () => void;
	const catalogHeld = new Promise<void>((resolve) => (releaseCatalog = resolve));
	await page.route('**/api/models', async (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		await catalogHeld;
		await route.fallback();
	});
	await page.goto('/');
	await expect(page.getByRole('status')).toHaveText('Starting Verstehen…');
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	await expect(page.getByPlaceholder('What do you want to learn?')).toBeVisible();
	expect(await marks()).toEqual(['ui_mounted']);
	await page.screenshot({
		path: test.info().outputPath('startup-pending.png'),
		animations: 'disabled'
	});

	await page.evaluate((port) => window.__settleSidecar.ready(port), port);
	await expect(page.getByRole('status')).toHaveCount(0);
	await expect(page.getByText('No sessions yet')).toBeVisible();
	expect(await marks()).toEqual(['ui_mounted']);
	releaseCatalog();
	await expect(page.getByRole('button', { name: 'Choose model', exact: true })).toContainText(
		'Scripted teacher'
	);
	await expect.poll(marks).toEqual(['ui_mounted', 'models_displayed', 'composer_usable']);
	await page.screenshot({
		path: test.info().outputPath('startup-ready.png'),
		animations: 'disabled'
	});

	await page.reload();
	await expect(page.getByRole('status')).toHaveText('Starting Verstehen…');
	await page.evaluate(() =>
		window.__settleSidecar.fail(
			"The sidecar didn't start: it took longer than 30 seconds. See /home/learner/.local/share/verstehen/logs/verstehen.log"
		)
	);
	const failure = page.getByRole('alert').filter({ hasText: /Verstehen couldn.t start/ });
	await expect(failure).toContainText('verstehen.log');
	await page.screenshot({
		path: test.info().outputPath('startup-failed.png'),
		animations: 'disabled'
	});
});
