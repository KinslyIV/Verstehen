import { test as base, expect } from '@playwright/test';
import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { get } from 'node:http';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { promisify } from 'node:util';
import type { Entry } from '../src/lib/api/client';
import { fileURLToPath } from 'node:url';

const runFile = promisify(execFile);
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

const appendEntries = `
import asyncio
import json
import sys
from pathlib import Path
from verstehen.store.database import open_database
from verstehen.store.entries import ENTRY, EntriesStore

async def main():
    async with open_database(Path(sys.argv[1]) / "verstehen.db") as database:
        entries = [ENTRY.validate_python(entry) for entry in json.loads(Path(sys.argv[3]).read_text())]
        await EntriesStore(database).append(sys.argv[2], entries)

asyncio.run(main())
`;

const seedGraphSource = `
import asyncio
import json
import sys
from pathlib import Path
from verstehen.store.database import open_database
from verstehen.store.graph import GraphChain, GraphNode, GraphStore, NotesSource, ProvenancePoint, timestamp

async def main():
    spec = json.loads(Path(sys.argv[2]).read_text())
    async with open_database(Path(sys.argv[1]) / "verstehen.db") as database:
        async with GraphStore(database).transaction() as ledger:
            for node in spec["nodes"]:
                ledger.nodes.append(GraphNode(id=node["id"], name=node["name"], statement=node["statement"], provenance=[ProvenancePoint(session_id=session) for session in [node["session"], *node.get("also", [])]]))
            for chain in spec["chains"]:
                ledger.chains.append(GraphChain(id=chain["id"], premises=chain["premises"], conclusion=chain["conclusion"], provenance=[ProvenancePoint(session_id=chain["session"])]))
            for source in spec.get("sources", []):
                ledger.sources.append(NotesSource(id=source["id"], file_path=source["file_path"], imported_at=timestamp()))

asyncio.run(main())
`;

export const learnHarnessFixture = resolve(
	appDirectory,
	'../backend/tests/fixtures/learnharness/basic'
);

async function importLearnHarness(folder: string, dataDirectory: string): Promise<void> {
	const child = spawn(
		resolve(appDirectory, '../backend/.venv/bin/verstehen'),
		['import-learnharness', folder],
		{
			env: {
				...Object.fromEntries(
					Object.entries(process.env).filter(([key]) => !key.startsWith('VERSTEHEN_'))
				),
				VERSTEHEN_DATA_DIR: dataDirectory
			},
			stdio: ['pipe', 'pipe', 'pipe']
		}
	);
	let output = '';
	child.stdout.on('data', (data) => (output += data));
	child.stderr.on('data', (data) => (output += data));
	child.stdin.end('replace\n');
	const [code] = await once(child, 'exit');
	if (code !== 0) throw new Error(`import-learnharness failed (${code}):\n${output}`);
}

async function mintAdminToken(dataDirectory: string): Promise<string> {
	const { stdout } = await runFile(
		resolve(appDirectory, '../backend/.venv/bin/verstehen'),
		['mint-token', 'verify-admin'],
		{ env: { ...process.env, VERSTEHEN_DATA_DIR: dataDirectory } }
	);
	return JSON.parse(stdout).token;
}

export interface GraphSeed {
	nodes: { id: string; name: string; statement: string; session: string; also?: string[] }[];
	chains: { id: string; premises: string[]; conclusion: string; session: string }[];
	sources?: { id: string; file_path: string }[];
}

