import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page, userEvent } from 'vitest/browser';
import type { SourceOrganization } from '#lib/api/client.js';
import GraphFolderFilter from './graph-folder-filter.svelte';

const folder = (id: string, name: string, parent_id: string | null) => ({
	id,
	name,
	parent_id,
	created_at: 'now'
});
const organization: SourceOrganization = {
	version: 1,
	folders: [
		folder('maths', 'Maths', null),
		folder('algebra', 'Algebra', 'maths'),
		folder('art', 'Art', null)
	],
	placements: {}
};
const listed = new Set(['maths', 'algebra', 'art']);

test('the_filter_is_a_quiet_funnel_until_a_folder_is_ticked', async () => {
	const screen = await render(GraphFolderFilter, {
		organization,
		listed,
		selected: new Set<string>(),
		onchange: () => {}
	});
	const button = screen.getByRole('button', { name: 'Folder filter', exact: true });
	await expect.element(button).toHaveAttribute('data-active', 'false');
	await screen.rerender({ selected: new Set(['art']) });
	await expect
		.element(screen.getByRole('button', { name: 'Folder filter: Art' }))
		.toHaveAttribute('data-active', 'true');
	await screen.rerender({ selected: new Set(['maths', 'algebra', 'art']) });
	await expect
		.element(screen.getByRole('button', { name: 'Folder filter: 2 selected' }))
		.toBeVisible();
});

test('ticking_a_folder_ticks_its_listed_subfolders_and_show_all_clears', async () => {
	const onchange = vi.fn();
	const screen = await render(GraphFolderFilter, {
		organization,
		listed,
		selected: new Set(['art']),
		onchange
	});
	await screen.getByRole('button', { name: /Folder filter/ }).click();
	await expect.element(page.getByRole('group', { name: 'Show folders' })).toBeVisible();
	await page.getByRole('checkbox', { name: 'Show folder Maths' }).click();
	expect(onchange).toHaveBeenLastCalledWith(new Set(['art', 'maths', 'algebra']));
	await page.getByTestId('graph-folder-filter-clear').click();
	expect(onchange).toHaveBeenLastCalledWith(new Set());
});

test('a_partly_ticked_subtree_shows_indeterminate_and_only_listed_folders_appear', async () => {
	await render(GraphFolderFilter, {
		organization,
		listed: new Set(['maths', 'algebra']),
		selected: new Set(['algebra']),
		onchange: () => {}
	});
	await page.getByRole('button', { name: /Folder filter/ }).click();
	const maths = page.getByRole('checkbox', { name: 'Show folder Maths' });
	await expect.element(maths).toBeVisible();
	expect((maths.element() as HTMLInputElement).indeterminate).toBe(true);
	await expect
		.element(page.getByRole('checkbox', { name: 'Show folder Art' }))
		.not.toBeInTheDocument();
});

test('the_arrow_keys_walk_the_checkboxes_from_the_trigger', async () => {
	await render(GraphFolderFilter, {
		organization,
		listed,
		selected: new Set<string>(),
		onchange: () => {}
	});
	const trigger = page.getByRole('button', { name: /Folder filter/ });
	(trigger.element() as HTMLElement).focus();
	await userEvent.keyboard('{ArrowDown}');
	await expect.element(page.getByRole('checkbox', { name: 'Show folder Art' })).toHaveFocus();
	await userEvent.keyboard('{ArrowDown}');
	await expect.element(page.getByRole('checkbox', { name: 'Show folder Maths' })).toHaveFocus();
	await userEvent.keyboard('{End}');
	await expect.element(page.getByRole('checkbox', { name: 'Show folder Algebra' })).toHaveFocus();
});

test('an_empty_list_says_no_folder_holds_graph_material', async () => {
	await render(GraphFolderFilter, {
		organization,
		listed: new Set<string>(),
		selected: new Set<string>(),
		onchange: () => {}
	});
	await page.getByRole('button', { name: 'Folder filter' }).click();
	await expect.element(page.getByText('No folders contain graph material yet.')).toBeVisible();
});
