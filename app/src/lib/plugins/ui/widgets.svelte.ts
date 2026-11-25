import { mount, unmount, type Component } from 'svelte';
import { SvelteSet } from 'svelte/reactivity';
import PluginBadge from './plugin-badge.svelte';
import PluginButton from './plugin-button.svelte';
import PluginDialog from './plugin-dialog.svelte';
import PluginMarkdown from './plugin-markdown.svelte';
import PluginMenu from './plugin-menu.svelte';
import PluginSettingsRows from './plugin-settings-rows.svelte';
import type {
	BadgeProps,
	ButtonProps,
	DialogProps,
	MarkdownProps,
	MenuProps,
	PluginUi,
	SettingsRowsProps,
	WidgetHandle,
	WidgetOptions
} from '../types.js';

const CSS_WIDE = ['inherit', 'initial', 'unset', 'revert', 'revert-layer'];
const BUTTON_VARIANTS = [
	'default',
	'destructive',
	'outline',
	'secondary',
	'ghost',
	'link',
	'custom'
];

function checkText(value: unknown, what: string): asserts value is string {
	if (typeof value !== 'string' || !value.trim())
		throw new TypeError(`${what} must be nonblank text`);
}

function checkColor(value: unknown, what: string) {
	checkText(value, what);
	if (CSS_WIDE.includes(value.trim().toLowerCase()) || !CSS.supports('color', value))
		throw new TypeError(`${what} must be a CSS color`);
}

function checkColorState(state: unknown, what: string, nested: string[] = [], ring = false) {
	if (state === undefined) return;
	if (typeof state !== 'object' || state === null) throw new TypeError(`${what} must be an object`);
	const colorSlots = ['background', 'text', 'border', ...(ring ? ['ring'] : [])];
	for (const [slot, value] of Object.entries(state)) {
		if (nested.includes(slot)) continue;
		if (!colorSlots.includes(slot)) throw new TypeError(`Unknown ${what} slot: ${slot}`);
		checkColor(value, `${what}.${slot}`);
	}
}

function checkButton(props: ButtonProps) {
	checkText(props.label, 'label');
	if (typeof props.onClick !== 'function') throw new TypeError('onClick must be a function');
	if (props.variant !== undefined && !BUTTON_VARIANTS.includes(props.variant))
		throw new TypeError(`Unknown button variant: ${props.variant}`);
	if (props.iconOnly && !props.icon?.trim()) throw new TypeError('iconOnly needs an icon');
	const colors = props.colors;
	checkColorState(colors, 'colors', ['hover', 'active', 'focusVisible', 'disabled']);
	for (const slot of ['hover', 'active', 'disabled'] as const)
		checkColorState(colors?.[slot], `colors.${slot}`);
	checkColorState(colors?.focusVisible, 'colors.focusVisible', [], true);
}

function checkBadge(props: BadgeProps) {
	if (typeof props.text !== 'string') throw new TypeError('text must be text');
	if (props.color !== undefined) checkColor(props.color, 'color');
}

function checkMarkdown(props: MarkdownProps) {
	if (typeof props.text !== 'string') throw new TypeError('text must be text');
}

function checkRows(props: SettingsRowsProps) {
	if (!Array.isArray(props.rows)) throw new TypeError('rows must be a list');
	const keys = new SvelteSet<string>();
	for (const row of props.rows) {
		checkText(row?.key, 'A row key');
		checkText(row.label, 'A row label');
		if (keys.has(row.key)) throw new TypeError(`Duplicate row key: ${row.key}`);
		keys.add(row.key);
		if (typeof row.onChange !== 'function')
			throw new TypeError('A row onChange must be a function');
		if (row.validate !== undefined && typeof row.validate !== 'function')
			throw new TypeError('A row validate must be a function');
		const valueType =
			row.type === 'toggle'
				? 'boolean'
				: row.type === 'text' || row.type === 'dropdown'
					? 'string'
					: 'number';
		if (typeof row.value !== valueType || (valueType === 'number' && !Number.isFinite(row.value)))
			throw new TypeError(`Row ${row.key} needs a ${valueType} value`);
		if (row.type === 'dropdown' && !Array.isArray(row.options))
			throw new TypeError(`Row ${row.key} needs options`);
		if (!['toggle', 'text', 'dropdown', 'number', 'slider'].includes(row.type))
			throw new TypeError(`Unknown row type: ${row.type}`);
	}
}

function checkDialog(props: DialogProps) {
	checkText(props.title, 'title');
	if (!(props.content instanceof HTMLElement) && typeof props.content !== 'function')
		throw new TypeError('content must be an element or a mount function');
}

function checkMenu(props: MenuProps) {
	if (!Array.isArray(props.items)) throw new TypeError('items must be a list');
	const keys = new SvelteSet<string>();
	for (const item of props.items) {
		checkText(item?.key, 'A menu item key');
		checkText(item.label, 'A menu item label');
		if (typeof item.onSelect !== 'function')
			throw new TypeError('A menu item onSelect must be a function');
		if (keys.has(item.key)) throw new TypeError(`Duplicate menu item key: ${item.key}`);
		keys.add(item.key);
	}
}

