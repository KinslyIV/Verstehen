import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { page, userEvent } from 'vitest/browser';
import { createPluginUi, pluginUi } from './widgets.svelte.js';
import type { SettingsRow } from '../types.js';

let container: HTMLElement;
let lifetime: AbortController;

beforeEach(() => {
	container = document.createElement('div');
	document.body.append(container);
	lifetime = new AbortController();
});

afterEach(() => {
	lifetime.abort();
	container.remove();
});

const options = () => ({ signal: lifetime.signal });

test('a_button_runs_its_handler_updates_its_label_and_is_removed_on_dispose', async () => {
	const onClick = vi.fn();
	const button = pluginUi.mountButton(container, { label: 'Save', onClick }, options());
	await page.getByRole('button', { name: 'Save' }).click();
	expect(onClick).toHaveBeenCalledOnce();
	button.update({ label: 'Saved', disabled: true });
	await expect.element(page.getByRole('button', { name: 'Saved' })).toBeDisabled();
	button.dispose();
	button.dispose();
	expect(container.querySelector('button')).toBeNull();
});

test('a_widget_is_disposed_when_its_activation_ends_even_though_its_own_signal_lives', async () => {
	const activation = new AbortController();
	const ui = createPluginUi(activation.signal);
	ui.mountButton(container, { label: 'Stay', onClick: () => {} }, options());
	await expect.element(page.getByRole('button', { name: 'Stay' })).toBeVisible();
	activation.abort();
	await vi.waitFor(() => expect(container.querySelector('button')).toBeNull());
	expect(lifetime.signal.aborted).toBe(false);
	const late = ui.mountButton(container, { label: 'Late', onClick: () => {} }, options());
	expect(container.querySelector('button')).toBeNull();
	late.dispose();
});

test('an_icon_only_button_keeps_its_label_as_the_accessible_name', async () => {
	pluginUi.mountButton(
		container,
		{ label: 'Open', iconOnly: true, icon: '<svg viewBox="0 0 1 1"></svg>', onClick: () => {} },
		options()
	);
	await expect.element(page.getByRole('button', { name: 'Open' })).toBeVisible();
	expect(container.textContent?.trim()).toBe('');
});

test('an_invalid_button_update_is_rejected_and_changes_nothing', async () => {
	const button = pluginUi.mountButton(container, { label: 'Keep', onClick: () => {} }, options());
	expect(() => button.update({ iconOnly: true })).toThrow('iconOnly needs an icon');
	expect(() => button.update({ label: ' ' })).toThrow('nonblank');
	expect(() => button.update({ variant: 'custom', colors: { background: 'not-a-color' } })).toThrow(
		'CSS color'
	);
	await expect.element(page.getByRole('button', { name: 'Keep' })).toBeVisible();
});

test('a_custom_button_applies_its_colors_only_for_the_custom_variant', async () => {
	pluginUi.mountButton(
		container,
		{ label: 'Tint', variant: 'custom', colors: { background: 'rgb(1, 2, 3)' }, onClick: () => {} },
		options()
	);
	const button = container.querySelector('button')!;
	expect(getComputedStyle(button).backgroundColor).toBe('rgb(1, 2, 3)');
});

test('a_badge_shows_its_text_and_tints_with_its_color', async () => {
	const badge = pluginUi.mountBadge(container, { text: 'New', color: 'rgb(200, 0, 0)' }, options());
	const element = page.getByText('New');
	await expect.element(element).toBeVisible();
	expect((element.element() as HTMLElement).style.color).toBe('rgb(200, 0, 0)');
	badge.update({ text: 'Old', color: undefined });
	await expect.element(page.getByText('Old')).toBeVisible();
	expect(() => badge.update({ color: 'inherit' })).toThrow('CSS color');
});

test('markdown_renders_with_the_app_pipeline_and_updates', async () => {
	const markdown = pluginUi.mountMarkdown(container, { text: '**Bold** and `code`' }, options());
	await expect.element(page.getByText('Bold')).toBeVisible();
	expect(container.querySelector('strong')?.textContent).toBe('Bold');
	markdown.update({ text: '# Heading' });
	await expect.element(page.getByRole('heading', { name: 'Heading' })).toBeVisible();
});

