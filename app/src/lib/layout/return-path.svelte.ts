const STORAGE_KEY = 'verstehen-settings-return';

/** Whether `pathname` is an in-app destination Settings Back can return to. */
export function isReturnablePath(pathname: string): boolean {
	return (
		pathname.startsWith('/') &&
		!pathname.startsWith('//') &&
		pathname !== '/settings' &&
		!pathname.startsWith('/settings/') &&
		pathname !== '/pair' &&
		!pathname.startsWith('/pair/')
	);
}

function readStored(): string {
	try {
		const raw = sessionStorage.getItem(STORAGE_KEY);
		if (raw && isReturnablePath(new URL(raw, 'http://localhost').pathname)) return raw;
	} catch {
		/* Storage is unavailable in private or restricted environments. */
	}
	return '/';
}

/** Last non-Settings path visited, kept across reloads on `/settings`. */
class ReturnPath {
	path = $state<string>(readStored());

	remember(url: Pick<URL, 'pathname' | 'search' | 'hash'>): void {
		if (!isReturnablePath(url.pathname)) return;
		const target = `${url.pathname}${url.search}${url.hash}`;
		this.path = target;
		try {
			sessionStorage.setItem(STORAGE_KEY, target);
		} catch {
			/* Keep the in-memory path if sessionStorage rejects writes. */
		}
	}

	reset(): void {
		this.path = '/';
		try {
			sessionStorage.removeItem(STORAGE_KEY);
		} catch {
			/* Ignore unavailable storage. */
		}
	}
}

export const returnPath = new ReturnPath();
