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
	return __VERSTEHEN_CLIENT__ !== 'sidecar' || Capacitor.isNativePlatform() ? 'remote' : 'sidecar';
}

const storage = () => (Capacitor.isNativePlatform() ? preferencesStorage : browserStorage);
let stored: Promise<StoredConnection> | undefined;

export function loadConnection(): Promise<StoredConnection> {
	return (stored ??= storage().load());
}

let writes: Promise<unknown> = Promise.resolve();

/** Runs connection writes one at a time, so a stale rejection cannot interleave with a pairing. */
function serialized<T>(write: () => Promise<T>): Promise<T> {
	const result = writes.then(write);
	writes = result.catch(() => {});
	return result;
}

const writeConnection = async (connection: StoredConnection): Promise<void> => {
	await storage().save(connection);
	stored = Promise.resolve(connection);
};

export const saveConnection = (connection: StoredConnection): Promise<void> =>
	serialized(() => writeConnection(connection));

export const clearConnection = (): Promise<void> =>
	serialized(async () => {
		await storage().clear();
		stored = Promise.resolve({});
	});

/** Drops the rejected token (keeping the address) unless a newer pairing replaced it; true if dropped. */
export const dropToken = (rejectedToken: string | undefined): Promise<boolean> =>
	serialized(async () => {
		const { server_url, token } = await loadConnection();
		if (token !== rejectedToken) return false;
		await writeConnection(server_url ? { server_url } : {});
		return true;
	});

export function isPaired(connection: StoredConnection): connection is ServerConnection {
	return Boolean(connection.server_url && connection.device_id && connection.token);
}

const isTailscaleAddress = (host: string): boolean => {
	const parts = host.split('.');
	if (parts.length !== 4 || !parts.every((part) => /^\d{1,3}$/.test(part))) return false;
	const octets = parts.map(Number);
	return (
		octets.every((octet) => octet <= 255) &&
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
	const typedHost = text.replace(/^https?:\/\//i, '').split(/[:/?#]/)[0];
	if (!url.hostname || typedHost !== url.hostname || url.pathname !== '/' || url.search || url.hash)
		throw new Error('Enter the server address as 100.x.y.z:port.');
	if (!isTailscaleAddress(url.hostname) && !extraHosts.includes(url.hostname))
		throw new Error('The server must be at its Tailscale address, 100.x.y.z (100.64.0.0/10).');
	return url.origin;
}
