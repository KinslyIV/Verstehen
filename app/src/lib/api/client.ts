import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import {
	clientMode,
	dropToken,
	isPaired,
	loadConnection,
	parseServerAddress,
	saveConnection,
	type ServerConnection
} from './connection';
import type { components, operations } from './schema';

export type SessionDetail = components['schemas']['SessionDetail'];
export type SessionItem = components['schemas']['SessionItem'];
export type SessionStats = components['schemas']['SessionStats'];
export type SessionKind = SessionItem['kind'];
export type Entry = SessionDetail['entries'][number];
export type ToolResult = components['schemas']['ToolResultEntry'];
export type FileAccess = components['schemas']['FileAccessSettings'];
export type ToolCallPart = components['schemas']['ToolCallPart'];
export type QuestionAnswer = components['schemas']['QuestionAnswer'];
export type DismissInput = components['schemas']['DismissInput'];
export type TurnInput = components['schemas']['TurnInput'];
export type TurnEvent = components['schemas']['TurnEvent'];
export type Notification = components['schemas']['Notification'];
export type ModelPick = components['schemas']['ModelPick'];
export type ModelCatalog = components['schemas']['ModelCatalog'];
export type CatalogModel = components['schemas']['CatalogModel'];
export type Settings = components['schemas']['Settings'];
export type SettingsStatus = components['schemas']['SettingsStatus'];
export type ModelSlots = components['schemas']['ModelSlots'];
export type Account = components['schemas']['Account'];
export type BinaryStatus = components['schemas']['BinaryStatus'];
export type SignInStatus = components['schemas']['SignInStatus'];
export type GraphSnapshot = components['schemas']['GraphSnapshot'];
export type GraphTitles = components['schemas']['GraphTitles'];
export type GraphNode = components['schemas']['GraphNode'];
export type GraphChain = components['schemas']['GraphChain'];
export type GraphRenderSettings = components['schemas']['GraphRenderSettings'];
export type RegionTuning = components['schemas']['RegionTuning'];
export type PhysicsTuning = components['schemas']['PhysicsTuning'];
export type GraphCostSummary = components['schemas']['GraphCostSummary'];
export type CostTotals = components['schemas']['CostTotals'];
export type RunningExtraction = components['schemas']['RunningExtraction'];
export type ImportResult = components['schemas']['ImportResult'];
export type SourceDirectory = components['schemas']['SourceDirectory'];
export type SourceEntry = components['schemas']['SourceEntry'];
export type SourceFolder = components['schemas']['SourceFolder'];
export type SourceOrganization = components['schemas']['SourceOrganization'];
export type SourcePlacement = components['schemas']['SourcePlacement'];
export type SessionCoverage = components['schemas']['SessionCoverage'];
export type GraphContext = components['schemas']['GraphContext'];
export type SyncStatusResponse = components['schemas']['SyncStatusResponse'];
export type ServerInstallStatus = components['schemas']['ServerInstallStatus'];
export type InstallStep = components['schemas']['InstallStep'];
export type HostKeyChallenge = components['schemas']['HostKeyChallenge'];
export type ServerSignInStarted = components['schemas']['ServerSignInStarted'];
export type ServerSignInHostKeyRequired = components['schemas']['ServerSignInHostKeyRequired'];
export type ServerSignInPasswordRequired = components['schemas']['ServerSignInPasswordRequired'];
export type ServerSignInResponse =
	ServerSignInStarted | ServerSignInHostKeyRequired | ServerSignInPasswordRequired;
export type ServerInstallInput = components['schemas']['ServerInstallInput'];
export type TrustHostInput = components['schemas']['TrustHostInput'];
export type ServerConnectInput = components['schemas']['ServerConnectInput'];
export type ServerChatGPTSignInInput = components['schemas']['ServerChatGPTSignInInput'];
export type Device = components['schemas']['Device'];
export type PairingCodeResponse = components['schemas']['PairingCodeResponse'];
export type PromptSegment = components['schemas']['PromptSegment'];
export type PromptSegments = components['schemas']['PromptSegments'];
export type DeleteMode = 'preserve-graph' | 'delete-nodes';
export class ApiError extends Error {
	constructor(
		public status: number,
		public code: string | undefined,
		message: string,
		public reason?: string,
		public missing?: string[]
	) {
		super(message);
	}
}

