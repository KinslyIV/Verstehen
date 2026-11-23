<script lang="ts">
	import { onMount } from 'svelte';
	import { Button } from '#lib/components/ui/button/index.js';
	import * as Dialog from '#lib/components/ui/dialog/index.js';
	import { live } from '#lib/api/live.svelte.js';
	import {
		ApiError,
		connectServer,
		createServerPairingCode,
		disconnectServer,
		getServerChatGPTSignIn,
		getServerClaudeCode,
		getServerInstallStatus,
		getSyncStatus,
		listServerChatGPTAccounts,
		listServerDevices,
		openExternal,
		removeServerChatGPTAccount,
		revokeServerDevice,
		startServerChatGPTSignIn,
		startServerInstall,
		streamNotifications,
		syncNow,
		trustServerHost,
		type Account,
		type BinaryStatus,
		type Device,
		type HostKeyChallenge,
		type PairingCodeResponse,
		type ServerInstallInput,
		type ServerInstallStatus,
		type SyncStatusResponse
	} from '#lib/api/client.js';

	const inputClass = 'h-9 min-w-0 rounded-md border bg-background px-3 text-sm disabled:opacity-50';

	const syncStatusLabels: Record<SyncStatusResponse['status'], string> = {
		disabled: 'Disabled',
		idle: 'Synced',
		syncing: 'Syncing…',
		offline: 'Offline',
		update_required: 'Update required',
		error: 'Error'
	};

	const syncDotClasses: Record<SyncStatusResponse['status'], string> = {
		disabled: 'bg-muted-foreground',
		idle: 'bg-emerald-500',
		syncing: 'bg-primary',
		offline: 'bg-amber-500',
		update_required: 'bg-amber-500',
		error: 'bg-destructive'
	};

	const accountStateLabels: Record<string, string> = {
		ready: 'Connected',
		needs_sign_in: 'Needs sign-in',
		unavailable: 'Unavailable',
		not_installed: 'Not installed',
		too_old: 'Too old',
		untested: 'Untested',
		tested: 'Tested'
	};

	const stepStatusLabels: Record<string, string> = {
		pending: 'Pending',
		running: 'Running…',
		done: 'Done',
		warning: 'Warning',
		failed: 'Failed'
	};

	let status = $state<SyncStatusResponse | null>(null);
	let installStatus = $state<ServerInstallStatus | null>(null);
	let accounts = $state<Account[]>([]);
	let claude = $state<BinaryStatus | null>(null);
	let devices = $state<Device[]>([]);
	let pairingCode = $state<PairingCodeResponse | null>(null);
	let nowMs = $state(Date.now());

	let setupMode = $state<'install' | 'connect'>('install');
	let connectAuthMode = $state<'code' | 'token'>('code');

	let installHost = $state('');
	let installServerPort = $state('8420');
	let installSshUser = $state('');
	let installSshPort = $state('22');
	let installSshPassword = $state('');
	let installDeviceName = $state('Laptop');

	let connectHost = $state('');
	let connectServerPort = $state('8420');
	let connectPairingCode = $state('');
	let connectToken = $state('');
	let connectDeviceName = $state('Laptop');

	let pendingSignInId = $state<string | null>(null);
	let pendingSignInAccountId = $state<string | null>(null);
	let signInUrl = $state<string | null>(null);
	let oauthHostKey = $state<HostKeyChallenge | null>(null);

	let sshModalOpen = $state(false);
	let sshModalPurpose = $state<'oauth' | 'update'>('oauth');
	let sshModalUser = $state('');
	let sshModalPort = $state('22');
	let sshModalPassword = $state('');

	let disconnectDialogOpen = $state(false);
	let revokeSelfDevice = $state<Device | null>(null);

	let busy = $state(false);
	let syncBusy = $state(false);
	let error = $state<string | null>(null);
	let accountsError = $state<string | null>(null);
	let claudeError = $state<string | null>(null);
	let signInFailure = $state<string | null>(null);
	let devicesError = $state<string | null>(null);
	let copiedField = $state<'url' | 'code' | null>(null);

	type OAuthAttempt = {
		accountId: string | null;
		ssh: { ssh_user: string; ssh_port: number; ssh_password: string } | null;
	};

	// In-memory only: the attempts keep one-time SSH passwords across TOFU and password prompts.
	let installAttempt: ServerInstallInput | null = null;
	let oauthAttempt: OAuthAttempt | null = null;
	let generation = 0;
	let statusSeq = 0;
	let installSeq = 0;
	let disposed = false;
	let pollingInstall = false;
	let pollingSignIn = false;

	function messageOf(cause: unknown): string {
		return cause instanceof Error ? cause.message : String(cause);
	}

	function parseServerEndpoint(url: string | null | undefined): { host: string; port: number } {
		if (!url) return { host: '', port: 8420 };
		try {
			const parsed = new URL(url);
			return {
				host: parsed.hostname,
				port: parsed.port ? Number(parsed.port) : 8420
			};
		} catch {
			return { host: '', port: 8420 };
		}
	}

	function formatPairingCode(code: string): string {
		const cleaned = code.replace(/[\s-]+/g, '').toUpperCase();
		if (cleaned.length === 8) return `${cleaned.slice(0, 4)}-${cleaned.slice(4)}`;
		return cleaned;
	}

	const pairingRemainingSeconds = $derived.by(() => {
		if (!pairingCode) return 0;
		const expiresMs = new Date(pairingCode.expires_at).getTime();
		return Math.max(0, Math.ceil((expiresMs - nowMs) / 1000));
	});

	const pairingCountdownLabel = $derived.by(() => {
		const secs = pairingRemainingSeconds;
		if (secs <= 0) return 'Expired';
		const mins = Math.floor(secs / 60);
		const rem = secs % 60;
		return `Expires in ${mins}:${String(rem).padStart(2, '0')}`;
	});

	function resetServerDetails() {
		generation += 1;
		accounts = [];
		claude = null;
		devices = [];
		pairingCode = null;
		accountsError = null;
		claudeError = null;
		signInFailure = null;
		devicesError = null;
		clearPendingSignIn();
	}

	function clearPendingSignIn() {
		pendingSignInId = null;
		pendingSignInAccountId = null;
		signInUrl = null;
	}

	function clearPendingAttempts() {
		installAttempt = null;
		oauthAttempt = null;
		oauthHostKey = null;
		installSshPassword = '';
		sshModalPassword = '';
		sshModalOpen = false;
		revokeSelfDevice = null;
		disconnectDialogOpen = false;
	}

	function applyDisconnected(next: SyncStatusResponse) {
		status = next;
		installSeq += 1;
		installStatus = null;
		error = null;
		resetServerDetails();
		clearPendingAttempts();
	}

	async function loadAccounts() {
		const current = generation;
		try {
			const next = await listServerChatGPTAccounts();
			if (disposed || current !== generation) return;
			accounts = next;
			accountsError = null;
		} catch (cause) {
			if (!disposed && current === generation) accountsError = messageOf(cause);
		}
	}

	async function loadClaude() {
		const current = generation;
		try {
			const next = await getServerClaudeCode();
			if (disposed || current !== generation) return;
			claude = next;
			claudeError = null;
		} catch (cause) {
			if (!disposed && current === generation) claudeError = messageOf(cause);
		}
	}

	async function loadDevices() {
		const current = generation;
		try {
			const next = await listServerDevices();
			if (disposed || current !== generation) return;
			devices = next;
			devicesError = null;
		} catch (cause) {
			if (!disposed && current === generation) devicesError = messageOf(cause);
		}
	}

	async function refreshConnectedDetails() {
		await Promise.allSettled([loadAccounts(), loadClaude(), loadDevices()]);
	}

	async function refreshStatus(loadDetails = false) {
		const seq = ++statusSeq;
		try {
			const next = await getSyncStatus();
			if (disposed || seq !== statusSeq) return;
			const previous = status;
			if (previous?.enabled && !next.enabled) {
				applyDisconnected(next);
				return;
			}
			const serverChanged = next.server_url !== previous?.server_url;
			if (serverChanged) resetServerDetails();
			status = next;
			if (next.enabled && (loadDetails || serverChanged || !previous?.enabled)) {
				await refreshConnectedDetails();
			}
		} catch (cause) {
			if (!disposed) error = messageOf(cause);
		}
	}

	async function loadInstallStatus() {
		const seq = ++installSeq;
		try {
			const next = await getServerInstallStatus();
			if (!disposed && seq === installSeq) installStatus = next;
		} catch (cause) {
			if (!disposed) error = messageOf(cause);
		}
	}

	async function loadSyncStatus() {
		const seq = ++statusSeq;
		try {
			const next = await getSyncStatus();
			if (disposed || seq !== statusSeq) return;
			status = next;
			if (next.enabled) await refreshConnectedDetails();
		} catch (cause) {
			if (!disposed) error = messageOf(cause);
		}
	}

	async function refreshAll() {
		await Promise.all([loadSyncStatus(), loadInstallStatus()]);
	}

	function openSshModal(purpose: 'oauth' | 'update', user: string, port: number) {
		sshModalPurpose = purpose;
		sshModalUser = user;
		sshModalPort = String(port);
		sshModalPassword = '';
		sshModalOpen = true;
	}

	async function settleInstall(next: ServerInstallStatus) {
		if (next.state === 'running' || next.state === 'host_key_required') return;
		const attempt = installAttempt;
		installAttempt = null;
		installSshPassword = '';
		if (next.state === 'complete') {
			await refreshStatus(true);
		} else if (
			next.state === 'failed' &&
			next.error_code === 'ssh_password_required' &&
			status?.enabled
		) {
			openSshModal(
				'update',
				attempt?.ssh_user ?? status.ssh_user ?? '',
				attempt?.ssh_port ?? status.ssh_port ?? 22
			);
		}
	}

	async function pollInstall() {
		if (disposed || pollingInstall || installStatus?.state !== 'running') return;
		pollingInstall = true;
		const seq = installSeq;
		try {
			const next = await getServerInstallStatus();
			if (disposed || seq !== installSeq) return;
			installStatus = next;
			await settleInstall(next);
		} catch (cause) {
			if (!disposed && seq === installSeq) error = messageOf(cause);
		} finally {
			pollingInstall = false;
		}
	}

	async function pollSignIn() {
		if (disposed || pollingSignIn || !pendingSignInId) return;
		pollingSignIn = true;
		const current = generation;
		try {
			const result = await getServerChatGPTSignIn(pendingSignInId);
			if (disposed || current !== generation) return;
			if (result.state !== 'pending') {
				clearPendingSignIn();
				if (result.state === 'failed') {
					signInFailure = result.reason ?? 'Server ChatGPT sign-in failed.';
				}
				await loadAccounts();
			}
		} catch (cause) {
			if (disposed || current !== generation) return;
			if (cause instanceof ApiError && cause.code === 'oauth_cancelled') {
				clearPendingSignIn();
				accountsError = null;
				signInFailure = messageOf(cause);
			} else {
				accountsError = messageOf(cause);
			}
		} finally {
			pollingSignIn = false;
		}
	}

	onMount(() => {
		const lifetime = new AbortController();
		void refreshAll();
		void live.follow(
			(signal, opened) =>
				streamNotifications(
					(event) => {
						if (event.type === 'sync-status-changed') void refreshStatus(false);
					},
					signal,
					opened
				),
			() => void refreshAll(),
			lifetime.signal
		);
		const timer = setInterval(() => {
			nowMs = Date.now();
			void pollInstall();
			void pollSignIn();
		}, 500);
		return () => {
			disposed = true;
			lifetime.abort();
			clearInterval(timer);
		};
	});

	function buildInstallRequest(
		mode: 'install' | 'update',
		oneTimePassword?: string
	): ServerInstallInput {
		const endpoint = parseServerEndpoint(status?.server_url);
		const host = mode === 'update' ? endpoint.host || installHost.trim() : installHost.trim();
		const serverPort = mode === 'update' ? endpoint.port : Number(installServerPort) || 8420;
		const sshUser =
			mode === 'update'
				? sshModalUser.trim() || status?.ssh_user || installSshUser.trim()
				: installSshUser.trim();
		const sshPort =
			mode === 'update'
				? Number(sshModalPort) || status?.ssh_port || 22
				: Number(installSshPort) || 22;
		const sshPassword =
			oneTimePassword !== undefined ? oneTimePassword || null : installSshPassword || null;

		installHost = host;
		installServerPort = String(serverPort);
		installSshUser = sshUser;
		installSshPort = String(sshPort);
		return {
			host,
			server_port: serverPort,
			ssh_user: sshUser,
			ssh_port: sshPort,
			ssh_password: sshPassword,
			device_name: installDeviceName.trim() || 'Laptop',
			mode
		};
	}

	async function runInstall(request: ServerInstallInput) {
		busy = true;
		error = null;
		installSeq += 1;
		installAttempt = request;
		try {
			const started = await startServerInstall(request);
			installStatus = started;
			await settleInstall(started);
		} catch (cause) {
			installAttempt = null;
			installSshPassword = '';
			error = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function confirmInstallHostKey(challenge: HostKeyChallenge) {
		busy = true;
		error = null;
		try {
			await trustServerHost({
				host: challenge.host,
				ssh_port: challenge.ssh_port,
				fingerprint_sha256: challenge.fingerprint_sha256
			});
		} catch (cause) {
			error = messageOf(cause);
			return;
		} finally {
			busy = false;
		}
		await runInstall(installAttempt ?? buildInstallRequest(installStatus?.mode ?? 'install'));
	}

	function cancelInstallHostKey() {
		installAttempt = null;
		installSshPassword = '';
		installStatus = null;
	}

	async function submitConnect() {
		busy = true;
		error = null;
		try {
			const connected = await connectServer({
				host: connectHost.trim(),
				server_port: Number(connectServerPort) || 8420,
				pairing_code: connectAuthMode === 'code' ? connectPairingCode.trim() : null,
				token: connectAuthMode === 'token' ? connectToken.trim() : null,
				device_name: connectDeviceName.trim() || 'Laptop'
			});
			connectPairingCode = '';
			connectToken = '';
			statusSeq += 1;
			if (connected.server_url !== status?.server_url) resetServerDetails();
			status = connected;
			await refreshConnectedDetails();
		} catch (cause) {
			error = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function handleSyncNow() {
		syncBusy = true;
		error = null;
		const seq = ++statusSeq;
		try {
			const next = await syncNow();
			if (!disposed && seq === statusSeq) status = next;
		} catch (cause) {
			error = messageOf(cause);
		} finally {
			syncBusy = false;
		}
	}

	function handleUpdateServerClick() {
		if (!status?.ssh_user) {
			openSshModal('update', '', status?.ssh_port ?? 22);
			return;
		}
		sshModalUser = status.ssh_user;
		sshModalPort = String(status.ssh_port ?? 22);
		void runInstall(buildInstallRequest('update', ''));
	}

	async function disconnect() {
		busy = true;
		error = null;
		statusSeq += 1;
		try {
			const next = await disconnectServer();
			statusSeq += 1;
			applyDisconnected(next);
		} catch (cause) {
			error = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function initiateServerSignIn(attempt: OAuthAttempt) {
		busy = true;
		accountsError = null;
		signInFailure = null;
		oauthHostKey = null;
		oauthAttempt = attempt;
		const current = generation;
		try {
			const result = await startServerChatGPTSignIn({
				account_id: attempt.accountId,
				ssh_user: attempt.ssh?.ssh_user ?? null,
				ssh_port: attempt.ssh?.ssh_port ?? null,
				ssh_password: attempt.ssh?.ssh_password ?? null
			});
			if (disposed || current !== generation) return;
			if (result.state === 'started') {
				oauthAttempt = null;
				pendingSignInId = result.sign_in.id;
				pendingSignInAccountId = attempt.accountId;
				signInUrl = result.sign_in.url;
				await openExternal(result.sign_in.url);
				await refreshStatus(false);
			} else if (result.state === 'host_key_required') {
				oauthHostKey = result.host_key;
			} else {
				oauthAttempt = { accountId: attempt.accountId, ssh: null };
				openSshModal(
					'oauth',
					result.ssh_user ?? status?.ssh_user ?? '',
					result.ssh_port ?? status?.ssh_port ?? 22
				);
			}
		} catch (cause) {
			oauthAttempt = null;
			if (!disposed && current === generation) accountsError = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function confirmOAuthHostKey(challenge: HostKeyChallenge) {
		busy = true;
		accountsError = null;
		try {
			await trustServerHost({
				host: challenge.host,
				ssh_port: challenge.ssh_port,
				fingerprint_sha256: challenge.fingerprint_sha256
			});
		} catch (cause) {
			accountsError = messageOf(cause);
			return;
		} finally {
			busy = false;
		}
		await initiateServerSignIn(oauthAttempt ?? { accountId: null, ssh: null });
	}

	function cancelOAuthHostKey() {
		oauthHostKey = null;
		oauthAttempt = null;
	}

	function cancelSshModal() {
		sshModalPassword = '';
		sshModalOpen = false;
		if (sshModalPurpose === 'oauth') oauthAttempt = null;
	}

	async function submitSshModal() {
		const user = sshModalUser.trim();
		const port = Number(sshModalPort) || 22;
		const password = sshModalPassword;
		sshModalPassword = '';
		sshModalOpen = false;
		if (sshModalPurpose === 'update') {
			await runInstall(buildInstallRequest('update', password));
		} else {
			await initiateServerSignIn({
				accountId: oauthAttempt?.accountId ?? null,
				ssh: { ssh_user: user, ssh_port: port, ssh_password: password }
			});
		}
	}

	async function handleRemoveServerAccount(accountId: string) {
		busy = true;
		accountsError = null;
		try {
			await removeServerChatGPTAccount(accountId);
			if (pendingSignInAccountId === accountId) {
				pendingSignInId = null;
				pendingSignInAccountId = null;
				signInUrl = null;
			}
			await loadAccounts();
		} catch (cause) {
			accountsError = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function generatePairingCode() {
		busy = true;
		devicesError = null;
		const current = generation;
		try {
			const next = await createServerPairingCode();
			if (disposed || current !== generation) return;
			pairingCode = next;
			nowMs = Date.now();
		} catch (cause) {
			if (!disposed && current === generation) devicesError = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function handleRevokeDevice(device: Device) {
		if (device.id === status?.server_device_id) {
			revokeSelfDevice = device;
			return;
		}
		busy = true;
		devicesError = null;
		try {
			await revokeServerDevice(device.id);
			await loadDevices();
		} catch (cause) {
			devicesError = messageOf(cause);
		} finally {
			busy = false;
		}
	}

	async function copyText(value: string, field: 'url' | 'code') {
		try {
			await navigator.clipboard.writeText(value);
			copiedField = field;
			setTimeout(() => {
				if (copiedField === field) copiedField = null;
			}, 1500);
		} catch {
			// Clipboard write may be unavailable in restricted contexts.
		}
	}
</script>

<div class="mt-6 space-y-6">
	{#if !status?.enabled}
		<div class="flex flex-wrap gap-2" role="group" aria-label="Server setup mode">
			<Button
				variant={setupMode === 'install' ? 'secondary' : 'outline'}
				size="sm"
				aria-pressed={setupMode === 'install'}
				onclick={() => {
					setupMode = 'install';
					error = null;
				}}
			>
				Install on a server (SSH)
			</Button>
			<Button
				variant={setupMode === 'connect' ? 'secondary' : 'outline'}
				size="sm"
				aria-pressed={setupMode === 'connect'}
				onclick={() => {
					setupMode = 'connect';
					error = null;
				}}
			>
				Connect to existing server
			</Button>
		</div>

		{#if setupMode === 'install'}
			<section aria-label="Install on a server" class="space-y-4 rounded-xl border bg-card p-4">
				<div>
					<h3 class="text-sm font-medium">Install Verstehen Server over SSH</h3>
					<p class="mt-1 text-xs text-muted-foreground">
						Deploys the Verstehen server bundle to your Linux host on Tailscale, enables a systemd
						user service, and pairs this laptop automatically.
					</p>
				</div>

				<div class="grid gap-4 sm:grid-cols-2">
					<div class="space-y-1.5">
						<label for="install-host" class="block text-sm">Tailscale IP or host</label>
						<input
							id="install-host"
							class={`${inputClass} w-full`}
							placeholder="100.64.0.10"
							bind:value={installHost}
							disabled={busy || installStatus?.state === 'running'}
						/>
					</div>
					<div class="space-y-1.5">
						<label for="install-server-port" class="block text-sm">Server port</label>
						<input
							id="install-server-port"
							type="number"
							min="1"
							max="65535"
							class={`${inputClass} w-full`}
							bind:value={installServerPort}
							disabled={busy || installStatus?.state === 'running'}
						/>
					</div>
					<div class="space-y-1.5">
						<label for="install-ssh-user" class="block text-sm">SSH username</label>
						<input
							id="install-ssh-user"
							class={`${inputClass} w-full`}
							placeholder="ubuntu"
							bind:value={installSshUser}
							disabled={busy || installStatus?.state === 'running'}
						/>
					</div>
					<div class="space-y-1.5">
						<label for="install-ssh-port" class="block text-sm">SSH port</label>
						<input
							id="install-ssh-port"
							type="number"
							min="1"
							max="65535"
							class={`${inputClass} w-full`}
							bind:value={installSshPort}
							disabled={busy || installStatus?.state === 'running'}
						/>
					</div>
					<div class="space-y-1.5">
						<label for="install-ssh-password" class="block text-sm">
							SSH password (optional)
						</label>
						<input
							id="install-ssh-password"
							type="password"
							autocomplete="off"
							placeholder="Leave blank for SSH keys / agent"
							class={`${inputClass} w-full`}
							bind:value={installSshPassword}
							disabled={busy || installStatus?.state === 'running'}
						/>
						<p class="text-xs text-muted-foreground">
							Leave blank to use ~/.ssh keys or ssh-agent. Used once in memory, never saved.
						</p>
					</div>
					<div class="space-y-1.5">
						<label for="install-device-name" class="block text-sm">Laptop device name</label>
						<input
							id="install-device-name"
							class={`${inputClass} w-full`}
							placeholder="Laptop"
							bind:value={installDeviceName}
							disabled={busy || installStatus?.state === 'running'}
						/>
					</div>
				</div>

				<div class="flex items-center gap-3">
					<Button
						size="sm"
						disabled={busy ||
							installStatus?.state === 'running' ||
							!installHost.trim() ||
							!installSshUser.trim()}
						onclick={() => void runInstall(buildInstallRequest('install'))}
					>
						{installStatus?.state === 'running' ? 'Installing…' : 'Install server'}
					</Button>
				</div>

				{#if installStatus?.state === 'host_key_required' && installStatus.host_key}
					{@const challenge = installStatus.host_key}
					<div
						role="region"
						aria-label="Confirm SSH host key"
						class="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4"
					>
						<h4 class="text-sm font-medium">Confirm SSH host key</h4>
						<p class="text-xs text-muted-foreground">
							Host <span class="font-mono text-foreground">
								{challenge.host}:{challenge.ssh_port}
							</span>
							is not in your <code>~/.ssh/known_hosts</code> file. Verify its fingerprint before continuing:
						</p>
						<div class="rounded-md border bg-background p-3 font-mono text-xs">
							<div>Type: <code>{challenge.key_type}</code></div>
							<div class="mt-1 break-all">
								Fingerprint: <code>{challenge.fingerprint_sha256}</code>
							</div>
						</div>
						<div class="flex gap-2">
							<Button
								size="sm"
								disabled={busy}
								onclick={() => void confirmInstallHostKey(challenge)}
							>
								Trust host & continue
							</Button>
							<Button variant="ghost" size="sm" disabled={busy} onclick={cancelInstallHostKey}>
								Cancel
							</Button>
						</div>
					</div>
				{/if}

				{#if installStatus?.steps && installStatus.steps.length > 0}
					<div aria-label="Install progress" class="space-y-2 border-t pt-4">
						<h4 class="text-xs font-medium tracking-wider text-muted-foreground uppercase">
							Install steps
						</h4>
						<ul class="space-y-2 text-sm">
							{#each installStatus.steps as step (step.id)}
								<li class="rounded-md border bg-background/60 px-3 py-2">
									<div class="flex items-center justify-between gap-2">
										<span class="font-medium">{step.label}</span>
										<span
											class={`text-xs ${
												step.status === 'done'
													? 'text-emerald-500'
													: step.status === 'warning'
														? 'text-amber-500'
														: step.status === 'failed'
															? 'text-destructive'
															: step.status === 'running'
																? 'text-primary'
																: 'text-muted-foreground'
											}`}
										>
											{stepStatusLabels[step.status] ?? step.status}
										</span>
									</div>
									{#if step.detail}
										<p class="mt-1 text-xs break-words text-muted-foreground">{step.detail}</p>
									{/if}
								</li>
							{/each}
						</ul>

						{#if installStatus.error}
							<p role="alert" class="text-sm text-destructive">{installStatus.error}</p>
						{/if}

						{#if installStatus.logs && installStatus.logs.length > 0}
							<details class="rounded-md border bg-background p-3 text-xs">
								<summary class="cursor-pointer font-medium text-muted-foreground">
									Install logs ({installStatus.logs.length})
								</summary>
								<pre
									class="mt-2 max-h-48 overflow-auto font-mono whitespace-pre-wrap text-muted-foreground">{installStatus.logs.join(
										'\n'
									)}</pre>
							</details>
						{/if}
					</div>
				{/if}
			</section>
		{:else}
			<section
				aria-label="Connect to existing server"
				class="space-y-4 rounded-xl border bg-card p-4"
			>
				<div>
					<h3 class="text-sm font-medium">Connect to an existing Verstehen Server</h3>
					<p class="mt-1 text-xs text-muted-foreground">
						Pair with a running server on your Tailscale network using a short pairing code or a
						minted bearer token.
					</p>
				</div>

				<div class="grid gap-4 sm:grid-cols-2">
					<div class="space-y-1.5">
						<label for="connect-host" class="block text-sm">Tailscale IP or host</label>
						<input
							id="connect-host"
							class={`${inputClass} w-full`}
							placeholder="100.64.0.10"
							bind:value={connectHost}
							disabled={busy}
						/>
					</div>
					<div class="space-y-1.5">
						<label for="connect-server-port" class="block text-sm">Server port</label>
						<input
							id="connect-server-port"
							type="number"
							min="1"
							max="65535"
							class={`${inputClass} w-full`}
							bind:value={connectServerPort}
							disabled={busy}
						/>
					</div>
				</div>

				<div class="flex gap-2" role="group" aria-label="Authentication method">
					<Button
						variant={connectAuthMode === 'code' ? 'secondary' : 'outline'}
						size="sm"
						aria-pressed={connectAuthMode === 'code'}
						onclick={() => (connectAuthMode = 'code')}
					>
						Pairing code
					</Button>
					<Button
						variant={connectAuthMode === 'token' ? 'secondary' : 'outline'}
						size="sm"
						aria-pressed={connectAuthMode === 'token'}
						onclick={() => (connectAuthMode = 'token')}
					>
						Bearer token
					</Button>
				</div>

				<div class="grid gap-4 sm:grid-cols-2">
					{#if connectAuthMode === 'code'}
						<div class="space-y-1.5">
							<label for="connect-pairing-code" class="block text-sm">Pairing code</label>
							<input
								id="connect-pairing-code"
								class={`${inputClass} w-full font-mono uppercase`}
								placeholder="ABCD-EFGH"
								bind:value={connectPairingCode}
								disabled={busy}
							/>
						</div>
					{:else}
						<div class="space-y-1.5">
							<label for="connect-token" class="block text-sm">Bearer token</label>
							<input
								id="connect-token"
								type="password"
								autocomplete="off"
								class={`${inputClass} w-full font-mono`}
								placeholder="Device bearer token"
								bind:value={connectToken}
								disabled={busy}
							/>
						</div>
					{/if}
					<div class="space-y-1.5">
						<label for="connect-device-name" class="block text-sm">Laptop device name</label>
						<input
							id="connect-device-name"
							class={`${inputClass} w-full`}
							placeholder="Laptop"
							bind:value={connectDeviceName}
							disabled={busy}
						/>
					</div>
				</div>

				<Button
					size="sm"
					disabled={busy ||
						!connectHost.trim() ||
						(connectAuthMode === 'code' ? !connectPairingCode.trim() : !connectToken.trim())}
					onclick={() => void submitConnect()}
				>
					Connect server
				</Button>
			</section>
		{/if}
	{:else}
		<section aria-label="Sync status" class="space-y-4 rounded-xl border bg-card p-4">
			<div class="flex flex-wrap items-start justify-between gap-4">
				<div>
					<div class="flex items-center gap-2">
						<span
							class={`size-2.5 rounded-full ${syncDotClasses[status.status]}`}
							aria-hidden="true"
						></span>
						<h3 class="text-sm font-medium">{syncStatusLabels[status.status]}</h3>
					</div>
					<p class="mt-1 font-mono text-xs text-muted-foreground">{status.server_url}</p>
				</div>
				<div class="flex flex-wrap gap-2">
					<Button
						variant="outline"
						size="sm"
						disabled={syncBusy || busy || status.status === 'syncing'}
						onclick={() => void handleSyncNow()}
					>
						{status.status === 'syncing' || syncBusy ? 'Syncing…' : 'Sync now'}
					</Button>
					<Button
						variant={status.status === 'update_required' ? 'default' : 'outline'}
						size="sm"
						disabled={busy || installStatus?.state === 'running'}
						onclick={handleUpdateServerClick}
					>
						{installStatus?.state === 'running' ? 'Updating…' : 'Update server'}
					</Button>
					<Button
						variant="ghost"
						size="sm"
						disabled={busy}
						onclick={() => (disconnectDialogOpen = true)}
					>
						Disconnect
					</Button>
				</div>
			</div>

			{#if status.device_identity_missing}
				<p role="status" class="text-xs text-muted-foreground">
					This server can't identify this laptop; update the server to enable self-revoke on
					disconnect.
				</p>
			{/if}

			<div class="grid gap-3 border-t pt-3 text-xs text-muted-foreground sm:grid-cols-3">
				<div>
					<span class="block text-foreground">Pending changes</span>
					<span>{status.pending_changes}</span>
				</div>
				<div>
					<span class="block text-foreground">Last synced</span>
					<span>
						{status.last_sync_at ? new Date(status.last_sync_at).toLocaleString() : 'Never'}
					</span>
				</div>
				<div>
					<span class="block text-foreground">SSH target</span>
					<span>
						{status.ssh_user ? `${status.ssh_user} · port ${status.ssh_port ?? 22}` : 'Not set'}
					</span>
				</div>
			</div>

			{#if status.last_error}
				<p
					role="alert"
					class="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive"
				>
					{status.last_error}
				</p>
			{/if}

			{#if installStatus?.state === 'host_key_required' && installStatus.host_key}
				{@const challenge = installStatus.host_key}
				<div
					role="region"
					aria-label="Confirm SSH host key"
					class="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4"
				>
					<h4 class="text-sm font-medium">Confirm SSH host key</h4>
					<p class="text-xs text-muted-foreground">
						Host <span class="font-mono text-foreground">
							{challenge.host}:{challenge.ssh_port}
						</span>
						is not in your <code>~/.ssh/known_hosts</code> file.
					</p>
					<div class="rounded-md border bg-background p-3 font-mono text-xs">
						<div>Type: {challenge.key_type}</div>
						<div class="mt-1 break-all">Fingerprint: {challenge.fingerprint_sha256}</div>
					</div>
					<div class="flex gap-2">
						<Button size="sm" disabled={busy} onclick={() => void confirmInstallHostKey(challenge)}>
							Trust host & continue
						</Button>
						<Button variant="ghost" size="sm" disabled={busy} onclick={cancelInstallHostKey}>
							Cancel
						</Button>
					</div>
				</div>
			{/if}

			{#if installStatus && installStatus.mode === 'update' && installStatus.steps && installStatus.steps.length > 0}
				<div aria-label="Update progress" class="space-y-2 border-t pt-3">
					<h4 class="text-xs font-medium tracking-wider text-muted-foreground uppercase">
						Server update progress
					</h4>
					<ul class="space-y-1.5 text-xs">
						{#each installStatus.steps as step (step.id)}
							<li
								class="flex items-center justify-between rounded border bg-background/60 px-2.5 py-1.5"
							>
								<span>{step.label}</span>
								<span class="text-muted-foreground">
									{stepStatusLabels[step.status] ?? step.status}
								</span>
							</li>
						{/each}
					</ul>
					{#if installStatus.error}
						<p role="alert" class="text-xs text-destructive">{installStatus.error}</p>
					{/if}
				</div>
			{/if}
		</section>

		<section aria-label="Server accounts" class="space-y-4 rounded-xl border bg-card p-4">
			<div>
				<h3 class="text-sm font-medium">Server Accounts</h3>
				<p class="mt-1 text-xs text-muted-foreground">
					Manage AI provider credentials on the remote server so your Android device can run lessons
					directly.
				</p>
			</div>

			<div class="space-y-3 border-t pt-3">
				<div class="flex items-center justify-between">
					<h4 class="text-sm font-medium">ChatGPT</h4>
					<Button
						variant="outline"
						size="sm"
						disabled={busy || !!pendingSignInId}
						onclick={() => void initiateServerSignIn({ accountId: null, ssh: null })}
					>
						Add account
					</Button>
				</div>

				{#each accounts as account (account.id)}
					<div class="rounded-lg border bg-background/50 p-3">
						<div class="flex items-start justify-between gap-4">
							<div>
								<p class="text-sm font-medium">{account.label}</p>
								<p class="mt-0.5 text-xs text-muted-foreground">
									{accountStateLabels[account.state ?? 'ready'] ?? account.state}
								</p>
							</div>
							<div class="flex gap-2">
								<Button
									variant="ghost"
									size="sm"
									disabled={busy || !!pendingSignInId}
									onclick={() => void initiateServerSignIn({ accountId: account.id, ssh: null })}
								>
									Sign in again
								</Button>
								<Button
									variant="ghost"
									size="sm"
									disabled={busy}
									onclick={() => void handleRemoveServerAccount(account.id)}
								>
									Remove
								</Button>
							</div>
						</div>
						{#if account.reason}
							<p class="mt-1.5 text-xs text-muted-foreground">{account.reason}</p>
						{/if}
					</div>
				{/each}

				{#if !accounts.length}
					<p class="text-sm text-muted-foreground">No ChatGPT accounts connected on server.</p>
				{/if}

				{#if pendingSignInId}
					<div role="status" class="flex items-center gap-2 text-sm text-muted-foreground">
						<span>Waiting for server browser sign-in via SSH tunnel…</span>
						<Button
							variant="link"
							size="sm"
							onclick={() => signInUrl && void openExternal(signInUrl)}
						>
							Open sign-in page
						</Button>
					</div>
				{/if}

				{#if oauthHostKey}
					{@const challenge = oauthHostKey}
					<div
						role="region"
						aria-label="Confirm SSH host key"
						class="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4"
					>
						<h4 class="text-sm font-medium">Confirm SSH host key for OAuth tunnel</h4>
						<div class="rounded-md border bg-background p-3 font-mono text-xs">
							<div>Host: {challenge.host}:{challenge.ssh_port}</div>
							<div>Type: {challenge.key_type}</div>
							<div class="mt-1 break-all">Fingerprint: {challenge.fingerprint_sha256}</div>
						</div>
						<div class="flex gap-2">
							<Button size="sm" disabled={busy} onclick={() => void confirmOAuthHostKey(challenge)}>
								Trust host & continue
							</Button>
							<Button variant="ghost" size="sm" disabled={busy} onclick={cancelOAuthHostKey}>
								Cancel
							</Button>
						</div>
					</div>
				{/if}
			</div>

			<div class="space-y-2 border-t pt-3">
				<h4 class="text-sm font-medium">Claude Code</h4>
				{#if claudeError}
					<p role="alert" class="text-xs text-destructive">{claudeError}</p>
				{/if}
				{#if claude}
					<div class="rounded-lg border bg-background/50 p-3">
						<div class="flex justify-between text-sm">
							<span>{accountStateLabels[claude.state] ?? claude.state}</span>
							<span class="text-muted-foreground">
								{claude.version ? `Version ${claude.version}` : 'No version detected'}
							</span>
						</div>
						{#if claude.reason}
							<p class="mt-1.5 text-xs text-muted-foreground">{claude.reason}</p>
						{/if}
						<p class="mt-1.5 text-xs text-muted-foreground">
							Claude Code is installed and signed in separately on the server over SSH.
						</p>
					</div>
				{/if}
			</div>

			{#if signInFailure}
				<p role="alert" class="text-xs text-destructive">{signInFailure}</p>
			{/if}
			{#if accountsError}
				<p role="alert" class="text-xs text-destructive">{accountsError}</p>
			{/if}
		</section>

		<section aria-label="Paired devices" class="space-y-4 rounded-xl border bg-card p-4">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div>
					<h3 class="text-sm font-medium">Paired Devices</h3>
					<p class="mt-1 text-xs text-muted-foreground">
						Mint a one-time 8-character code to pair your Android phone over Tailscale, or revoke
						existing device tokens.
					</p>
				</div>
				<Button
					variant="outline"
					size="sm"
					disabled={busy}
					onclick={() => void generatePairingCode()}
				>
					Pair Android device
				</Button>
			</div>

			{#if pairingCode}
				<div
					role="region"
					aria-label="Android pairing code"
					class="space-y-3 rounded-lg border bg-background p-4"
				>
					<div class="flex flex-wrap items-center justify-between gap-2">
						<span class="text-xs font-medium tracking-wider text-muted-foreground uppercase">
							One-time pairing code
						</span>
						<span class="text-xs text-muted-foreground" data-testid="pairing-countdown">
							{pairingCountdownLabel}
						</span>
					</div>
					<div class="flex flex-wrap items-center justify-between gap-3">
						<div>
							<p class="text-xs text-muted-foreground">Server URL</p>
							<code class="text-sm font-medium">{status.server_url}</code>
						</div>
						<Button
							variant="outline"
							size="sm"
							onclick={() => status?.server_url && void copyText(status.server_url, 'url')}
						>
							{copiedField === 'url' ? 'Copied URL' : 'Copy URL'}
						</Button>
					</div>
					<div class="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
						<div>
							<p class="text-xs text-muted-foreground">8-character code</p>
							<code class="text-lg font-semibold tracking-widest" data-testid="pairing-code-value">
								{formatPairingCode(pairingCode.code)}
							</code>
						</div>
						<Button
							variant="outline"
							size="sm"
							onclick={() =>
								pairingCode && void copyText(formatPairingCode(pairingCode.code), 'code')}
						>
							{copiedField === 'code' ? 'Copied code' : 'Copy code'}
						</Button>
					</div>
				</div>
			{/if}

			<div class="space-y-2 border-t pt-3">
				{#each devices as device (device.id)}
					<div
						class="flex items-center justify-between gap-4 rounded-lg border bg-background/50 p-3"
					>
						<div class="min-w-0">
							<div class="flex items-center gap-2">
								<span class="truncate text-sm font-medium">{device.name}</span>
								{#if device.id === status.server_device_id}
									<span
										class="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground"
										data-testid="this-laptop-badge"
									>
										This laptop
									</span>
								{/if}
								{#if device.revoked_at}
									<span
										class="rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive"
									>
										Revoked
									</span>
								{/if}
							</div>
							<p class="mt-0.5 text-xs text-muted-foreground">
								Added {new Date(device.created_at).toLocaleDateString()}
								{#if device.last_seen_at}
									· Last seen {new Date(device.last_seen_at).toLocaleString()}
								{/if}
							</p>
						</div>
						{#if !device.revoked_at}
							<Button
								variant="ghost"
								size="sm"
								disabled={busy}
								aria-label={`Revoke ${device.name}`}
								onclick={() => void handleRevokeDevice(device)}
							>
								Revoke
							</Button>
						{/if}
					</div>
				{/each}
				{#if !devices.length}
					<p class="text-sm text-muted-foreground">No paired devices found.</p>
				{/if}
			</div>

			{#if devicesError}
				<p role="alert" class="text-xs text-destructive">{devicesError}</p>
			{/if}
		</section>
	{/if}

	{#if error}
		<p role="alert" class="text-sm text-destructive">{error}</p>
	{/if}
</div>

{#if sshModalOpen}
	<Dialog.Root
		open
		onOpenChange={(open) => {
			if (!open) cancelSshModal();
		}}
	>
		<Dialog.Content class="sm:max-w-md" aria-label="SSH authentication required">
			<Dialog.Header>
				<Dialog.Title class="text-sm">SSH authentication required</Dialog.Title>
				<Dialog.Description class="text-xs text-muted-foreground">
					Enter your one-time SSH credentials for the server. The password is used only in memory
					and is never stored on disk.
				</Dialog.Description>
			</Dialog.Header>
			<div class="space-y-3">
				<div class="space-y-1">
					<label for="modal-ssh-user" class="block text-xs">SSH username</label>
					<input id="modal-ssh-user" class={`${inputClass} w-full`} bind:value={sshModalUser} />
				</div>
				<div class="space-y-1">
					<label for="modal-ssh-port" class="block text-xs">SSH port</label>
					<input
						id="modal-ssh-port"
						type="number"
						min="1"
						max="65535"
						class={`${inputClass} w-full`}
						bind:value={sshModalPort}
					/>
				</div>
				<div class="space-y-1">
					<label for="modal-ssh-password" class="block text-xs">SSH password</label>
					<input
						id="modal-ssh-password"
						type="password"
						autocomplete="off"
						class={`${inputClass} w-full`}
						bind:value={sshModalPassword}
						onkeydown={(e) => {
							if (e.key === 'Enter' && sshModalUser.trim()) {
								e.preventDefault();
								void submitSshModal();
							}
						}}
					/>
				</div>
			</div>
			<Dialog.Footer>
				<Button variant="ghost" size="sm" onclick={cancelSshModal}>Cancel</Button>
				<Button size="sm" disabled={!sshModalUser.trim()} onclick={() => void submitSshModal()}>
					Continue
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}

{#if disconnectDialogOpen}
	<Dialog.Root
		open
		onOpenChange={(open) => {
			if (!open && !busy) disconnectDialogOpen = false;
		}}
	>
		<Dialog.Content class="sm:max-w-md" aria-label="Disconnect sync server">
			<Dialog.Header>
				<Dialog.Title class="text-sm text-destructive">Disconnect sync server?</Dialog.Title>
				<Dialog.Description class="text-xs text-muted-foreground">
					This stops background sync, revokes this laptop's device token on the server, and clears
					the local server connection. All of your sessions, messages, and knowledge graph remain
					intact on this laptop.
				</Dialog.Description>
			</Dialog.Header>
			<Dialog.Footer>
				<Button
					variant="ghost"
					size="sm"
					disabled={busy}
					onclick={() => (disconnectDialogOpen = false)}
				>
					Cancel
				</Button>
				<Button variant="destructive" size="sm" disabled={busy} onclick={() => void disconnect()}>
					Disconnect server
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}

{#if revokeSelfDevice}
	<Dialog.Root
		open
		onOpenChange={(open) => {
			if (!open && !busy) revokeSelfDevice = null;
		}}
	>
		<Dialog.Content class="sm:max-w-md" aria-label="Revoke this laptop">
			<Dialog.Header>
				<Dialog.Title class="text-sm text-destructive">Revoke this laptop?</Dialog.Title>
				<Dialog.Description class="text-xs text-muted-foreground">
					Revoking <strong>{revokeSelfDevice.name}</strong> disconnects this laptop: sync stops, its token
					is revoked on the server, and the connection is cleared. Local sessions and graph stay intact.
				</Dialog.Description>
			</Dialog.Header>
			<Dialog.Footer>
				<Button variant="ghost" size="sm" disabled={busy} onclick={() => (revokeSelfDevice = null)}>
					Cancel
				</Button>
				<Button variant="destructive" size="sm" disabled={busy} onclick={() => void disconnect()}>
					Revoke and disconnect
				</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
{/if}
