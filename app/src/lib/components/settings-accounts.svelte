<script lang="ts">
	import { onMount } from 'svelte';
	import { Switch } from 'bits-ui';
	import { Button } from '#lib/components/ui/button/index.js';
	import {
		getSettings,
		saveSettings,
		listChatGPTAccounts,
		startChatGPTSignIn,
		getSignIn,
		removeChatGPTAccount,
		getClaudeCode,
		openExternal,
		type Account,
		type BinaryStatus,
		type Settings
	} from '#lib/api/client.js';
	let accounts = $state<Account[]>([]);
	let claude = $state<BinaryStatus>();
	let settings = $state<Settings>();
	let error = $state<string | null>(null);
	let pending = $state<string | null>(null);
	let signInUrl = $state<string | null>(null);
	let busy = $state(false);
	let disposed = false;
	let polling = false;
	const INSTALL_URL = 'https://code.claude.com/docs/en/setup';
	const stateLabels: Record<string, string> = {
		ready: 'Connected',
		needs_sign_in: 'Needs sign-in',
		unavailable: 'Unavailable',
		not_installed: 'Not installed',
		too_old: 'Too old',
		untested: 'Untested',
		tested: 'Tested'
	};
	async function refresh() {
		try {
			const values = await Promise.all([listChatGPTAccounts(), getClaudeCode(), getSettings()]);
			if (disposed) return;
			[accounts, claude, settings] = values;
		} catch (cause) {
			if (!disposed) error = cause instanceof Error ? cause.message : String(cause);
		}
	}
	async function poll() {
		if (polling || disposed) return;
		polling = true;
		try {
			if (pending) {
				const result = await getSignIn(pending);
				if (result.state !== 'pending') {
					pending = null;
					signInUrl = null;
					if (result.state === 'failed') error = result.reason ?? 'Sign-in failed.';
					await refresh();
				}
			}
		} catch (cause) {
			if (!disposed) error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			polling = false;
		}
	}
	onMount(() => {
		void refresh();
		const timer = setInterval(() => void poll(), 1000);
		return () => {
			disposed = true;
			clearInterval(timer);
		};
	});
	async function signIn(account?: string) {
		busy = true;
		error = null;
		try {
			const started = await startChatGPTSignIn(account);
			pending = started.id;
			signInUrl = started.url;
			await openExternal(started.url);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}
	async function remove(account: string) {
		busy = true;
		error = null;
		try {
			await removeChatGPTAccount(account);
			pending = null;
			signInUrl = null;
			await refresh();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}
	async function background(provider: 'chatgpt' | 'claude_code', checked: boolean) {
		if (busy || !settings) return;
		const previous = settings;
		settings = {
			...settings,
			background: {
				chatgpt: settings.background?.chatgpt ?? true,
				claude_code: settings.background?.claude_code ?? true,
				[provider]: checked
			}
		};
		busy = true;
		try {
			const current = await getSettings();
			settings = await saveSettings({
				...current,
				background: {
					chatgpt: current.background?.chatgpt ?? true,
					claude_code: current.background?.claude_code ?? true,
					[provider]: checked
				}
			});
			error = null;
		} catch (cause) {
			settings = previous;
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}
</script>

<div class="mt-6 space-y-8">
	<section class="space-y-4" aria-label="ChatGPT accounts">
		<div class="flex items-center justify-between">
			<h3 class="font-medium">ChatGPT</h3>
			<Button
				variant="outline"
				size="sm"
				disabled={busy || !!pending}
				onclick={() => void signIn()}
			>
				Add account
			</Button>
		</div>
		{#each accounts as account (account.id)}
			<div class="rounded-lg border p-4">
				<div class="flex items-start justify-between gap-4">
					<div>
						<p class="text-sm font-medium">{account.label}</p>
						<p class="mt-1 text-xs text-muted-foreground">
							{stateLabels[account.state ?? 'ready'] ?? account.state}
						</p>
					</div>
					<div class="flex gap-2">
						<Button
							variant="ghost"
							size="sm"
							disabled={busy || !!pending}
							onclick={() => void signIn(account.id)}
						>
							Sign in again
						</Button><Button
							variant="ghost"
							size="sm"
							disabled={busy}
							onclick={() => void remove(account.id)}
						>
							Remove
						</Button>
					</div>
				</div>
				{#if account.reason}<p class="mt-2 text-xs text-muted-foreground">{account.reason}</p>{/if}
			</div>
		{/each}
		{#if !accounts.length}<p class="text-sm text-muted-foreground">
				No ChatGPT accounts connected.
			</p>{/if}
		{#if pending}<div role="status" class="text-sm text-muted-foreground">
				Waiting for browser sign-in… <Button
					variant="link"
					size="sm"
					onclick={() => signInUrl && void openExternal(signInUrl)}
				>
					Open sign-in page
				</Button>
			</div>{/if}
		{#if settings}<div class="flex items-center justify-between text-sm">
				<span id="chatgpt-background">Allow background use</span><Switch.Root
					aria-labelledby="chatgpt-background"
					checked={settings.background?.chatgpt ?? true}
					disabled={busy}
					onCheckedChange={(value) => void background('chatgpt', value)}
					class="h-5 w-9 rounded-full bg-muted p-0.5 data-[state=checked]:bg-primary"
				>
					<Switch.Thumb
						class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
					/>
				</Switch.Root>
			</div>{/if}
	</section>
	<section class="space-y-4 border-t pt-6" aria-label="Claude Code account">
		<h3 class="font-medium">Claude Code</h3>
		{#if claude}<div class="rounded-lg border p-4">
				<div class="flex justify-between text-sm">
					<span>{stateLabels[claude.state]}</span><span class="text-muted-foreground">
						{claude.version ? `Version ${claude.version}` : 'No version detected'}
					</span>
				</div>
				{#if claude.reason}<p class="mt-2 text-xs leading-5 text-muted-foreground">
						{claude.reason}
					</p>{/if}
				<p class="mt-2 text-xs text-muted-foreground">
					Uses your Claude Code login. Run claude to sign in.
				</p>
			</div>
			{#if claude.state === 'not_installed' || claude.state === 'too_old'}<Button
					variant="outline"
					size="sm"
					onclick={() => void openExternal(INSTALL_URL)}
				>
					Install Claude Code
				</Button>{/if}{/if}
		{#if settings}<div class="flex items-center justify-between text-sm">
				<span id="claude-background">Allow background use</span><Switch.Root
					aria-labelledby="claude-background"
					checked={settings.background?.claude_code ?? true}
					disabled={busy}
					onCheckedChange={(value) => void background('claude_code', value)}
					class="h-5 w-9 rounded-full bg-muted p-0.5 data-[state=checked]:bg-primary"
				>
					<Switch.Thumb
						class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
					/>
				</Switch.Root>
			</div>{/if}
	</section>
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>{/if}
</div>
