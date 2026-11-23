import { beforeEach, expect, test, vi } from 'vitest';
import { userEvent } from 'vitest/browser';
import { questionBatch } from '#lib/questions/question-fixtures.js';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import SessionThread from './session-thread.svelte';
const backListeners = vi.hoisted(() => new Set<(event: { canGoBack: boolean }) => void>());
vi.mock('@capacitor/core', async (original) => ({
	...(await original<typeof import('@capacitor/core')>()),
	Capacitor: { getPlatform: () => 'android' }
}));
vi.mock('@capacitor/app', () => ({
	App: {
		addListener: (_: string, listener: (event: { canGoBack: boolean }) => void) => {
			backListeners.add(listener);
			return Promise.resolve({ remove: () => backListeners.delete(listener) });
		},
		exitApp: vi.fn()
	}
}));
const pressBack = () => backListeners.forEach((listener) => listener({ canGoBack: true }));
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getModels: async () => ({ accounts: [], slots: {} }),
	refreshModels: async () => {},
	getJobs: vi.fn(),
	getExtractionStatus: async () => [],
	getSettings: async () => ({}),
	getSideChats: async () => ({ threads: [], answering: {} }),
	getSession: vi.fn(),
	postInput: vi.fn(),
	streamTurn: vi.fn()
}));
beforeEach(() => {
	vi.spyOn(history, 'back').mockImplementation(() => {});
	sessionStorage.clear();
	vi.mocked(api.getJobs).mockReset().mockResolvedValue({ jobs: [], turn_in_flight: false });
	vi.mocked(api.getSession).mockReset();
	vi.mocked(api.postInput).mockReset();
});
test('saved_thread_renders_plain_learner_text_markdown_and_collapsed_thinking', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{ kind: 'user', entry_id: 'u', text: '**plain**' },
			{
				kind: 'assistant',
				entry_id: 'a',
				stop_reason: 'stop',
				parts: [
					{ type: 'thinking', thinking: 'Consider slope.', redacted: false },
					{ type: 'text', text: '**Answer**' }
				]
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByText('**plain**', { exact: true })).toBeVisible();
	await expect.element(screen.getByText('Answer', { exact: true })).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: "AGENT'S THINKING" }))
		.toHaveAttribute('aria-expanded', 'false');
	await screen.getByRole('button', { name: "AGENT'S THINKING" }).click();
	await expect.element(screen.getByText('Consider slope.')).toBeVisible();
});
test('failed_saved_reply_offers_retry_after_reload', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{
				kind: 'assistant',
				entry_id: 'a',
				stop_reason: 'error',
				error_text: 'Provider failed',
				parts: []
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByText('Provider failed', { exact: true })).toBeVisible();
	await expect.element(screen.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
});

test('the_question_draft_is_restored_after_a_failed_submit', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [questionBatch('one')]
	});
	vi.mocked(api.postInput).mockRejectedValue(new Error('Network unavailable'));
	const screen = await render(SessionThread, { id: 'one' });
	const two = screen.getByRole('radio', { name: 'Two' });
	await two.click();
	await userEvent.keyboard('{ArrowRight}');
	const thinking = screen.getByRole('textbox', { name: 'Your thinking' });
	await thinking.fill('An even number is divisible by two.');
	await screen.getByRole('button', { name: 'Submit answer' }).click();
	await expect.element(screen.getByText('Network unavailable')).toBeVisible();
	await expect.element(two).toHaveAttribute('aria-checked', 'true');
	await expect.element(screen.getByRole('slider')).toHaveAttribute('aria-valuetext', '70 percent');
	await expect.element(thinking).toHaveValue('An even number is divisible by two.');
	expect(api.postInput).toHaveBeenCalledWith(
		'one',
		expect.objectContaining({
			type: 'answer',
			tool_call_id: 'one',
			answer: expect.objectContaining({
				confidence: 70,
				correct: true,
				thinking: 'An even number is divisible by two.'
			})
		}),
		expect.any(AbortSignal)
	);
});

test('compacting_session_shows_the_indicator_and_disables_send_and_submit', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		compacting: true,
		entries: [questionBatch('one')]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByTestId('compacting-indicator')).toBeVisible();
	await expect.element(screen.getByText('compacting session…')).toBeVisible();
	await screen.getByRole('radio', { name: 'Two' }).click();
	await expect.element(screen.getByRole('button', { name: 'Submit answer' })).toBeDisabled();
});

test('failed_compaction_clears_indicator_without_markers_and_re_enables_answering', async () => {
	const session = {
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach' as const,
		turn_in_flight: false,
		turn_error: null,
		entries: [questionBatch('one')]
	};
	vi.mocked(api.getSession).mockResolvedValue({ ...session, compacting: true });
	vi.mocked(api.postInput).mockResolvedValue();
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByTestId('compacting-indicator')).toBeVisible();
	await screen.getByRole('radio', { name: 'Two' }).click();
	const submit = screen.getByRole('button', { name: 'Submit answer' });
	await expect.element(submit).toBeDisabled();

	vi.mocked(api.getSession).mockResolvedValue({ ...session, compacting: false });
	window.dispatchEvent(new CustomEvent('verstehen:sessions-changed', { detail: 'one' }));
	await expect.element(screen.getByTestId('compacting-indicator')).not.toBeInTheDocument();
	await expect.element(screen.getByTestId('compaction-moment')).not.toBeInTheDocument();
	await expect.element(screen.getByTestId('compaction-cut-divider')).not.toBeInTheDocument();
	await expect.element(submit).toBeEnabled();
	await submit.click();
	expect(api.postInput).toHaveBeenCalledWith(
		'one',
		expect.objectContaining({ type: 'answer', tool_call_id: 'one' }),
		expect.any(AbortSignal)
	);
});

