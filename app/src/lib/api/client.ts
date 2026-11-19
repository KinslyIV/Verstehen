import type { components } from './schema';

export type SessionDetail = components['schemas']['SessionDetail'];
export type SessionItem = components['schemas']['SessionItem'];
export type Entry = SessionDetail['entries'][number];
export type TurnInput = components['schemas']['TurnInput'];
export type TurnEvent = components['schemas']['TurnEvent'];
export type Notification = components['schemas']['Notification'];
let token: string | undefined;

export function setToken(value: string | undefined): void {
	token = value;
}

export class ApiError extends Error {
	constructor(
		public status: number,
		public code: string | undefined,
		message: string
	) {
		super(message);
	}
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
	const response = await fetch(path, {
		...init,
		headers: {
			...(init.body ? { 'content-type': 'application/json' } : {}),
			...init.headers,
			...(token ? { 'x-verstehen-token': token } : {})
		}
	});
	if (!response.ok) {
		const body = await response.json().catch(() => ({}));
		throw new ApiError(
			response.status,
			body.code,
			body.error ?? `HTTP ${response.status}: ${response.statusText}`
		);
	}
	return response;
}

export async function health(): Promise<{ status: string }> {
	return (await request('/api/health')).json();
}
export async function listSessions(signal?: AbortSignal): Promise<SessionItem[]> {
	return (await (await request('/api/sessions', { signal })).json()).sessions;
}
export async function createSession(title: string): Promise<components['schemas']['Created']> {
	return (
		await request('/api/sessions', { method: 'POST', body: JSON.stringify({ title }) })
	).json();
}
const sessionPath = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
export async function getSession(id: string, signal?: AbortSignal): Promise<SessionDetail> {
	return (await request(sessionPath(id), { signal })).json();
}
export async function renameSession(
	id: string,
	title: string
): Promise<components['schemas']['Renamed']> {
	return (
		await request(sessionPath(id), { method: 'PATCH', body: JSON.stringify({ title }) })
	).json();
}
export async function deleteSession(id: string): Promise<void> {
	await request(sessionPath(id), { method: 'DELETE' });
}
export async function postInput(id: string, input: TurnInput, signal?: AbortSignal): Promise<void> {
	await request(`${sessionPath(id)}/input`, {
		method: 'POST',
		body: JSON.stringify(input),
		signal
	});
}
export async function abortSession(id: string): Promise<void> {
	await request(`${sessionPath(id)}/abort`, { method: 'POST' });
}

/** Decode complete SSE frames across arbitrary UTF-8 and network boundaries. */
export async function readEvents(
	response: Response,
	receive: (event: string, data: string) => void
): Promise<boolean> {
	if (!response.body) throw new Error('The turn stream body is empty.');
	const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
	let pending = '';
	try {
		for (;;) {
			const { value, done } = await reader.read();
			if (done) return false;
			pending += value;
			let end: number;
			while ((end = pending.search(/\r?\n\r?\n/)) !== -1) {
				const frame = pending.slice(0, end);
				pending = pending.slice(end + (pending.slice(end).startsWith('\r\n') ? 4 : 2));
				let event = 'message';
				const data: string[] = [];
				for (const line of frame.split(/\r?\n/)) {
					if (line.startsWith('event:')) event = line.slice(6).trimStart();
					if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
				}
				if (!data.length) continue;
				if (data.join('\n') === '[DONE]') return true;
				receive(event, data.join('\n'));
			}
		}
	} finally {
		await reader.cancel().catch(() => {});
		reader.releaseLock();
	}
}

export async function streamTurn(
	id: string,
	receive: (event: TurnEvent) => void,
	signal: AbortSignal
): Promise<boolean> {
	return readEvents(await request(`${sessionPath(id)}/stream`, { signal }), (_, data) =>
		receive(JSON.parse(data))
	);
}
export async function streamNotifications(
	receive: (event: Notification) => void,
	signal: AbortSignal
): Promise<void> {
	await readEvents(await request('/api/events', { signal }), (type, data) =>
		receive({ ...JSON.parse(data), type })
	);
}