function toggleRow(
	onChange: SettingsRow['onChange'],
	validate?: SettingsRow['validate']
): SettingsRow {
	return {
		key: 'on',
		type: 'toggle',
		label: 'Enabled',
		value: false,
		onChange,
		validate
	} as SettingsRow;
}

test('settings_rows_save_changes_and_the_plugin_publishes_the_accepted_value', async () => {
	const onChange = vi.fn();
	const rows = pluginUi.mountSettingsRows(container, { rows: [toggleRow(onChange)] }, options());
	await page.getByRole('switch', { name: 'Enabled' }).click();
	expect(onChange).toHaveBeenCalledWith(true);
	rows.update({ rows: [{ ...toggleRow(onChange), value: true } as SettingsRow] });
	await expect.element(page.getByRole('switch', { name: 'Enabled' })).toBeChecked();
});

test('a_validation_failure_shows_inline_without_saving_and_a_thrown_save_shows_its_message', async () => {
	const onChange = vi.fn();
	pluginUi.mountSettingsRows(
		container,
		{ rows: [toggleRow(onChange, () => 'Not allowed')] },
		options()
	);
	await page.getByRole('switch', { name: 'Enabled' }).click();
	await expect.element(page.getByRole('alert')).toHaveTextContent('Not allowed');
	expect(onChange).not.toHaveBeenCalled();

	const failing = document.createElement('div');
	container.append(failing);
	pluginUi.mountSettingsRows(
		failing,
		{
			rows: [
				toggleRow(async () => {
					throw new Error('Disk full');
				})
			]
		},
		options()
	);
	await page.getByRole('switch', { name: 'Enabled' }).nth(1).click();
	await expect.element(page.getByText('Disk full')).toBeVisible();
});

test('number_rows_refuse_values_outside_their_range', async () => {
	const onChange = vi.fn();
	pluginUi.mountSettingsRows(
		container,
		{ rows: [{ key: 'n', type: 'number', label: 'Count', value: 1, min: 1, max: 5, onChange }] },
		options()
	);
	const input = page.getByRole('spinbutton', { name: 'Count' });
	await input.fill('9');
	await userEvent.keyboard('{Tab}');
	await expect.element(page.getByRole('alert')).toHaveTextContent('Enter a number from 1 to 5');
	expect(onChange).not.toHaveBeenCalled();
	await input.fill('4');
	await userEvent.keyboard('{Tab}');
	expect(onChange).toHaveBeenCalledWith(4);
});

test('invalid_settings_rows_are_rejected_before_mounting', async () => {
	expect(() =>
		pluginUi.mountSettingsRows(
			container,
			{ rows: [toggleRow(() => {}), toggleRow(() => {})] },
			options()
		)
	).toThrow('Duplicate row key');
	const badRows: [unknown, string][] = [
		[null, 'A row must be an object'],
		[{ ...toggleRow(() => {}), disabled: 'yes' }, 'disabled must be boolean'],
		[{ ...toggleRow(() => {}), description: 42 }, 'description must be text'],
		[
			{
				key: 'dd',
				type: 'dropdown',
				label: 'Mode',
				value: 'a',
				options: [null],
				onChange: () => {}
			},
			'options need string value and label'
		],
		[
			{
				key: 'dd',
				type: 'dropdown',
				label: 'Mode',
				value: 'a',
				options: [{ value: 'a', label: 123 }],
				onChange: () => {}
			},
			'options need string value and label'
		],
		[
			{
				key: 'dd',
				type: 'dropdown',
				label: 'Mode',
				value: 'a',
				options: [
					{ value: 'a', label: 'A' },
					{ value: 'a', label: 'Again' }
				],
				onChange: () => {}
			},
			'duplicate option value'
		],
		[
			{ key: 'n', type: 'number', label: 'N', value: 1, min: Number.NaN, onChange: () => {} },
			'min must be a finite number'
		],
		[
			{
				key: 'n',
				type: 'slider',
				label: 'N',
				value: 1,
				max: Number.POSITIVE_INFINITY,
				onChange: () => {}
			},
			'max must be a finite number'
		],
		[
			{ key: 'n', type: 'number', label: 'N', value: 1, step: Number.NaN, onChange: () => {} },
			'step must be a finite number'
		],
		[
			{ key: 'n', type: 'number', label: 'N', value: 1, min: 5, max: 2, onChange: () => {} },
			'min exceeds max'
		],
		[
			{ key: 'n', type: 'slider', label: 'N', value: 1, step: 0, onChange: () => {} },
			'step must be positive'
		],
		[
			{ key: 'n', type: 'number', label: 'N', value: 1, step: -1, onChange: () => {} },
			'step must be positive'
		]
	];
	for (const [bad, reason] of badRows) {
		expect(() =>
			pluginUi.mountSettingsRows(container, { rows: [bad as SettingsRow] }, options())
		).toThrow(reason);
	}
	expect(container.textContent).toBe('');

	const handle = pluginUi.mountSettingsRows(container, { rows: [toggleRow(() => {})] }, options());
	await expect.element(page.getByRole('switch', { name: 'Enabled' })).toBeVisible();
	for (const [bad, reason] of badRows) {
		expect(() => handle.update({ rows: [bad as SettingsRow] })).toThrow(reason);
	}
	await expect.element(page.getByRole('switch', { name: 'Enabled' })).toBeVisible();
});

