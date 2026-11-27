const agents = [
	['prober', 'Prober'],
	['teacher', 'Teacher'],
	['practice', 'Practice'],
	['chat', 'Chat']
];

function blankServer() {
	return {
		name: '',
		command: '',
		args: [],
		env: {},
		tools: [],
		selections: {}
	};
}

function mount(backend, root, signal) {
	root.classList.add('mcp-settings');
	root.innerHTML = `
		<fieldset class="mcp-settings-controls" disabled>
			<div class="mcp-server-list">
				<label>Server <select data-server></select></label>
				<button type="button" data-add>Add server</button>
			</div>
			<form>
				<label>Name <input name="name" required placeholder="Zotero"></label>
				<label>Command <input name="command" required placeholder="/home/you/.local/bin/zotero-mcp" spellcheck="false"></label>
				<div class="mcp-command-options">
					<label>Arguments <span>JSON array of strings</span>
						<textarea name="args" rows="2" placeholder='["--option", "value"]' spellcheck="false"></textarea>
					</label>
					<label>Environment variables <span>JSON object of strings, saved locally</span>
						<textarea name="env" rows="2" placeholder='{"ZOTERO_LOCAL": "true"}' spellcheck="false"></textarea>
					</label>
				</div>
				<div class="mcp-connection">
					<button type="button" data-test>Test connection</button>
					<p data-connection-status role="status"></p>
				</div>
				<section data-tool-section hidden>
					<div class="mcp-tool-heading">
						<h4>Agent tools</h4>
						<label>Agent <select data-agent></select></label>
					</div>
					<div class="mcp-tool-controls">
						<label>Filter tools <input type="search" data-filter placeholder="Search by name or description"></label>
						<button type="button" data-select-all>Select all</button>
						<button type="button" data-clear-all>Clear all</button>
					</div>
					<div class="mcp-tools" data-tools></div>
				</section>
				<div class="mcp-settings-actions">
					<button type="submit" class="mcp-primary">Save</button>
					<button type="button" data-remove hidden>Remove server</button>
					<div data-confirm hidden>
						<span>Remove this server?</span>
						<button type="button" data-delete>Remove</button>
						<button type="button" data-cancel>Cancel</button>
					</div>
				</div>
			</form>
		</fieldset>
		<p data-status role="status"></p>
	`;

	const controls = root.querySelector('fieldset');
	const form = root.querySelector('form');
	const name = form.elements.namedItem('name');
	const command = form.elements.namedItem('command');
	const args = form.elements.namedItem('args');
	const env = form.elements.namedItem('env');
	const serverPicker = root.querySelector('[data-server]');
	const agentPicker = root.querySelector('[data-agent]');
	const toolSection = root.querySelector('[data-tool-section]');
	const filter = root.querySelector('[data-filter]');
	const selectAll = root.querySelector('[data-select-all]');
	const clearAll = root.querySelector('[data-clear-all]');
	const tools = root.querySelector('[data-tools]');
	const save = root.querySelector('[type=submit]');
	const remove = root.querySelector('[data-remove]');
	const confirm = root.querySelector('[data-confirm]');
	const status = root.querySelector('[data-status]');
	const connectionStatus = root.querySelector('[data-connection-status]');
	let servers = {};
	let id = '';
	let catalog = [];
	let selections = {};
	let tested = false;

	for (const [value, label] of agents) agentPicker.add(new Option(label, value));
	agentPicker.value = 'chat';

	function showStatus(message, error = false, output = status) {
		output.textContent = message;
		output.classList.toggle('mcp-error', error);
	}

	function renderTools() {
		toolSection.hidden = !tested;
		save.disabled = !tested;
		selectAll.disabled = clearAll.disabled = catalog.length === 0;
		const query = filter.value.toLowerCase().trim();
		const selected = (selections[agentPicker.value] ??= []);
		const visible = catalog.filter((tool) =>
			`${tool.name} ${tool.description}`.toLowerCase().includes(query)
		);
		tools.replaceChildren();
		if (!visible.length) {
			tools.textContent = catalog.length ? 'No matching tools.' : 'This server offers no tools.';
		}
		for (const tool of visible) {
			const label = document.createElement('label');
			const input = document.createElement('input');
			const title = document.createElement('span');
			const description = document.createElement('span');
			input.type = 'checkbox';
			input.checked = selected.includes(tool.name);
			title.textContent = tool.name;
			description.textContent = tool.description;
			input.setAttribute('aria-label', tool.name);
			input.addEventListener('change', () => {
				const current = selections[agentPicker.value] ?? [];
				selections[agentPicker.value] = input.checked
					? [...current, tool.name]
					: current.filter((item) => item !== tool.name);
			});
			const detail = document.createElement('span');
			detail.append(title, description);
			label.append(input, detail);
			tools.append(label);
		}
	}

	function edit(serverId) {
		id = serverId;
		const server = servers[id] ?? blankServer();
		serverPicker.replaceChildren(new Option('New server', ''));
		for (const saved of Object.values(servers)) serverPicker.add(new Option(saved.name, saved.id));
		serverPicker.value = id;
		name.value = server.name;
		command.value = server.command;
		args.value = server.args.length ? JSON.stringify(server.args) : '';
		env.value = Object.keys(server.env).length ? JSON.stringify(server.env) : '';
		catalog = server.tools;
		selections = structuredClone(server.selections);
		tested = Boolean(id);
		filter.value = '';
		remove.hidden = !id;
		confirm.hidden = true;
		renderTools();
	}

	function launchConfig() {
		return {
			command: command.value.trim(),
			args: JSON.parse(args.value.trim() || '[]'),
			env: JSON.parse(env.value.trim() || '{}')
		};
	}

	async function run(action, output = status) {
		controls.disabled = true;
		try {
			await action();
		} catch (error) {
			if (!signal.aborted)
				showStatus(error instanceof Error ? error.message : String(error), true, output);
		} finally {
			if (!signal.aborted) controls.disabled = false;
		}
	}

	function accepted(response) {
		if (response.error) throw new Error(response.error);
		return response;
	}

	function changeServer(serverId) {
		edit(serverId);
		showStatus('');
		showStatus('', false, connectionStatus);
	}

	serverPicker.addEventListener('change', () => changeServer(serverPicker.value));
	root.querySelector('[data-add]').addEventListener('click', () => {
		changeServer('');
		name.focus();
	});
	for (const field of [command, args, env]) {
		field.addEventListener('input', () => {
			tested = false;
			catalog = [];
			selections = {};
			showStatus('');
			showStatus('Test the connection to choose tools for this command.', false, connectionStatus);
			renderTools();
		});
	}
	agentPicker.addEventListener('change', renderTools);
	filter.addEventListener('input', renderTools);
	selectAll.addEventListener('click', () => {
		selections[agentPicker.value] = catalog.map((tool) => tool.name);
		renderTools();
	});
	clearAll.addEventListener('click', () => {
		selections[agentPicker.value] = [];
		renderTools();
	});
	root.querySelector('[data-test]').addEventListener('click', () =>
		run(async () => {
			showStatus('');
			showStatus('Connecting…', false, connectionStatus);
			const response = accepted(await backend.test_connection(launchConfig()));
			if (signal.aborted) return;
			catalog = response.tools;
			const names = new Set(catalog.map((tool) => tool.name));
			for (const [agent, selected] of Object.entries(selections))
				selections[agent] = selected.filter((tool) => names.has(tool));
			tested = true;
			renderTools();
			showStatus(
				`Found ${catalog.length} ${catalog.length === 1 ? 'tool' : 'tools'}.`,
				false,
				connectionStatus
			);
		}, connectionStatus)
	);
	form.addEventListener('submit', (event) => {
		event.preventDefault();
		if (!tested) return;
		void run(async () => {
			const response = accepted(
				await backend.save_server({
					id: id || null,
					server: {
						name: name.value.trim(),
						...launchConfig(),
						tools: catalog,
						selections
					}
				})
			);
			if (signal.aborted) return;
			const server = response.server;
			servers[server.id] = server;
			edit(server.id);
			showStatus('Saved. Changes apply on the next turn.');
		});
	});
	remove.addEventListener('click', () => {
		confirm.hidden = false;
		remove.hidden = true;
		root.querySelector('[data-cancel]').focus();
	});
	root.querySelector('[data-cancel]').addEventListener('click', () => {
		confirm.hidden = true;
		remove.hidden = false;
		remove.focus();
	});
	root.querySelector('[data-delete]').addEventListener('click', () =>
		run(async () => {
			accepted(await backend.remove_server(id));
			if (signal.aborted) return;
			delete servers[id];
			changeServer(Object.keys(servers)[0] ?? '');
			showStatus('Server removed. Changes apply on the next turn.');
		})
	);
	edit('');
	void run(async () => {
		const saved = await backend.get_servers();
		if (signal.aborted) return;
		servers = saved;
		edit(Object.keys(servers)[0] ?? '');
	});
}

export function activate(ctx) {
	ctx.registerSettings({
		mount(container, signal) {
			mount(ctx.backend, container, signal);
		}
	});
}
