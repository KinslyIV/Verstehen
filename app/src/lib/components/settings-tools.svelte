<script lang="ts">
	import { onMount } from 'svelte';
	import { Switch } from 'bits-ui';
	import { Button } from '#lib/components/ui/button/index.js';
	import {
		getSettings,
		openExternal,
		onLinkRefused,
		saveSettings,
		getDemoBrowser,
		health,
		browserDownload,
		getSearchKeys,
		setSearchKey,
		type Settings,
		type DemoBrowser,
		type BrowserDownloadProgress,
		type SearchKeysStatus,
		type SearchEngine
	} from '#lib/api/client.js';
	import { concurrencyError, parseConcurrency } from '#lib/settings/tools.js';
	import { onReconnect } from './settings-reconnect.js';

	const tools = ['research', 'demo', 'visual', 'pdf'] as const;
	const engines = [
		{ id: 'tavily', label: 'Tavily', docs: 'https://app.tavily.com/' },
		{ id: 'brave', label: 'Brave Search', docs: 'https://brave.com/search/api/' }
	] as const;
	const inputClass = 'h-9 min-w-0 rounded-md border bg-background px-3 text-sm disabled:opacity-50';
	let settings = $state<Settings>();
	let desktop = $state(false);
	let browser = $state<DemoBrowser>();
	let download = $state<BrowserDownloadProgress>();
	let keys = $state<SearchKeysStatus>();
	let drafts = $state({ tavily: '', brave: '' });
	let concurrency = $state('');
	let browserPath = $state('');
	let fieldError = $state<string | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let disposed = false;
	let polling = false;
	const missingKey = $derived(
		settings?.search_engine !== 'native' &&
			settings?.search_engine &&
			keys &&
			!keys[settings.search_engine].present
	);
	const effectiveLabel = $derived(
		keys?.effective_engine
			? { native: 'Native', tavily: 'Tavily', brave: 'Brave Search' }[keys.effective_engine]
			: 'no search engine'
	);

	async function refresh() {
		desktop = (await health()).desktop === true;
		const values = await Promise.all([
			getSettings(),
			getSearchKeys(),
			desktop ? undefined : getDemoBrowser(),
			desktop ? undefined : browserDownload()
		]);
		if (disposed) return;
		[settings, keys, browser, download] = values;
		concurrency = String(settings.worker_request_concurrency ?? '');
		browserPath = settings.demo_browser ?? '';
	}
	function failure(cause: unknown) {
		if (!disposed) error = cause instanceof Error ? cause.message : String(cause);
	}
	async function poll() {
		if (disposed || polling || download?.state !== 'downloading') return;
		polling = true;
		try {
			const progress = await browserDownload();
			if (disposed) return;
			download = progress;
			if (progress.state === 'complete') browser = await getDemoBrowser();
		} catch (cause) {
			failure(cause);
		} finally {
			polling = false;
		}
	}
	onMount(() => {
		void refresh().catch(failure);
		const timer = setInterval(() => void poll(), 1000);
		const stopReconnect = onReconnect(() => {
			if (settings) return;
			error = null;
			void refresh().catch(failure);
		});
		const stopRefused = onLinkRefused((url) =>
			failure(new Error(`Verstehen can't open ${url}. Open it in your browser.`))
		);
		return () => {
			disposed = true;
			clearInterval(timer);
			stopReconnect();
			stopRefused();
		};
	});
	async function save(update: (current: Settings) => Settings): Promise<boolean> {
		if (busy || !settings) return false;
		busy = true;
		error = null;
		try {
			settings = await saveSettings(update(await getSettings()));
			[keys, browser] = await Promise.all([
				getSearchKeys(),
				desktop ? undefined : getDemoBrowser()
			]);
			return true;
		} catch (cause) {
			failure(cause);
			return false;
		} finally {
			busy = false;
		}
	}
	async function commitConcurrency(input: HTMLInputElement) {
		const value = input.validity.badInput ? undefined : parseConcurrency(input.value);
		fieldError = value === undefined ? concurrencyError : null;
		if (value === undefined || value === (settings?.worker_request_concurrency ?? null)) return;
		if (await save((current) => ({ ...current, worker_request_concurrency: value })))
			concurrency = String(value ?? '');
	}
	async function commitBrowser() {
		const value = browserPath.trim() || null;
		if (value === (settings?.demo_browser ?? null)) return;
		if (await save((current) => ({ ...current, demo_browser: value }))) browserPath = value ?? '';
	}
	async function keyAction(engine: SearchEngine, clear = false) {
		if (busy) return;
		busy = true;
		error = null;
		try {
			keys = await setSearchKey(engine, clear ? null : drafts[engine]);
			drafts[engine] = '';
		} catch (cause) {
			failure(cause);
		} finally {
			busy = false;
		}
	}
	async function startDownload() {
		busy = true;
		error = null;
		try {
			download = await browserDownload(true);
		} catch (cause) {
			failure(cause);
		} finally {
			busy = false;
		}
	}
