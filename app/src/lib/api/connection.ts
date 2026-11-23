import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

export interface ServerConnection {
	server_url: string;
	device_id: string;
	token: string;
}

/** What the app remembers: the server address survives dropping a rejected token. */
export type StoredConnection = Partial<ServerConnection>;

export interface ConnectionStorage {
	load(): Promise<StoredConnection>;
	save(connection: StoredConnection): Promise<void>;
	clear(): Promise<void>;
}

const FIELDS = ['server_url', 'device_id', 'token'] as const;

/** The Android app's private storage (excluded from Android backup). */
const preferencesStorage: ConnectionStorage = {
	async load() {
		const stored: StoredConnection = {};
		for (const field of FIELDS) {
			const { value } = await Preferences.get({ key: field });
			if (value) stored[field] = value;
		}
		return stored;
	},
	async save(connection) {
		for (const field of FIELDS) {
			const value = connection[field];
			if (value) await Preferences.set({ key: field, value });
			else await Preferences.remove({ key: field });
		}
	},
	async clear() {
		await Preferences.clear();
	}
};

const BROWSER_KEY = 'verstehen-connection';

/** The headless verify flows' storage; a real browser never selects remote mode. */
const browserStorage: ConnectionStorage = {
	async load() {
		try {
			return JSON.parse(localStorage.getItem(BROWSER_KEY) ?? '{}');
		} catch {
			return {};
		}
	},
	async save(connection) {
		localStorage.setItem(BROWSER_KEY, JSON.stringify(connection));
	},
	async clear() {
		localStorage.removeItem(BROWSER_KEY);
	}
};

export type ClientMode = 'sidecar' | 'remote';

/** The Android app is always remote; headless flows opt in at build time. */
export function clientMode(): ClientMode {
	return __VERSTEHEN_CLIENT__ === 'remote' || Capacitor.isNativePlatform() ? 'remote' : 'sidecar';
}

const storage = () => (Capacitor.isNativePlatform() ? preferencesStorage : browserStorage);
let stored: Promise<StoredConnection> | undefined;

export function loadConnection(): Promise<StoredConnection> {
	return (stored ??= storage().load());
}

export async function saveConnection(connection: StoredConnection): Promise<void> {
	await storage().save(connection);
	stored = Promise.resolve(connection);
}

export async function clearConnection(): Promise<void> {
	await storage().clear();
	stored = Promise.resolve({});
}

/** Forgets a rejected token and device but keeps the server address for the next pairing. */
export async function dropToken(): Promise<void> {
	const { server_url } = await loadConnection();
	await saveConnection(server_url ? { server_url } : {});
}

export function isPaired(connection: StoredConnection): connection is ServerConnection {
	return Boolean(connection.server_url && connection.device_id && connection.token);
}

const isTailscaleAddress = (host: string): boolean => {
	const octets = host.split('.').map(Number);
	return (
		octets.length === 4 &&
		octets.every((octet) => Number.isInteger(octet) && octet >= 0 && octet <= 255) &&
		octets[0] === 100 &&
		octets[1] >= 64 &&
		octets[1] <= 127
	);
};

/** Turns `100.x.y.z:port` into a server URL; refuses hosts the app may not reach. */
export function parseServerAddress(
	input: string,
	extraHosts = __VERSTEHEN_EXTRA_HOSTS__.split(',').filter(Boolean)
): string {
	const text = input.trim();
	let url: URL;
	try {
		url = new URL(/^https?:\/\//i.test(text) ? text : `http://${text}`);
	} catch {
		throw new Error('Enter the server address as 100.x.y.z:port.');
	}
	if (!url.hostname || url.pathname !== '/' || url.search || url.hash)
		throw new Error('Enter the server address as 100.x.y.z:port.');
	if (!isTailscaleAddress(url.hostname) && !extraHosts.includes(url.hostname))
		throw new Error('The server must be at its Tailscale address, 100.x.y.z (100.64.0.0/10).');
	return url.origin;
}
