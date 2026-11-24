import { test as base, expect, type Frame, type Request } from '@playwright/test';
import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createConnection, createServer, type Socket } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { promisify } from 'node:util';
import type { Entry } from '../src/lib/api/client';
import { fileURLToPath } from 'node:url';

const runFile = promisify(execFile);
const appDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');

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

class PreviewExitError extends Error {}

async function previewHandshake(child: ChildProcess): Promise<number> {
	if (!child.stdout) throw new Error('Vite preview stdout is missing');
	const lines = createInterface({ input: child.stdout });
	const timeout = new AbortController();
	const timer = setTimeout(() => {
		timeout.abort();
		lines.close();
	}, 15000);
	try {
		for await (const line of lines) {
			const match = /Local:\s+http:\/\/127\.0\.0\.1:(\d+)\/?/.exec(line);
			if (!match) continue;
			const port = Number(match[1]);
			if (!Number.isInteger(port) || port < 1 || port > 65535)
				throw new Error(`Invalid preview URL line: ${line}`);
			return port;
		}
		if (timeout.signal.aborted)
			throw new Error('Vite preview did not print its local URL within 15 seconds');
		if (child.exitCode === null && child.signalCode === null) {
			try {
				await once(child, 'exit', { signal: timeout.signal });
			} catch (error) {
				if (timeout.signal.aborted)
					throw new Error('Vite preview did not print its local URL within 15 seconds', {
						cause: error
					});
				throw error;
			}
		}
		throw new PreviewExitError(
			`Vite preview exited with ${child.exitCode ?? child.signalCode} before listening`
		);
	} finally {
		clearTimeout(timer);
		lines.close();
		child.stdout.resume();
	}
}

interface TcpForwarder {
	readonly port: number;
	pause(): void;
	pointTo(port: number): void;
	close(): Promise<void>;
}

