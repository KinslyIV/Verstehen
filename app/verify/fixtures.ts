import { test as base, expect } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm } from 'node:fs/promises';
import { get } from 'node:http';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const appDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');

async function freePort(): Promise<number> {
	const server = createServer();
	server.listen(0, '127.0.0.1');
	await once(server, 'listening');
	const address = server.address();
	if (!address || typeof address === 'string') throw new Error('No free preview port');
	await new Promise<void>((resolve, reject) =>
		server.close((error) => (error ? reject(error) : resolve()))
	);
	return address.port;
}

async function start(
	command: string,
	args: string[],
	env: NodeJS.ProcessEnv
): Promise<ChildProcess> {
	const child = spawn(command, args, { cwd: appDirectory, env, stdio: ['ignore', 'pipe', 'pipe'] });
	child.stderr?.on('data', (data) => process.stderr.write(data));
	await once(child, 'spawn');
	return child;
}

async function stop(child: ChildProcess): Promise<void> {
	if (child.exitCode !== null || child.signalCode !== null) return;
	const exited = once(child, 'exit');
	child.kill('SIGTERM');
	const timer = setTimeout(() => child.kill('SIGKILL'), 5000);
	try {
		await exited;
	} finally {
		clearTimeout(timer);
	}
}

async function handshake(child: ChildProcess): Promise<number> {
	if (!child.stdout) throw new Error('Sidecar stdout is missing');
	const lines = createInterface({ input: child.stdout });
	const timer = setTimeout(() => lines.close(), 15000);
	try {
		for await (const line of lines) {
			const { port } = JSON.parse(line);
			if (!Number.isInteger(port) || port < 1 || port > 65535)
				throw new Error(`Invalid sidecar handshake: ${line}`);
			return port;
		}
		throw new Error('Sidecar did not print its port handshake within 15 seconds');
	} finally {
		clearTimeout(timer);
		lines.close();
	}
}

async function ready(url: string, child: ChildProcess): Promise<void> {
	const deadline = Date.now() + 15000;
	while (Date.now() < deadline) {
		if (child.exitCode !== null) throw new Error(`Vite preview exited with ${child.exitCode}`);
		const ok = await new Promise<boolean>((resolve) => {
			const request = get(url, (response) => {
				response.resume();
				resolve(response.statusCode === 200);
			});
			request.on('error', () => resolve(false));
			request.setTimeout(1000, () => request.destroy());
		});
		if (ok) return;
		await new Promise((resolve) => setTimeout(resolve, 100));
	}
	throw new Error(`Vite preview was not ready at ${url}`);
}

export const test = base.extend<{
	script: string;
	expectedStatuses: number[];
	browserErrors: void;
}>({
	script: ['', { option: true }],
	expectedStatuses: [[], { option: true }],
	baseURL: async ({ script, playwright }, use) => {
		if (!script) throw new Error('Declare a fake-model script with test.use({ script: ... })');
		const directory = await mkdtemp(resolve(tmpdir(), 'verstehen-verify-'));
		const env = Object.fromEntries(
			Object.entries(process.env).filter(([key]) => !key.startsWith('VERSTEHEN_'))
		);
		Object.assign(env, {
			VERSTEHEN_DATA_DIR: directory,
			VERSTEHEN_PORT: '0',
			...(script === 'none' ? {} : { VERSTEHEN_FAKE_MODEL_SCRIPT: resolve(appDirectory, script) })
		});
		const children: ChildProcess[] = [];
		try {
			const sidecar = await start(resolve(appDirectory, '../backend/.venv/bin/verstehen'), [], env);
			children.push(sidecar);
			const port = await handshake(sidecar);
			const previewPort = await freePort();
			const preview = await start(
				process.execPath,
				[
					'node_modules/vite/bin/vite.js',
					'preview',
					'--host',
					'127.0.0.1',
					'--port',
					String(previewPort),
					'--strictPort'
				],
				{ ...env, VERSTEHEN_PORT: String(port) }
			);
			children.push(preview);
			const url = `http://127.0.0.1:${previewPort}`;
			await ready(url, preview);
			if (script !== 'none') {
				const api = await playwright.request.newContext({ baseURL: url });
				try {
					const response = await api.put('/api/settings', {
						data: {
							models: {
								strong: { account: 'fake', model: 'fake' },
								cheap: { account: 'fake', model: 'fake-title' },
								vision: { account: 'fake', model: 'fake' }
							}
						}
					});
					expect(response.ok()).toBe(true);
				} finally {
					await api.dispose();
				}
			}
			await use(url);
		} finally {
			try {
				await Promise.all(children.map(stop));
			} finally {
				await rm(directory, { recursive: true, force: true });
			}
		}
	},
	browserErrors: [
		async ({ page, expectedStatuses }, use, testInfo) => {
			const errors: string[] = [];
			page.on('console', (message) => {
				if (
					message.type() === 'error' &&
					!expectedStatuses.some((status) =>
						message
							.text()
							.startsWith(
								`Failed to load resource: the server responded with a status of ${status} (`
							)
					)
				)
					errors.push(`Console error: ${message.text()}`);
			});
			page.on('pageerror', (error) => errors.push(`Uncaught page error: ${error.message}`));
			page.on(
				'requestfailed',
				(request) =>
					!(
						request.failure()?.errorText.includes('ERR_ABORTED') &&
						request.method() === 'GET' &&
						/\/api\/(events|sessions(?:\/[^/]+(?:\/stream)?)?)$/.test(request.url())
					) &&
					errors.push(
						`Failed request: ${request.method()} ${request.url()}: ${request.failure()?.errorText}`
					)
			);
			try {
				await use();
			} finally {
				if (!page.isClosed()) {
					const path = testInfo.outputPath('screenshot.png');
					await page.screenshot({ path, fullPage: true, animations: 'disabled' });
					await testInfo.attach('final-page', { path, contentType: 'image/png' });
				}
				expect(errors, 'Browser errors must be fixed').toEqual([]);
			}
		},
		{ auto: true }
	]
});

export { expect };