test('a_dialog_shows_its_content_closes_on_escape_and_tells_the_plugin', async () => {
	const onClose = vi.fn();
	const content = document.createElement('p');
	content.textContent = 'Dialog body';
	pluginUi.openDialog({ title: 'Details', content, onClose }, options());
	await expect.element(page.getByRole('dialog', { name: 'Details' })).toBeVisible();
	await expect.element(page.getByText('Dialog body')).toBeVisible();
	await userEvent.keyboard('{Escape}');
	await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
	expect(onClose).toHaveBeenCalledOnce();
});

test('a_dialog_mounts_function_content_and_cleans_up_when_disposed', async () => {
	const cleanup = vi.fn();
	const dialog = pluginUi.openDialog(
		{
			title: 'Made',
			content: (target) => {
				target.textContent = 'Built';
				return cleanup;
			}
		},
		options()
	);
	await expect.element(page.getByText('Built')).toBeVisible();
	dialog.dispose();
	await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
	expect(cleanup).toHaveBeenCalledOnce();
});

test('a_menu_selects_an_item_closes_and_a_second_open_on_the_same_anchor_closes_it', async () => {
	const anchor = document.createElement('button');
	anchor.textContent = 'Anchor';
	container.append(anchor);
	const onSelect = vi.fn();
	const onClose = vi.fn();
	pluginUi.openMenu(
		anchor,
		{ label: 'Actions', items: [{ key: 'a', label: 'Do it', onSelect }], onClose },
		options()
	);
	await expect.element(page.getByRole('menu', { name: 'Actions' })).toBeVisible();
	const again = pluginUi.openMenu(anchor, { items: [] }, options());
	await expect.poll(() => document.querySelector('[role="menu"]')).toBeNull();
	expect(onClose).toHaveBeenCalledOnce();
	again.update({});

	pluginUi.openMenu(anchor, { items: [{ key: 'a', label: 'Do it', onSelect }] }, options());
	await page.getByRole('menuitem', { name: 'Do it' }).click();
	expect(onSelect).toHaveBeenCalledOnce();
	await expect.poll(() => document.querySelector('[role="menu"]')).toBeNull();
});

test('aborting_the_signal_disposes_every_widget', async () => {
	pluginUi.mountBadge(container, { text: 'Gone' }, options());
	pluginUi.openDialog({ title: 'Also gone', content: document.createElement('div') }, options());
	await expect.element(page.getByRole('dialog')).toBeVisible();
	lifetime.abort();
	await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
	expect(container.textContent).toBe('');
});