export const test = base.extend<{
	script: string;
	learnHarnessFolder: string;
	dataDirectory: string;
	appendEntries: (sessionId: string, entries: Entry[]) => Promise<void>;
	seedGraph: (seed: GraphSeed) => Promise<void>;
	expectedStatuses: number[];
	/** The flow goes offline on purpose, so refused requests are not browser errors. */
	goesOffline: boolean;
	client: 'sidecar' | 'remote';
	serverAdmin: { token: string };
	sidecarControl: { restart: () => Promise<void> };
	restartSidecar: () => Promise<void>;
	browserErrors: void;
}>({
	script: ['', { option: true }],
	learnHarnessFolder: ['', { option: true }],
	expectedStatuses: [[], { option: true }],
	goesOffline: [false, { option: true }],
	client: ['sidecar', { option: true }],
	serverAdmin: async ({ client, dataDirectory }, use) => {
		await use({ token: client === 'remote' ? await mintAdminToken(dataDirectory) : '' });
	},
	sidecarControl: async ({ dataDirectory }, use) => {
		await use({
			restart: async () => {
				throw new Error(`Sidecar is not started for ${dataDirectory}`);
			}
		});
	},
	restartSidecar: async ({ baseURL, sidecarControl }, use) => {
		if (!baseURL) throw new Error('Preview is not started');
		await use(() => sidecarControl.restart());
	},
	dataDirectory: async ({ script, learnHarnessFolder }, use) => {
		if (!script) throw new Error('Declare a fake-model script with test.use({ script: ... })');
		const directory = await mkdtemp(resolve(tmpdir(), 'verstehen-verify-'));
		try {
			if (learnHarnessFolder) await importLearnHarness(learnHarnessFolder, directory);
			await use(directory);
		} finally {
			await rm(directory, { recursive: true, force: true });
		}
	},
	appendEntries: async ({ dataDirectory }, use) => {
		await use(async (sessionId, entries) => {
			const file = resolve(dataDirectory, 'append-entries.json');
			await writeFile(file, JSON.stringify(entries));
			await runFile(
				resolve(appDirectory, '../backend/.venv/bin/python'),
				['-c', appendEntries, dataDirectory, sessionId, file],
				{ env: { ...process.env, VERSTEHEN_DATA_DIR: dataDirectory } }
			);
		});
	},
	seedGraph: async ({ dataDirectory }, use) => {
		await use(async (seed) => {
			const file = resolve(dataDirectory, 'seed-graph.json');
			await writeFile(file, JSON.stringify(seed));
			await runFile(
				resolve(appDirectory, '../backend/.venv/bin/python'),
				['-c', seedGraphSource, dataDirectory, file],
				{ env: { ...process.env, VERSTEHEN_DATA_DIR: dataDirectory } }
			);
		});
	},
	baseURL: async (
		{ script, client, playwright, dataDirectory, sidecarControl, serverAdmin },
		use
	) => {
		const env = Object.fromEntries(
			Object.entries(process.env).filter(([key]) => !key.startsWith('VERSTEHEN_'))
		);
		Object.assign(env, {
			VERSTEHEN_DATA_DIR: dataDirectory,
			VERSTEHEN_PORT: '0',
			...(script === 'none' ? {} : { VERSTEHEN_FAKE_MODEL_SCRIPT: resolve(appDirectory, script) })
		});
		const remote = client === 'remote';
		const sidecarArguments = remote ? ['--server', '--port', '0'] : [];
		const children: ChildProcess[] = [];
		try {
			let sidecar = await start(
				resolve(appDirectory, '../backend/.venv/bin/verstehen'),
				sidecarArguments,
				env
			);
			children.push(sidecar);
			const port = await handshake(sidecar);
			const previewPort = await freePort();
			const startPreview = (sidecarPort: number) =>
				start(
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
					{
						...env,
						VERSTEHEN_PORT: String(sidecarPort),
						...(remote
							? { PUBLIC_VERSTEHEN_CLIENT: 'remote', PUBLIC_VERSTEHEN_EXTRA_HOSTS: '127.0.0.1' }
							: {})
					}
				);
			let preview = await startPreview(port);
			children.push(preview);
			const url = `http://127.0.0.1:${previewPort}`;
			await ready(url, preview);
			sidecarControl.restart = async () => {
				await stop(preview);
				await stop(sidecar);
				sidecar = await start(
					resolve(appDirectory, '../backend/.venv/bin/verstehen'),
					sidecarArguments,
					env
				);
				children.push(sidecar);
				preview = await startPreview(await handshake(sidecar));
				children.push(preview);
				await ready(url, preview);
			};
			if (script !== 'none') {
				const api = await playwright.request.newContext({ baseURL: url });
				try {
					const response = await api.put('/api/settings', {
						headers: remote ? { authorization: `Bearer ${serverAdmin.token}` } : {},
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
			await Promise.all(children.map(stop));
		}
	},
	browserErrors: [
		async ({ page, expectedStatuses, goesOffline }, use, testInfo) => {
			const errors: string[] = [];
			page.on('console', (message) => {
				if (
					message.type() === 'error' &&
					!(goesOffline && message.text().includes('ERR_INTERNET_DISCONNECTED')) &&
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
					!(goesOffline && request.failure()?.errorText.includes('ERR_INTERNET_DISCONNECTED')) &&
					!(
						request.failure()?.errorText.includes('ERR_ABORTED') &&
						request.method() === 'GET' &&
						/\/api\/(events|jobs|sessions(?:\/[^/]+(?:\/stream|\/side-chats(?:\/[^/]+\/stream)?)?)?)$/.test(
							new URL(request.url()).pathname
						)
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