</script>

<div class="mt-6 space-y-6">
	<section aria-label="Background tools" class="space-y-4 rounded-xl border bg-card p-4">
		<h3 class="text-sm font-medium">Background tools</h3>
		{#each tools as tool (tool)}
			<div class="flex items-center justify-between gap-4 text-sm">
				<span>Tool · {tool}</span>
				<Switch.Root
					aria-label={`tool ${tool}`}
					checked={settings?.tools?.[tool] ?? true}
					disabled={busy || !settings}
					onCheckedChange={(value) =>
						void save((current) => ({
							...current,
							tools: {
								research: true,
								demo: true,
								visual: true,
								pdf: true,
								...current.tools,
								[tool]: value
							}
						}))}
					class="h-5 w-9 rounded-full bg-muted p-0.5 data-[state=checked]:bg-primary"
				>
					<Switch.Thumb
						class="block size-4 rounded-full bg-background transition-transform data-[state=checked]:translate-x-4"
					/>
				</Switch.Root>
			</div>
		{/each}
		<div class="flex items-start justify-between gap-6 border-t pt-4">
			<div>
				<label for="worker-concurrency" class="text-sm">Concurrent worker requests</label>
				<p class="mt-1 max-w-80 text-xs text-muted-foreground">
					Maximum simultaneous background-worker model requests. Direct conversations are not
					limited.
				</p>
			</div>
			<input
				id="worker-concurrency"
				type="number"
				min="1"
				step="1"
				placeholder="8"
				value={concurrency}
				disabled={busy || !settings}
				aria-invalid={!!fieldError}
				aria-describedby={fieldError ? 'concurrency-error' : undefined}
				class={`${inputClass} w-24`}
				oninput={(event) => {
					concurrency = event.currentTarget.value;
					fieldError = null;
				}}
				onblur={(event) => void commitConcurrency(event.currentTarget)}
				onkeydown={(event) => {
					if (event.key === 'Enter') {
						event.preventDefault();
						void commitConcurrency(event.currentTarget);
					}
				}}
			/>
		</div>
		{#if fieldError}<p id="concurrency-error" role="alert" class="text-xs text-destructive">
				{fieldError}
			</p>{/if}
	</section>
	<section aria-label="Research" class="space-y-4 rounded-xl border bg-card p-4">
		<h3 class="text-sm font-medium">Research</h3>
		<div class="flex items-center justify-between gap-4">
			<label for="search-engine" class="text-sm">Search engine</label>
			<select
				id="search-engine"
				class={inputClass}
				value={settings?.search_engine ?? 'native'}
				disabled={busy || !settings || !keys}
				onchange={(event) => {
					const value = event.currentTarget.value as Settings['search_engine'];
					void save((current) => ({ ...current, search_engine: value }));
				}}
			>
				<option value="native">Native</option>
				{#each engines as engine (engine.id)}<option
						value={engine.id}
						disabled={!keys?.[engine.id].present}
					>
						{engine.label}
					</option>{/each}
			</select>
		</div>
		<p class="text-xs text-muted-foreground">
			{missingKey ? `Key missing, using ${effectiveLabel}.` : `Using ${effectiveLabel}.`}
		</p>
		{#each engines as engine (engine.id)}
			<div class="space-y-2 border-t pt-3">
				<div class="flex items-center justify-between text-sm">
					<label for={`key-${engine.id}`}>{engine.label}</label>
					<button
						type="button"
						onclick={() => openExternal(engine.docs)}
						class="text-xs text-muted-foreground underline underline-offset-4"
					>
						Get a key
					</button>
				</div>
				<p class="text-xs text-muted-foreground">
					{keys?.[engine.id].masked ?? 'Not set'}{keys?.[engine.id].source === 'env'
						? ' · from environment'
						: ''}
				</p>
				<div class="flex gap-2">
					<input
						id={`key-${engine.id}`}
						type="password"
						autocomplete="off"
						placeholder="API key"
						bind:value={drafts[engine.id]}
						disabled={busy || !keys || keys[engine.id].source === 'env'}
						class={`${inputClass} flex-1`}
						onkeydown={(event) => {
							if (event.key === 'Enter') {
								event.preventDefault();
								if (drafts[engine.id].trim()) void keyAction(engine.id);
							}
						}}
					/>
					<Button
						variant="outline"
						size="sm"
						disabled={busy ||
							!keys ||
							keys[engine.id].source === 'env' ||
							!drafts[engine.id].trim()}
						onclick={() => void keyAction(engine.id)}
					>
						Set <span class="sr-only">{engine.label} key</span>
					</Button>
					<Button
						variant="ghost"
						size="sm"
						disabled={busy || !keys?.[engine.id].present || keys?.[engine.id].source === 'env'}
						onclick={() => void keyAction(engine.id, true)}
					>
						Clear <span class="sr-only">{engine.label} key</span>
					</Button>
				</div>
			</div>
		{/each}
	</section>
	{#if !desktop}
		<section aria-label="Demo browser" class="space-y-4 rounded-xl border bg-card p-4">
			<h3 class="text-sm font-medium">Demo browser</h3>
			<label for="demo-browser" class="block text-sm">Browser path</label>
			<input
				id="demo-browser"
				class={`${inputClass} w-full`}
				placeholder="Automatic discovery"
				bind:value={browserPath}
				disabled={busy || !settings}
				onblur={() => void commitBrowser()}
				onkeydown={(event) => {
					if (event.key === 'Enter') {
						event.preventDefault();
						void commitBrowser();
					}
				}}
			/>
			{#if browser?.path}<p class="text-xs break-all text-muted-foreground">
					{browser.path} · {browser.source}
				</p>
			{:else if browser}<p class="text-xs text-muted-foreground">
					No Chromium-family browser found.
				</p>
				<Button
					variant="outline"
					size="sm"
					disabled={busy || download?.state === 'downloading'}
					onclick={() => void startDownload()}
				>
					Download Chromium for demos
				</Button>
			{/if}
			{#if download?.state === 'downloading'}
				<div role="status" class="space-y-2">
					<p class="text-xs break-words text-muted-foreground">
						{download.message ?? 'Downloading Chromium…'}
					</p>
					<progress
						class="h-1 w-full"
						value={download.percent ?? undefined}
						max="100"
						aria-label="Chromium download"
					></progress>
				</div>
			{:else if download?.state === 'failed'}<p role="alert" class="text-sm text-destructive">
					{download.error}
				</p>
			{:else if download?.state === 'complete'}<p
					role="status"
					class="text-xs text-muted-foreground"
				>
					Chromium installed.
				</p>{/if}
		</section>
	{/if}
	{#if error}<p role="alert" class="text-sm text-destructive">{error}</p>{/if}
</div>