/** Forgets the token the server rejected and goes to /pair, unless a newer pairing replaced it. */
async function returnToPairing(rejectedToken: string | undefined): Promise<void> {
	if (await dropToken(rejectedToken)) await goto(resolve('/pair'));
}

interface Endpoint {
	base: string;
	auth: Record<string, string>;
	rejectedToken?: string;
}

/** Where requests go and how they authenticate: the app's own server, or the paired server. */
async function endpoint(): Promise<Endpoint> {
	if (clientMode() === 'sidecar') return { base: '', auth: {} };
	const connection = await loadConnection();
	if (!isPaired(connection)) {
		await returnToPairing(connection.token);
		throw new ApiError(401, undefined, 'This device is not paired with a server.');
	}
	return {
		base: connection.server_url,
		auth: { authorization: `Bearer ${connection.token}` },
		rejectedToken: connection.token
	};
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
	const { base, auth, rejectedToken } = await endpoint();
	const response = await fetch(`${base}${path}`, {
		...init,
		...(clientMode() === 'remote' ? { redirect: 'error' } : {}),
		headers: {
			...(init.body && !(init.body instanceof FormData)
				? { 'content-type': 'application/json' }
				: {}),
			...init.headers,
			...auth
		}
	});
	if (response.status === 401 && clientMode() === 'remote') await returnToPairing(rejectedToken);
	if (!response.ok) {
		const body = await response.json().catch(() => ({}));
		throw new ApiError(
			response.status,
			body.code,
			body.error ?? `HTTP ${response.status}: ${response.statusText}`,
			body.reason,
			body.missing
		);
	}
	return response;
}

/** Sends a non-streaming request and drains its body so navigation cannot abort an unread response. */
async function requestSettled(path: string, init: RequestInit = {}): Promise<Response> {
	const response = await request(path, init);
	await response.text();
	return response;
}

/** Redeems a pairing code with the server at `address` and returns the new connection. */
export async function pairDevice(
	address: string,
	code: string,
	deviceName: string
): Promise<ServerConnection> {
	const server_url = parseServerAddress(address);
	let response: Response;
	try {
		response = await fetch(`${server_url}/api/auth/pair`, {
			method: 'POST',
			redirect: 'error',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ code: code.trim().toUpperCase(), device_name: deviceName.trim() })
		});
	} catch {
		throw new Error(
			`Can't reach ${server_url}. Check the address and that Tailscale is connected.`
		);
	}
	if (response.status === 429)
		throw new Error('Too many wrong codes. Wait a few minutes, then try again.');
	if (response.status === 400)
		throw new Error('That code is invalid or has expired. Create a new one on the laptop.');
	if (!response.ok) throw new Error(`The server refused pairing (HTTP ${response.status}).`);
	const paired: { device_id: string; token: string } = await response.json();
	const connection = { server_url, device_id: paired.device_id, token: paired.token };
	await saveConnection(connection);
	return connection;
}