test('widgets_mounted_and_left_repeatedly_leave_no_listener_on_the_activation_signal', async () => {
	const activation = new AbortController();
	const attached = new Set<unknown>();
	vi.spyOn(activation.signal, 'addEventListener').mockImplementation((_, listener) => {
		attached.add(listener);
	});
	vi.spyOn(activation.signal, 'removeEventListener').mockImplementation((_, listener) => {
		attached.delete(listener);
	});
	const ui = createPluginUi(activation.signal);
	for (let round = 0; round < 10; round++) {
		const view = new AbortController();
		const own = { signal: view.signal };
		ui.mountButton(container, { label: 'Leave', onClick: () => {} }, own);
		ui.mountBadge(container, { text: 'Gone' }, own).dispose();
		ui.openDialog({ title: 'Closes', content: document.createElement('div') }, own);
		await expect.element(page.getByRole('dialog')).toBeVisible();
		await userEvent.keyboard('{Escape}');
		await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
		view.abort();
	}
	expect(attached.size).toBe(0);
	expect(container.textContent).toBe('');
});

test('a_dialog_awaits_async_mount_and_async_cleanup_and_catches_cleanup_and_onclose_errors', async () => {
	const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
	const events: string[] = [];
	let releaseMount!: () => void;
	const dialog = pluginUi.openDialog(
		{
			title: 'Async dialog',
			async content(target) {
				await new Promise<void>((resolve) => (releaseMount = resolve));
				target.textContent = 'Async ready';
				return async () => {
					await new Promise((resolve) => setTimeout(resolve, 10));
					events.push('async-cleanup');
					throw new Error('cleanup boom');
				};
			},
			onClose() {
				events.push('on-close');
				throw new Error('onClose sync boom');
			}
		},
		options()
	);
	await vi.waitFor(() => expect(releaseMount).toBeTypeOf('function'));
	releaseMount();
	await expect.element(page.getByText('Async ready')).toBeVisible();
	await userEvent.keyboard('{Escape}');
	await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
	await vi.waitFor(() => expect(events).toEqual(['on-close', 'async-cleanup']));
	expect(logged).toHaveBeenCalledTimes(2);
	dialog.dispose();

	let finishLateMount!: () => void;
	const lateCleanup = vi.fn();
	const early = pluginUi.openDialog(
		{
			title: 'Closed early',
			async content() {
				await new Promise<void>((resolve) => (finishLateMount = resolve));
				return lateCleanup;
			}
		},
		options()
	);
	await vi.waitFor(() => expect(finishLateMount).toBeTypeOf('function'));
	early.dispose();
	await expect.poll(() => document.querySelector('[role="dialog"]')).toBeNull();
	finishLateMount();
	await vi.waitFor(() => expect(lateCleanup).toHaveBeenCalledOnce());
	logged.mockRestore();
});

test('same_anchor_menu_dismissal_uses_updated_onclose_and_disposes_even_when_onclose_throws', async () => {
	const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
	const anchor = document.createElement('button');
	anchor.textContent = 'Menu anchor';
	container.append(anchor);
	const firstClose = vi.fn();
	const updatedClose = vi.fn(() => {
		throw new Error('menu onClose boom');
	});
	const handle = pluginUi.openMenu(
		anchor,
		{
			label: 'First menu',
			items: [{ key: 'a', label: 'Item A', onSelect: () => {} }],
			onClose: firstClose
		},
		options()
	);
	await expect.element(page.getByRole('menu', { name: 'First menu' })).toBeVisible();
	handle.update({ onClose: updatedClose });

	pluginUi.openMenu(anchor, { items: [] }, options());
	await expect.poll(() => document.querySelector('[role="menu"]')).toBeNull();
	expect(firstClose).not.toHaveBeenCalled();
	expect(updatedClose).toHaveBeenCalledOnce();
	expect(logged).toHaveBeenCalledOnce();

	const reopened = pluginUi.openMenu(
		anchor,
		{
			label: 'Reopened menu',
			items: [{ key: 'b', label: 'Item B', onSelect: () => {} }]
		},
		options()
	);
	await expect.element(page.getByRole('menu', { name: 'Reopened menu' })).toBeVisible();
	reopened.dispose();
	await expect.poll(() => document.querySelector('[role="menu"]')).toBeNull();
	logged.mockRestore();
});
