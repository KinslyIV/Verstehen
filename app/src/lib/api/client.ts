import { invoke, isTauri } from '@tauri-apps/api/core';
import type { components, operations } from './schema';

export type SessionDetail = components['schemas']['SessionDetail'];
export type SessionItem = components['schemas']['SessionItem'];
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
export type DeleteMode = 'preserve-graph' | 'delete-nodes';
let token: string | undefined;
let connection: Promise<string> | undefined;

export function setToken(value: string | undefined): void {
	token = value;
}

function baseUrl(): Promise<string> {
	if (!isTauri()) return Promise.resolve('');
	return (connection ??= invoke<{ port: number; token: string }>('sidecar_connection')
		.then((value) => {
			setToken(value.token);
			return `http://127.0.0.1:${value.port}`;
		})
		.catch((cause: unknown) => {
			connection = undefined;
			throw cause instanceof Error ? cause : new Error(String(cause));
		}));
}

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

async function request(path: string, init: RequestInit = {}): Promise<Response> {
	const base = await baseUrl();
	const response = await fetch(`${base}${path}`, {
		...init,
		headers: {
			...(init.body && !(init.body instanceof FormData)
				? { 'content-type': 'application/json' }
				: {}),
			...init.headers,
			...(token ? { 'x-verstehen-token': token } : {})
		}
	});
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

export async function health(): Promise<{ status: string }> {
	return (await request('/api/health')).json();
}
export async function listSessions(signal?: AbortSignal): Promise<SessionItem[]> {
	return (await (await request('/api/sessions', { signal })).json()).sessions;
}
export async function createSession(
	title: string,
	model?: ModelPick | null,
	graph_context?: GraphContext,
	kind: SessionKind = 'teach'
): Promise<components['schemas']['Created']> {
	return (
		await request('/api/sessions', {
			method: 'POST',
			body: JSON.stringify({ title, model, graph_context, kind })
		})
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
export async function deleteSession(id: string, mode: DeleteMode): Promise<void> {
	await request(`${sessionPath(id)}?mode=${mode}`, { method: 'DELETE' });
}
export async function postInput(id: string, input: TurnInput, signal?: AbortSignal): Promise<void> {
	await request(`${sessionPath(id)}/input`, {
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
	const response = await request(`${sessionPath(id)}/dismiss`, {
		method: 'POST',
		body: JSON.stringify(input),
		signal
	});
	return response.status === 202;
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

export async function getModels(options: { refresh?: boolean } = {}): Promise<ModelCatalog> {
	return (await request(options.refresh ? '/api/models?refresh=true' : '/api/models')).json();
}
export async function getSettings(): Promise<SettingsStatus> {
	return (await request('/api/settings')).json();
}
export async function saveSettings(settings: SettingsStatus): Promise<Settings> {
	const body = { ...settings };
	delete body.file_access_error;
	return (await request('/api/settings', { method: 'PUT', body: JSON.stringify(body) })).json();
}
export async function setDefaultModel(pick: ModelPick): Promise<ModelPick> {
	return (
		await request('/api/settings/default-model', { method: 'POST', body: JSON.stringify(pick) })
	).json();
}
export async function setSessionModel(id: string, model: ModelPick): Promise<void> {
	await request(sessionPath(id), { method: 'PATCH', body: JSON.stringify({ model }) });
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
	await request(`/api/accounts/chatgpt/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export async function getClaudeCode(): Promise<BinaryStatus> {
	return (await request('/api/accounts/claude-code')).json();
}
export const CLAUDE_CODE_INSTALL_URL = 'https://code.claude.com/docs/en/setup';
export async function openExternal(url: string): Promise<void> {
	if (isTauri()) await invoke('plugin:shell|open', { path: url });
	else window.open(url, '_blank', 'noopener,noreferrer');
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
	await request(`/api/jobs/${encodeURIComponent(id)}/abort`, { method: 'POST' });
}
export async function steerSession(id: string, steerId: string, text: string): Promise<void> {
	await request(`${sessionPath(id)}/steer`, {
		method: 'POST',
		body: JSON.stringify({ id: steerId, text })
	});
}
export async function setArtifactView(
	id: string,
	entryId: string,
	inverted: boolean
): Promise<void> {
	await request(`${sessionPath(id)}/artifact-views/${encodeURIComponent(entryId)}`, {
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
	await request(`${sidePath(id)}/${encodeURIComponent(threadId)}/stop`, { method: 'POST' });
}

export async function getGraph(signal?: AbortSignal): Promise<GraphSnapshot> {
	return (await request('/api/graph', { signal })).json();
}
export async function putGraphPositions(
	positions: Record<string, { x: number; y: number }>
): Promise<void> {
	await request('/api/graph/positions', { method: 'PUT', body: JSON.stringify(positions) });
}
export async function getGraphRenderSettings(
	signal?: AbortSignal
): Promise<GraphRenderSettings | null> {
	return (await request('/api/graph/render-settings', { signal })).json();
}
export async function putGraphRenderSettings(settings: GraphRenderSettings): Promise<void> {
	await request('/api/graph/render-settings', { method: 'PUT', body: JSON.stringify(settings) });
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
	| { action: 'delete-folder'; id: string };
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
	await request(`/api/graph/nodes/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
/** Starts a manual extraction; a 409 means one is already running and counts as started. */
export async function extractCoverage(sessionId: string): Promise<void> {
	try {
		await request('/api/graph/coverage/extract', {
			method: 'POST',
			body: JSON.stringify({ session_id: sessionId })
		});
	} catch (cause) {
		if (!(cause instanceof ApiError && cause.status === 409)) throw cause;
	}
}
export async function abortExtraction(source: string): Promise<void> {
	await request(`/api/graph/extractions/${encodeURIComponent(source)}/abort`, { method: 'POST' });
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
	await request('/api/server/trust-host', { method: 'POST', body: JSON.stringify(body) });
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
	await request(`/api/server/accounts/chatgpt/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export async function listServerDevices(): Promise<Device[]> {
	return (await (await request('/api/server/devices')).json()).devices;
}
export async function createServerPairingCode(): Promise<PairingCodeResponse> {
	return (await request('/api/server/pairing-code', { method: 'POST' })).json();
}
export async function revokeServerDevice(id: string): Promise<void> {
	await request(`/api/server/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
