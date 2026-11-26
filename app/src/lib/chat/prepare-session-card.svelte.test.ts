import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import { models } from '#lib/models/catalog.svelte.js';
import { testCatalog, testSettings } from '#lib/models/test-fixtures.js';
import { readOpening } from '#lib/session/opening.js';
import PrepareSessionCard from './prepare-session-card.svelte';

const navigated = vi.hoisted(() => ({ hrefs: [] as string[] }));
vi.mock('$app/navigation', () => ({
	goto: vi.fn(async (href: string) => {
		navigated.hrefs.push(href);
	})
}));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: vi.fn(),
	refreshModels: vi.fn(),
	getSettings: vi.fn(),
	createSession: vi.fn()
}));

function makeResult(details: Record<string, unknown>): api.ToolResult {
	return {
		kind: 'tool_result',
		entry_id: 'tr_1',
		tool_call_id: 'tc_1',
		tool_name: 'prepare_session',
		text: 'Launch card prepared.',
		is_error: false,
		details
	};
}

beforeEach(() => {
	vi.clearAllMocks();
	sessionStorage.clear();
	navigated.hrefs = [];
	models.reset();
	vi.mocked(api.refreshModels).mockResolvedValue(undefined);
	vi.mocked(api.getModels).mockResolvedValue(structuredClone(testCatalog));
	vi.mocked(api.getSettings).mockResolvedValue(structuredClone(testSettings));
});

test('renders_teach_card_metadata_and_starts_a_new_teaching_session_with_folder_and_graph_context', async () => {
	vi.mocked(api.createSession).mockResolvedValueOnce({ id: 's_teach_1' } as never);
	const propositions = [
		{ id: 'n_slope', name: 'Slope', statement: 'Slope is rise over run.' },
		{ id: 'n_limit', name: 'Limit', statement: 'A limit approaches a value.' }
	];
	const screen = await render(PrepareSessionCard, {
		result: makeResult({
			kind: 'teach',
			title: 'Secant to Tangent',
			opening_prompt: 'Help me connect secant slopes to derivatives.',
			folder_id: 'f_calc',
			folder_name: 'Math/Calculus',
			propositions
		})
	});

	await expect.element(screen.getByTestId('prepare-session-kind')).toHaveTextContent('Teaching');
	await expect
		.element(screen.getByTestId('prepare-session-title'))
		.toHaveTextContent('Secant to Tangent');
	await expect
		.element(screen.getByTestId('prepare-session-folder'))
		.toHaveTextContent('Math/Calculus');
	await expect.element(screen.getByText('Slope')).toBeVisible();
	await expect.element(screen.getByText('Limit')).toBeVisible();
	await expect
		.element(screen.getByTestId('prepare-session-prompt'))
		.toHaveTextContent('Help me connect secant slopes to derivatives.');

	const startBtn = screen.getByTestId('prepare-session-start');
	await expect.element(startBtn).toHaveTextContent('Start teaching');
	await startBtn.click();

	await expect.poll(() => vi.mocked(api.createSession).mock.calls.length).toBe(1);
	expect(api.createSession).toHaveBeenCalledWith(
		'Secant to Tangent',
		null,
		{ propositions },
		'teach',
		'f_calc'
	);
	expect(readOpening('s_teach_1')).toEqual({
		text: 'Help me connect secant slopes to derivatives.',
		attempted: false
	});
	expect(navigated.hrefs).toEqual(['/session/s_teach_1']);
});

test('renders_practice_card_and_falls_back_to_top_level_when_the_folder_was_deleted', async () => {
	vi.mocked(api.createSession)
		.mockRejectedValueOnce(new api.ApiError(400, undefined, 'Folder no longer exists.'))
		.mockResolvedValueOnce({ id: 's_prac_1' } as never);

	const screen = await render(PrepareSessionCard, {
		result: makeResult({
			kind: 'practice',
			title: null,
			opening_prompt: 'Drill me on the chain rule.',
			folder_id: 'f_gone',
			folder_name: 'Old Folder',
			propositions: []
		})
	});

	await expect.element(screen.getByTestId('prepare-session-kind')).toHaveTextContent('Practice');
	const startBtn = screen.getByTestId('prepare-session-start');
	await expect.element(startBtn).toHaveTextContent('Start practice');
	await startBtn.click();

	await expect.poll(() => vi.mocked(api.createSession).mock.calls.length).toBe(2);
	expect(vi.mocked(api.createSession).mock.calls[0]).toEqual([
		'Drill me on the chain rule.',
		null,
		undefined,
		'practice',
		'f_gone'
	]);
	expect(vi.mocked(api.createSession).mock.calls[1]).toEqual([
		'Drill me on the chain rule.',
		null,
		undefined,
		'practice',
		undefined
	]);
	await expect
		.element(screen.getByTestId('prepare-session-folder-note'))
		.toHaveTextContent('Folder no longer exists. Started at the top level instead.');
	expect(readOpening('s_prac_1')).toEqual({
		text: 'Drill me on the chain rule.',
		attempted: false,
		notice: 'Folder no longer exists. Started at the top level instead.'
	});
	expect(navigated.hrefs).toEqual(['/session/s_prac_1']);
});

test('does_not_show_deleted_folder_notice_when_fallback_creation_fails_and_retries_without_duplicate_post', async () => {
	const { goto } = await import('$app/navigation');
	vi.mocked(api.createSession)
		.mockRejectedValueOnce(new api.ApiError(400, undefined, 'Folder no longer exists.'))
		.mockRejectedValueOnce(new api.ApiError(503, undefined, 'Server overloaded.'))
		.mockRejectedValueOnce(new api.ApiError(400, undefined, 'Folder no longer exists.'))
		.mockResolvedValueOnce({ id: 's_retry_1' } as never);

	const screen = await render(PrepareSessionCard, {
		result: makeResult({
			kind: 'teach',
			title: 'Calculus',
			opening_prompt: 'Explain limits.',
			folder_id: 'f_gone',
			folder_name: 'Old Folder',
			propositions: []
		})
	});

	const startBtn = screen.getByTestId('prepare-session-start');
	await startBtn.click();

	await expect
		.element(screen.getByTestId('prepare-session-error'))
		.toHaveTextContent('Server overloaded.');
	await expect.element(screen.getByTestId('prepare-session-folder-note')).not.toBeInTheDocument();

	vi.mocked(goto).mockRejectedValueOnce(new Error('Navigation aborted'));
	await startBtn.click();

	await expect.poll(() => vi.mocked(api.createSession).mock.calls.length).toBe(4);
	await expect.element(screen.getByTestId('prepare-session-error')).toBeVisible();

	await startBtn.click();
	await expect.poll(() => navigated.hrefs.length).toBe(1);
	expect(vi.mocked(api.createSession).mock.calls.length).toBe(4);
	expect(navigated.hrefs).toEqual(['/session/s_retry_1']);
});

test('shows_an_inline_error_when_session_creation_fails', async () => {
	vi.mocked(api.createSession).mockRejectedValueOnce(
		new api.ApiError(503, undefined, 'Database is busy.')
	);
	const screen = await render(PrepareSessionCard, {
		result: makeResult({
			kind: 'teach',
			title: 'Linear Algebra',
			opening_prompt: 'Explain eigenvectors.',
			propositions: []
		})
	});

	await screen.getByTestId('prepare-session-start').click();
	await expect
		.element(screen.getByTestId('prepare-session-error'))
		.toHaveTextContent('Database is busy.');
	expect(navigated.hrefs).toEqual([]);
});