test('saved_compaction_draws_the_moment_line_and_the_cut_divider', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{ kind: 'user', entry_id: 'u1', text: 'first' },
			{ kind: 'user', entry_id: 'u2', text: 'second' },
			{
				kind: 'marker',
				entry_id: 'm',
				marker_type: 'compaction',
				content: 'SECRET SUMMARY',
				display: true,
				details: { first_kept_entry_id: 'u2', last_summarized_entry_id: 'u1', tokens_before: 33000 }
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect
		.element(screen.getByTestId('compaction-moment'))
		.toHaveTextContent('Context compacted');
	await expect
		.element(screen.getByTestId('compaction-cut-divider'))
		.toHaveTextContent('History compacted · 33k tok');
	await expect.element(screen.getByText('SECRET SUMMARY')).not.toBeInTheDocument();
});

test('dispatch_card_follows_the_session_feed_by_tool_call_id', async () => {
	const matching: api.JobRecord = {
		id: 'job',
		session_id: 'one',
		kind: 'research',
		tool_call_id: 'research-call',
		input: {},
		status: 'running',
		activity: 'Matching research activity',
		created_at: new Date().toISOString()
	};
	const unrelated = {
		...matching,
		id: 'other',
		tool_call_id: 'other-call',
		activity: 'Unrelated activity'
	};
	vi.mocked(api.getJobs).mockResolvedValue({ jobs: [unrelated, matching], turn_in_flight: false });
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Research',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [
			{
				kind: 'assistant',
				entry_id: 'dispatch',
				stop_reason: 'stop',
				parts: [
					{
						type: 'tool_call',
						tool_call_id: 'research-call',
						tool_name: 'research',
						arguments: { question: 'Why?' }
					}
				]
			},
			{
				kind: 'tool_result',
				entry_id: 'ack',
				tool_call_id: 'research-call',
				tool_name: 'research',
				text: 'Dispatched.',
				is_error: false
			},
			{
				kind: 'assistant',
				entry_id: 'prose',
				stop_reason: 'stop',
				parts: [{ type: 'text', text: 'While it runs.' }]
			}
		]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect
		.element(screen.getByTestId('dispatch-card'))
		.toMatchTextContent('Matching research activity');
	await expect.element(screen.getByText('Unrelated activity')).not.toBeInTheDocument();
	vi.mocked(api.getJobs).mockResolvedValue({
		jobs: [unrelated, { ...matching, status: 'done' }],
		turn_in_flight: false
	});
	window.dispatchEvent(new CustomEvent('verstehen:jobs-changed', { detail: 'one' }));
	await expect.element(screen.getByTestId('dispatch-settled')).toMatchTextContent('finished');
});

test('android_back_opens_the_dismiss_confirmation_for_a_pending_question_like_escape', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [questionBatch('one')]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByRole('radio', { name: 'Two' })).toBeVisible();
	pressBack();
	await expect.element(screen.getByText('Dismiss this question?')).toBeVisible();
	expect(history.back).not.toHaveBeenCalled();
});

test('android_back_closes_the_open_drawer_instead_of_asking_to_dismiss', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [questionBatch('one')]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByRole('radio', { name: 'Two' })).toBeVisible();
	const drawer = document.createElement('div');
	drawer.dataset.slot = 'sidebar';
	drawer.dataset.mobile = 'true';
	drawer.dataset.state = 'open';
	document.body.append(drawer);
	const escapes = vi.fn((event: KeyboardEvent) => event.key === 'Escape');
	document.addEventListener('keydown', escapes);
	pressBack();
	document.removeEventListener('keydown', escapes);
	drawer.remove();
	expect(escapes).toHaveReturnedWith(true);
	expect(history.back).not.toHaveBeenCalled();
	await expect.element(screen.getByText('Dismiss this question?')).not.toBeInTheDocument();
});

test('android_back_goes_back_when_nothing_is_pending', async () => {
	vi.mocked(api.getSession).mockResolvedValue({
		side_segments: { by_entry: {}, entry_points: {}, current: null },
		id: 'one',
		title: 'Algebra',
		kind: 'teach',
		turn_in_flight: false,
		turn_error: null,
		entries: [{ kind: 'user', entry_id: 'u', text: 'Hello' }]
	});
	const screen = await render(SessionThread, { id: 'one' });
	await expect.element(screen.getByText('Hello', { exact: true })).toBeVisible();
	pressBack();
	expect(history.back).toHaveBeenCalledOnce();
	await expect.element(screen.getByText('Dismiss this question?')).not.toBeInTheDocument();
});