export async function health(): Promise<{ status: string; desktop?: boolean }> {
	return (await request('/api/health')).json();
}
export async function listSessions(signal?: AbortSignal): Promise<SessionItem[]> {
	return (await (await request('/api/sessions', { signal })).json()).sessions;
}
export async function createSession(
	title: string,
	model?: ModelPick | null,
	graph_context?: GraphContext,
	kind: SessionKind = 'teach',
	folder_id?: string
): Promise<components['schemas']['Created']> {
	return (
		await request('/api/sessions', {
			method: 'POST',
			body: JSON.stringify({ title, model, graph_context, kind, folder_id })
		})
	).json();
}
const sessionPath = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
export async function getSession(id: string, signal?: AbortSignal): Promise<SessionDetail> {
	return (await request(sessionPath(id), { signal })).json();
}
export async function getSessionStats(id: string, signal?: AbortSignal): Promise<SessionStats> {
	return (await request(`${sessionPath(id)}/stats`, { signal })).json();
}
export async function getSessionItem(
	id: string,
	signal?: AbortSignal
): Promise<SessionItem | null> {
	return (await request(`${sessionPath(id)}/item`, { signal })).json();
}
export async function getSessionCoverage(
	id: string,
	signal?: AbortSignal
): Promise<SessionCoverage | null> {
	return (await request(`${sessionPath(id)}/coverage`, { signal })).json();
}
export async function renameSession(
	id: string,
	title: string
): Promise<components['schemas']['Renamed']> {
	return (
		await request(sessionPath(id), { method: 'PATCH', body: JSON.stringify({ title }) })
	).json();
}
export async function deleteSession(id: string, mode: DeleteMode): Promise<void> {
	await requestSettled(`${sessionPath(id)}?mode=${mode}`, { method: 'DELETE' });
}
export async function postInput(id: string, input: TurnInput, signal?: AbortSignal): Promise<void> {
	await requestSettled(`${sessionPath(id)}/input`, {
		method: 'POST',
		body: JSON.stringify(input),
		signal
	});
}
export async function dismissQuestion(
	id: string,
	input: DismissInput,
	signal: AbortSignal
): Promise<boolean> {
	const response = await requestSettled(`${sessionPath(id)}/dismiss`, {
		method: 'POST',
		body: JSON.stringify(input),
		signal
	});
	return response.status === 202;
}
export async function abortSession(id: string): Promise<void> {
	await requestSettled(`${sessionPath(id)}/abort`, { method: 'POST' });
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

/** `opened` runs once the server has accepted the stream, before its first event. */
export async function streamTurn(
	id: string,
	receive: (event: TurnEvent) => void,
	signal: AbortSignal,
	opened?: () => void
): Promise<boolean> {
	const response = await request(`${sessionPath(id)}/stream`, { signal });
	opened?.();
	return readEvents(response, (_, data) => receive(JSON.parse(data)));
}
export async function streamNotifications(
	receive: (event: Notification) => void,
	signal: AbortSignal,
	opened?: () => void
): Promise<void> {
	const response = await request('/api/events', { signal });
	opened?.();
	await readEvents(response, (type, data) => receive({ ...JSON.parse(data), type }));
}

export async function getModels(): Promise<ModelCatalog> {
	return (await request('/api/models')).json();
}
export async function refreshModels(force = false): Promise<void> {
	await requestSettled(force ? '/api/models/refresh?force=true' : '/api/models/refresh', {
		method: 'POST'
	});
}
export async function getSettings(): Promise<SettingsStatus> {
	return (await request('/api/settings')).json();
}
export async function saveSettings(
	settings: SettingsStatus,
	includeModels = false
): Promise<Settings> {
	const body = { ...settings };
	delete body.file_access_error;
	if (!includeModels) delete body.models;
	return (await request('/api/settings', { method: 'PATCH', body: JSON.stringify(body) })).json();
}
const promptPath = (path: string) =>
	`/api/prompts/${path.split('/').map(encodeURIComponent).join('/')}`;
export async function getPrompts(signal?: AbortSignal): Promise<PromptSegments> {
	return (await request('/api/prompts', { signal })).json();
}
export async function savePromptOverride(path: string, text: string): Promise<void> {
	await requestSettled(`${promptPath(path)}/override`, {
		method: 'PUT',
		body: JSON.stringify({ text })
	});
}
export async function deletePromptOverride(path: string): Promise<void> {
	await requestSettled(`${promptPath(path)}/override`, { method: 'DELETE' });
}
/** Resolves with the switch as the server stored it. */
export async function setPromptEnabled(path: string, enabled: boolean): Promise<boolean> {
	const reply = await request(`${promptPath(path)}/enabled`, {
		method: 'PUT',
		body: JSON.stringify({ enabled })
	});
	return (await reply.json()).enabled;
}
export async function setDefaultModel(pick: ModelPick): Promise<ModelPick> {
	return (
		await request('/api/settings/default-model', { method: 'POST', body: JSON.stringify(pick) })
	).json();
}
export async function setModelSlot(
	slot: keyof ModelCatalog['slots'],
	pick: ModelPick
): Promise<ModelPick> {
	return (
		await request(`/api/settings/models/${slot}`, { method: 'PUT', body: JSON.stringify(pick) })
	).json();
}
export async function setSessionModel(id: string, model: ModelPick): Promise<void> {
	await requestSettled(sessionPath(id), { method: 'PATCH', body: JSON.stringify({ model }) });
}
export async function listChatGPTAccounts(): Promise<Account[]> {
	return (await request('/api/accounts/chatgpt')).json();
}
export async function startChatGPTSignIn(
	account?: string
): Promise<components['schemas']['SignInStarted']> {
	return (
		await request(
			account
				? `/api/accounts/chatgpt/${encodeURIComponent(account)}/sign-in`
				: '/api/accounts/chatgpt',
			{ method: 'POST' }
		)
	).json();
}
export async function getSignIn(id: string): Promise<SignInStatus> {
	return (await request(`/api/accounts/chatgpt/sign-in/${encodeURIComponent(id)}`)).json();
}
export async function removeChatGPTAccount(id: string): Promise<void> {
	await requestSettled(`/api/accounts/chatgpt/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export async function getClaudeCode(): Promise<BinaryStatus> {
	return (await request('/api/accounts/claude-code')).json();
}
export const CLAUDE_CODE_INSTALL_URL = 'https://code.claude.com/docs/en/setup';
export function openExternal(url: string): void {
	window.open(url, '_blank', 'noopener,noreferrer');
}
export const LINK_REFUSED_EVENT = 'verstehen:link-refused';
/** Calls `refused` with the URL when the desktop shell declines to open a link; returns the unsubscribe. */
export function onLinkRefused(refused: (url: string) => void): () => void {
	const listen = (event: Event) => refused((event as CustomEvent<string>).detail);
	window.addEventListener(LINK_REFUSED_EVENT, listen);
	return () => window.removeEventListener(LINK_REFUSED_EVENT, listen);
}

export type DemoBrowser = components['schemas']['DemoBrowser'];
export type BrowserDownloadProgress = components['schemas']['BrowserDownloadProgress'];
export type SearchKeysStatus = components['schemas']['SearchKeysStatus'];
export type SearchEngine = 'tavily' | 'brave';
export async function getDemoBrowser(): Promise<DemoBrowser> {
	return (await request('/api/demo-browser')).json();
}
export async function browserDownload(start = false): Promise<BrowserDownloadProgress> {
	return (await request('/api/demo-browser/download', { method: start ? 'POST' : 'GET' })).json();
}
export async function getSearchKeys(): Promise<SearchKeysStatus> {
	return (await request('/api/search-keys')).json();
}
export async function setSearchKey(
	engine: SearchEngine,
	value: string | null
): Promise<SearchKeysStatus> {
	return (
		await request(`/api/search-keys/${engine}`, {
			method: value === null ? 'DELETE' : 'PUT',
			...(value === null ? {} : { body: JSON.stringify({ value }) })
		})
	).json();
}

export async function getImage(
	sha256: string,
	extension: 'png' | 'jpeg',
	signal?: AbortSignal
): Promise<Blob> {
	return (
		await request(`/api/images/${encodeURIComponent(sha256)}.${extension}`, { signal })
	).blob();
}

export type JobRecord = components['schemas']['JobRecord'];
export type JobList = components['schemas']['JobList'];
export async function getJobs(session: string, signal?: AbortSignal): Promise<JobList> {
	return (await request(`/api/jobs?session=${encodeURIComponent(session)}`, { signal })).json();
}
export async function abortJob(id: string): Promise<void> {
	await requestSettled(`/api/jobs/${encodeURIComponent(id)}/abort`, { method: 'POST' });
}
export async function steerSession(id: string, steerId: string, text: string): Promise<void> {
	await requestSettled(`${sessionPath(id)}/steer`, {
		method: 'POST',
		body: JSON.stringify({ id: steerId, text })
	});
}
export async function setArtifactView(
	id: string,
	entryId: string,
	inverted: boolean
): Promise<void> {
	await requestSettled(`${sessionPath(id)}/artifact-views/${encodeURIComponent(entryId)}`, {
		method: 'PUT',
		body: JSON.stringify({ inverted })
	});
}

export type SideThread = components['schemas']['SideThread'];
export type SideExchange = components['schemas']['SideExchange'];
export type SideChatList = components['schemas']['SideChatList'];
export type SideStreamEvent = components['schemas']['SideStreamEvent'];
export type SideSegments = components['schemas']['SideSegments'];
export type SideAskBody = NonNullable<
	operations['ask_side_chat_api_sessions__session_id__side_chats_post']['requestBody']
>['content']['application/json'];
const sidePath = (id: string) => `${sessionPath(id)}/side-chats`;
export async function getSideChats(id: string, signal?: AbortSignal): Promise<SideChatList> {
	return (await request(sidePath(id), { signal })).json();
}
export async function askSideChat(
	id: string,
	body: SideAskBody,
	signal?: AbortSignal
): Promise<SideThread> {
	return (
		await request(sidePath(id), { method: 'POST', body: JSON.stringify(body), signal })
	).json();
}
export async function streamSideChat(
	id: string,
	threadId: string,
	receive: (event: SideStreamEvent) => void,
	signal: AbortSignal
): Promise<boolean> {
	const response = await request(`${sidePath(id)}/${encodeURIComponent(threadId)}/stream`, {
		signal
	});
	return readEvents(response, (_, data) => receive(JSON.parse(data)));
}
export async function stopSideChat(id: string, threadId: string): Promise<void> {
	await requestSettled(`${sidePath(id)}/${encodeURIComponent(threadId)}/stop`, { method: 'POST' });
}

export async function getGraph(signal?: AbortSignal): Promise<GraphSnapshot> {
	return (await request('/api/graph', { signal })).json();
}
export async function getGraphTitles(signal?: AbortSignal): Promise<GraphTitles> {
	return (await request('/api/graph/titles', { signal })).json();
}
/** Saves the layout; resolves with the graph revision the save produced. */
export async function putGraphPositions(
	positions: Record<string, { x: number; y: number }>
): Promise<number | null> {
	const response = await request('/api/graph/positions', {
		method: 'PUT',
		body: JSON.stringify(positions)
	});
	return (await response.json()).revision;
}
export async function getGraphRenderSettings(
	signal?: AbortSignal
): Promise<GraphRenderSettings | null> {
	return (await request('/api/graph/render-settings', { signal })).json();
}
export async function putGraphRenderSettings(settings: GraphRenderSettings): Promise<void> {
	await requestSettled('/api/graph/render-settings', {
		method: 'PUT',
		body: JSON.stringify(settings)
	});
}
export async function getGraphCosts(signal?: AbortSignal): Promise<GraphCostSummary> {
	return (await request('/api/graph/costs', { signal })).json();
}
export async function getExtractionStatus(signal?: AbortSignal): Promise<RunningExtraction[]> {
	return (await (await request('/api/graph/status', { signal })).json()).runs;
}
/** Imports one notes file; `path` is its folder-relative name, the identity of its source. */
export async function importNotes(file: File, path: string): Promise<ImportResult> {
	const form = new FormData();
	form.append('files', file);
	form.append('paths', path);
	return (await (await request('/api/graph/import', { method: 'POST', body: form })).json())
		.results[0];
}
export type OrganizationAction =
	| { action: 'create-folder'; name: string; parent_id: string | null }
	| { action: 'rename-folder'; id: string; name: string }
	| { action: 'rename-source'; id: string; name: string }
	| { action: 'move'; kind: 'source' | 'folder'; id: string; parent_id: string | null }
	| { action: 'delete-folder'; id: string }
	| { action: 'delete-folder-tree'; id: string };
export async function getSourceDirectory(signal?: AbortSignal): Promise<SourceDirectory> {
	return (await request('/api/graph/sources', { signal })).json();
}
export async function organizeSources(action: OrganizationAction): Promise<SourceDirectory> {
	return (
		await request('/api/graph/sources', { method: 'POST', body: JSON.stringify(action) })
	).json();
}
export async function deleteSources(body: {
	source_ids: string[];
	folder_ids: string[];
	delete_sessions: boolean;
}): Promise<SourceDirectory> {
	return (
		await request('/api/graph/sources', { method: 'DELETE', body: JSON.stringify(body) })
	).json();
}
export async function deleteGraphNode(id: string): Promise<void> {
	await requestSettled(`/api/graph/nodes/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
/** Starts a manual extraction; a 409 means one is already running and counts as started. */
export async function extractCoverage(sessionId: string): Promise<void> {
	try {
		await requestSettled('/api/graph/coverage/extract', {
			method: 'POST',
			body: JSON.stringify({ session_id: sessionId })
		});
	} catch (cause) {
		if (!(cause instanceof ApiError && cause.status === 409)) throw cause;
	}
}
export async function abortExtraction(source: string): Promise<void> {
	await requestSettled(`/api/graph/extractions/${encodeURIComponent(source)}/abort`, {
		method: 'POST'
	});
}

export async function getSyncStatus(signal?: AbortSignal): Promise<SyncStatusResponse> {
	return (await request('/api/sync/status', { signal })).json();
}
export async function syncNow(): Promise<SyncStatusResponse> {
	return (await request('/api/sync/now', { method: 'POST' })).json();
}
export async function startServerInstall(body: ServerInstallInput): Promise<ServerInstallStatus> {
	return (
		await request('/api/server/install', { method: 'POST', body: JSON.stringify(body) })
	).json();
}
export async function getServerInstallStatus(signal?: AbortSignal): Promise<ServerInstallStatus> {
	return (await request('/api/server/install', { signal })).json();
}
export async function trustServerHost(body: TrustHostInput): Promise<void> {
	await requestSettled('/api/server/trust-host', { method: 'POST', body: JSON.stringify(body) });
}
export async function connectServer(body: ServerConnectInput): Promise<SyncStatusResponse> {
	return (
		await request('/api/server/connect', { method: 'POST', body: JSON.stringify(body) })
	).json();
}
export async function disconnectServer(): Promise<SyncStatusResponse> {
	return (await request('/api/server/disconnect', { method: 'POST' })).json();
}
export async function getServerClaudeCode(): Promise<BinaryStatus> {
	return (await request('/api/server/accounts/claude-code')).json();
}
export async function listServerChatGPTAccounts(): Promise<Account[]> {
	return (await request('/api/server/accounts/chatgpt')).json();
}
export async function startServerChatGPTSignIn(
	body?: ServerChatGPTSignInInput
): Promise<ServerSignInResponse> {
	return (
		await request('/api/server/accounts/chatgpt', {
			method: 'POST',
			...(body ? { body: JSON.stringify(body) } : {})
		})
	).json();
}
export async function getServerChatGPTSignIn(id: string): Promise<SignInStatus> {
	return (await request(`/api/server/accounts/chatgpt/sign-in/${encodeURIComponent(id)}`)).json();
}
export async function removeServerChatGPTAccount(id: string): Promise<void> {
	await requestSettled(`/api/server/accounts/chatgpt/${encodeURIComponent(id)}`, {
		method: 'DELETE'
	});
}
export async function getOwnDeviceName(id: string): Promise<string | undefined> {
	const { devices } = await (await request('/api/auth/devices')).json();
	return devices.find((device: Device) => device.id === id)?.name;
}
/** Ends this device's pairing on the server it is paired with. */
export async function revokeOwnDevice(id: string): Promise<void> {
	await requestSettled(`/api/auth/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export async function listServerDevices(): Promise<Device[]> {
	return (await (await request('/api/server/devices')).json()).devices;
}
export async function createServerPairingCode(): Promise<PairingCodeResponse> {
	return (await request('/api/server/pairing-code', { method: 'POST' })).json();
}
export async function revokeServerDevice(id: string): Promise<void> {
	await requestSettled(`/api/server/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