interface MountedWidget<Props extends object> {
	component: Component<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
	target: HTMLElement;
	props: Props;
	options: WidgetOptions;
	check(props: Props): void;
	extra?: Record<string, unknown>;
	onDismiss?(props: Props): void;
	onDispose?(): void;
}

/** Mounts a component over reactive props: `update` merges and re-validates, abort or `dispose` unmounts. */
function mountWidget<Props extends object>(widget: MountedWidget<Props>): WidgetHandle<Props> {
	widget.check(widget.props);
	const props = $state(widget.props);
	let instance: Record<string, unknown> | undefined;
	const dispose = () => {
		if (!instance) return;
		const mounted = instance;
		instance = undefined;
		widget.options.signal.removeEventListener('abort', dispose);
		void unmount(mounted);
		widget.onDispose?.();
	};
	const ondismiss = () => {
		if (!instance) return;
		widget.onDismiss?.(props);
		dispose();
	};
	instance = mount(widget.component, {
		target: widget.target,
		props: { props, ondismiss, ...widget.extra }
	});
	if (widget.options.signal.aborted) dispose();
	else widget.options.signal.addEventListener('abort', dispose, { once: true });
	return {
		update(next) {
			if (!instance) return;
			widget.check({ ...props, ...next });
			Object.assign(props, next);
		},
		dispose
	};
}

const reportFailure = (error: unknown) => console.error('Plugin callback failed', error);

function overlayHost(): HTMLElement {
	const host = document.createElement('div');
	document.body.append(host);
	return host;
}

const openMenus = new WeakMap<HTMLElement, () => void>();
const inertHandle = { update() {}, dispose() {} };

/** The six host widgets a plugin builds its pages from. */
export const pluginUi: PluginUi = {
	mountButton: (target, props, options) =>
		mountWidget({ component: PluginButton, target, props, options, check: checkButton }),
	mountBadge: (target, props, options) =>
		mountWidget({ component: PluginBadge, target, props, options, check: checkBadge }),
	mountMarkdown: (target, props, options) =>
		mountWidget({ component: PluginMarkdown, target, props, options, check: checkMarkdown }),
	mountSettingsRows: (target, props, options) =>
		mountWidget({ component: PluginSettingsRows, target, props, options, check: checkRows }),
	openDialog(props, options) {
		const target = overlayHost();
		return mountWidget({
			component: PluginDialog,
			target,
			props,
			options,
			check: checkDialog,
			onDismiss: (latest) => void Promise.resolve(latest.onClose?.()).catch(reportFailure),
			onDispose: () => target.remove()
		});
	},
	openMenu(anchor, props, options) {
		const open = openMenus.get(anchor);
		if (open) {
			open();
			return inertHandle;
		}
		const target = overlayHost();
		const handle = mountWidget({
			component: PluginMenu,
			target,
			props,
			options,
			check: checkMenu,
			extra: { anchor },
			onDismiss: (latest) => void Promise.resolve(latest.onClose?.()).catch(reportFailure),
			onDispose: () => {
				openMenus.delete(anchor);
				target.remove();
			}
		});
		openMenus.set(anchor, () => {
			void Promise.resolve(props.onClose?.()).catch(reportFailure);
			handle.dispose();
		});
		return handle;
	}
};

/** The widgets one activation gets: each is also disposed when that activation ends. */
export function createPluginUi(activation: AbortSignal): PluginUi {
	function bound<Handle extends { dispose(): void }>(
		options: WidgetOptions,
		mount: (options: WidgetOptions) => Handle
	): Handle {
		const both = new AbortController();
		const stop = () => both.abort();
		const detach = () => {
			options.signal.removeEventListener('abort', stop);
			activation.removeEventListener('abort', stop);
		};
		if (options.signal.aborted || activation.aborted) both.abort();
		options.signal.addEventListener('abort', stop, { once: true });
		activation.addEventListener('abort', stop, { once: true });
		const handle = mount({ ...options, signal: both.signal });
		return {
			...handle,
			dispose() {
				detach();
				handle.dispose();
			}
		};
	}
	return {
		mountButton: (target, props, options) =>
			bound(options, (own) => pluginUi.mountButton(target, props, own)),
		mountBadge: (target, props, options) =>
			bound(options, (own) => pluginUi.mountBadge(target, props, own)),
		mountMarkdown: (target, props, options) =>
			bound(options, (own) => pluginUi.mountMarkdown(target, props, own)),
		mountSettingsRows: (target, props, options) =>
			bound(options, (own) => pluginUi.mountSettingsRows(target, props, own)),
		openDialog: (props, options) => bound(options, (own) => pluginUi.openDialog(props, own)),
		openMenu: (anchor, props, options) =>
			bound(options, (own) => pluginUi.openMenu(anchor, props, own))
	};
}
