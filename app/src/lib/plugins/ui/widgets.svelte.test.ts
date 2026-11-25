import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { page, userEvent } from 'vitest/browser';
import { pluginUi } from './widgets.svelte.js';
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

test('invalid_settings_rows_are_rejected_before_mounting', () => {
	expect(() =>
		pluginUi.mountSettingsRows(
			container,
			{ rows: [toggleRow(() => {}), toggleRow(() => {})] },
			options()
		)
	).toThrow('Duplicate row key');
	expect(container.textContent).toBe('');
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
