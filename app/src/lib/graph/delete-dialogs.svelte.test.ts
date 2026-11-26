import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { ApiError, deleteGraphNode, deleteSession } from '#lib/api/client.js';
import { TRACES_COPY } from './delete-copy.js';
import DeleteNodeDialog from './delete-node-dialog.svelte';
import DeleteSessionDialog from './delete-session-dialog.svelte';

vi.mock('#lib/api/client.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.js')>()),
	deleteSession: vi.fn(),
	deleteGraphNode: vi.fn()
}));

const session = {
	id: 's1',
	title: 'Limits',
	kind: 'teach' as const,
	created_at: '2026-01-01T00:00:00Z',
	updated_at: '2026-01-01T00:00:00Z',
	busy: false,
	compacting: false
};

test('session_delete_keeps_graph_traces_by_default', async () => {
	vi.mocked(deleteSession).mockReset().mockResolvedValue();
	const ondeleted = vi.fn();
	const screen = await render(DeleteSessionDialog, { session, onclose: vi.fn(), ondeleted });
	await expect.element(screen.getByText(TRACES_COPY.title)).toBeVisible();
	await expect.element(screen.getByText(TRACES_COPY.body)).toBeVisible();
	await screen.getByRole('button', { name: 'Delete', exact: true }).click();
	expect(deleteSession).toHaveBeenLastCalledWith('s1', 'preserve-graph');
	await expect.poll(() => ondeleted.mock.calls.length).toBe(1);
});

test('session_delete_with_the_box_checked_removes_the_graph_traces', async () => {
	vi.mocked(deleteSession).mockReset().mockResolvedValue();
	const screen = await render(DeleteSessionDialog, {
		session,
		onclose: vi.fn(),
		ondeleted: vi.fn()
	});
	await screen.getByRole('checkbox').click();
	await screen.getByRole('button', { name: 'Delete', exact: true }).click();
	expect(deleteSession).toHaveBeenLastCalledWith('s1', 'delete-nodes');
});

test.each(['practice', 'chat'] as const)(
	'a_%s_session_delete_offers_no_graph_traces_and_preserves_the_graph',
	async (kind) => {
		vi.mocked(deleteSession).mockReset().mockResolvedValue();
		const screen = await render(DeleteSessionDialog, {
			session: { ...session, kind },
			onclose: vi.fn(),
			ondeleted: vi.fn()
		});
		await expect.element(screen.getByText(TRACES_COPY.title)).not.toBeInTheDocument();
		await expect.element(screen.getByText(/extraction records/)).not.toBeInTheDocument();
		await screen.getByRole('button', { name: 'Delete', exact: true }).click();
		expect(deleteSession).toHaveBeenLastCalledWith('s1', 'preserve-graph');
	}
);

test('session_delete_failure_shows_the_server_line_and_try_again_repeats_the_request', async () => {
	vi.mocked(deleteSession)
		.mockReset()
		.mockRejectedValueOnce(new ApiError(503, 'extraction_winding_down', 'Try again in a moment'))
		.mockResolvedValue();
	const ondeleted = vi.fn();
	const screen = await render(DeleteSessionDialog, { session, onclose: vi.fn(), ondeleted });
	await screen.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect.element(screen.getByText('Try again in a moment')).toBeVisible();
	await screen.getByRole('button', { name: 'Try again' }).click();
	await expect.poll(() => ondeleted.mock.calls.length).toBe(1);
	expect(deleteSession).toHaveBeenCalledTimes(2);
});

test('node_delete_names_the_nodes_and_stops_at_a_running_extraction', async () => {
	vi.mocked(deleteGraphNode)
		.mockReset()
		.mockResolvedValueOnce()
		.mockRejectedValueOnce(new ApiError(409, 'extraction_running', 'server text'));
	const ondeleted = vi.fn();
	const screen = await render(DeleteNodeDialog, {
		nodes: [
			{ id: 'a', name: 'Slope' },
			{ id: 'b', name: 'Limit' },
			{ id: 'c', name: 'Never reached' }
		],
		onclose: vi.fn(),
		ondeleted
	});
	await expect.element(screen.getByText('Delete 3 nodes?')).toBeVisible();
	await expect
		.element(screen.getByText('This permanently deletes all 3 nodes — this cannot be undone.'))
		.toBeVisible();
	await screen.getByRole('button', { name: 'Delete', exact: true }).click();
	await expect
		.element(screen.getByText('An extraction is running — try again when it finishes.'))
		.toBeVisible();
	expect(deleteGraphNode).toHaveBeenCalledTimes(2);
	expect(ondeleted).toHaveBeenCalledWith(['a']);
});