/** Keep one stable listener so upstream port swaps or offline pauses preserve the bound port. */
async function createTcpForwarder(initialPort: number): Promise<TcpForwarder> {
	let targetPort: number | null = initialPort;
	const sockets = new Set<Socket>();
	const server = createServer((client) => {
		if (targetPort === null) {
			client.destroy();
			return;
		}
		const upstream = createConnection({ host: '127.0.0.1', port: targetPort });
		client.setNoDelay(true);
		upstream.setNoDelay(true);
		sockets.add(client);
		sockets.add(upstream);
		client.on('close', () => {
			sockets.delete(client);
			upstream.destroy();
		});
		upstream.on('close', (hadError) => {
			sockets.delete(upstream);
			if (hadError) client.destroy();
		});
		client.on('error', () => upstream.destroy());
		upstream.on('error', () => client.destroy());
		client.pipe(upstream);
		upstream.pipe(client);
	});
	server.listen(0, '127.0.0.1');
	await once(server, 'listening');
	const address = server.address();
	if (!address || typeof address === 'string') {
		await new Promise<void>((resolve) => server.close(() => resolve()));
		throw new Error('No free upstream forwarder port');
	}
	return {
		port: address.port,
		pause: () => {
			targetPort = null;
			for (const socket of sockets) socket.destroy();
			sockets.clear();
		},
		pointTo: (port) => {
			targetPort = port;
		},
		close: async () => {
			targetPort = null;
			for (const socket of sockets) socket.destroy();
			sockets.clear();
			await new Promise<void>((resolve, reject) =>
				server.close((error) => (error ? reject(error) : resolve()))
			);
		}
	};
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
	networkControl: { setOffline: (offline: boolean) => void };
	setOffline: (offline: boolean) => Promise<void>;
	teardownControl: {
		run: <T>(paths: readonly string[], action: () => Promise<T>) => Promise<T>;
		isExpected: (request: Request) => boolean;
	};
	/** Allow expected `ERR_ABORTED` GETs for pre-navigation requests during a teardown action. */
	allowTeardownAborts: <T>(paths: readonly string[], action: () => Promise<T>) => Promise<T>;
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
	networkControl: async ({ goesOffline }, use) => {
		await use({
			setOffline: () => {
				throw new Error(
					goesOffline ? 'Preview is not started' : 'setOffline requires goesOffline: true'
				);
			}
		});
	},
	setOffline: async ({ baseURL, context, networkControl }, use) => {
		if (!baseURL) throw new Error('Preview is not started');
		await use(async (offline) => {
			if (offline) {
				await context.setOffline(true);
				networkControl.setOffline(true);
			} else {
				networkControl.setOffline(false);
				await context.setOffline(false);
			}
		});
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
		{
			script,
			client,
			goesOffline,
			playwright,
			dataDirectory,
			sidecarControl,
			networkControl,
			serverAdmin
		},
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
		let upstreamForwarder: TcpForwarder | undefined;
		let browserForwarder: TcpForwarder | undefined;
		try {
			let sidecar = await start(
				resolve(appDirectory, '../backend/.venv/bin/verstehen'),
				sidecarArguments,
				env
			);
			children.push(sidecar);
			const port = await handshake(sidecar);
			upstreamForwarder = await createTcpForwarder(port);
			const launchPreview = async (
				upstreamPort: number
			): Promise<{ child: ChildProcess; port: number }> => {
				const previewEnv: NodeJS.ProcessEnv = {
					...env,
					VERSTEHEN_PORT: String(upstreamPort),
					NO_COLOR: '1',
					...(remote
						? { PUBLIC_VERSTEHEN_CLIENT: 'remote', PUBLIC_VERSTEHEN_EXTRA_HOSTS: '127.0.0.1' }
						: {})
				};
				delete previewEnv.FORCE_COLOR;
				const args = [
					'node_modules/vite/bin/vite.js',
					'preview',
					'--host',
					'127.0.0.1',
					'--port',
					'0'
				];
				for (let attempt = 1; ; attempt++) {
					const child = await start(process.execPath, args, previewEnv);
					try {
						const boundPort = await previewHandshake(child);
						children.push(child);
						return { child, port: boundPort };
					} catch (error) {
						await stop(child);
						if (!(error instanceof PreviewExitError) || attempt >= 5) throw error;
					}
				}
			};
			const { port: previewPort } = await launchPreview(upstreamForwarder.port);
			let browserPort = previewPort;
			if (goesOffline) {
				browserForwarder = await createTcpForwarder(previewPort);
				browserPort = browserForwarder.port;
				networkControl.setOffline = (offline) => {
					if (offline) browserForwarder?.pause();
					else browserForwarder?.pointTo(previewPort);
				};
			}
			const url = `http://127.0.0.1:${browserPort}`;
			sidecarControl.restart = async () => {
				upstreamForwarder?.pause();
				await stop(sidecar);
				sidecar = await start(
					resolve(appDirectory, '../backend/.venv/bin/verstehen'),
					sidecarArguments,
					env
				);
				children.push(sidecar);
				upstreamForwarder?.pointTo(await handshake(sidecar));
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
			await browserForwarder?.close();
			await upstreamForwarder?.close();
			await Promise.all(children.map(stop));
		}
	},
	teardownControl: async ({ page }, use) => {
		const inFlight = new Set<Request>();
		let active: {
			paths: readonly string[];
			requests: Set<Request>;
			accepting: boolean;
		} | null = null;
		const onRequest = (request: Request) => {
			inFlight.add(request);
			if (active?.accepting) active.requests.add(request);
		};
		const onSettled = (request: Request) => inFlight.delete(request);
		const onNavigated = (frame: Frame) => {
			if (frame === page.mainFrame() && active) active.accepting = false;
		};
		page.on('request', onRequest);
		page.on('requestfinished', onSettled);
		page.on('requestfailed', onSettled);
		page.on('framenavigated', onNavigated);
		try {
			await use({
				run: async (paths, action) => {
					if (active !== null)
						throw new Error('Nested allowTeardownAborts calls are not supported');
					active = { paths, requests: new Set(inFlight), accepting: true };
					try {
						return await action();
					} finally {
						active = null;
					}
				},
				isExpected: (request) =>
					active !== null &&
					active.requests.has(request) &&
					request.failure()?.errorText.includes('ERR_ABORTED') === true &&
					request.method() === 'GET' &&
					active.paths.includes(new URL(request.url()).pathname)
			});
		} finally {
			page.off('request', onRequest);
			page.off('requestfinished', onSettled);
			page.off('requestfailed', onSettled);
			page.off('framenavigated', onNavigated);
			inFlight.clear();
			active = null;
		}
	},
	allowTeardownAborts: async ({ teardownControl }, use) => {
		await use((paths, action) => teardownControl.run(paths, action));
	},
	browserErrors: [
		async ({ page, expectedStatuses, goesOffline, teardownControl }, use, testInfo) => {
			const errors: string[] = [];
			const offlineError = (text: string) =>
				/ERR_(INTERNET_DISCONNECTED|INCOMPLETE_CHUNKED_ENCODING|CONNECTION_RESET|EMPTY_RESPONSE)/.test(
					text
				);
			page.on('console', (message) => {
				if (
					message.type() === 'error' &&
					!(goesOffline && offlineError(message.text())) &&
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
					!(goesOffline && offlineError(request.failure()?.errorText ?? '')) &&
					!teardownControl.isExpected(request) &&
					!(
						request.failure()?.errorText.includes('ERR_ABORTED') &&
						request.method() === 'GET' &&
						/\/api\/(events|jobs|models|graph\/sources|prompts|sessions(?:\/[^/]+(?:\/stream|\/stats|\/side-chats(?:\/[^/]+\/stream)?)?)?)$/.test(
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
