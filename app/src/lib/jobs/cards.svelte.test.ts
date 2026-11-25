import { afterEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { flushSync } from 'svelte';
import type { Entry, JobRecord } from '#lib/api/client.js';
import * as api from '#lib/api/client.js';
import { responseProse } from '#lib/teaching/response-prose.js';
import DispatchCard from './dispatch-card.svelte';
import MarkerCard from './marker-card.svelte';
import JobsPanel from './jobs-panel.svelte';
import { JobsFeed } from './feed.svelte.js';
import { loadSnapshot } from './snapshot.js';
vi.mock('./snapshot.js', () => ({ loadSnapshot: vi.fn() }));

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getJobs: vi.fn(),
	getExtractionStatus: async () => [],
	getSettings: async () => ({}),
	abortJob: vi.fn()
}));
afterEach(() => vi.resetAllMocks());
// Unstyled, a closed dialog is display:none and a demo card could never be near the viewport.
document.head.append(
	Object.assign(document.createElement('style'), { textContent: 'dialog { display: block }' })
);
const job = (patch: Partial<JobRecord> = {}): JobRecord => ({
	id: 'job-1',
	session_id: 'one',
	kind: 'research',
	tool_call_id: 'call-1',
	input: {},
	status: 'running',
	activity: 'Searching for sources',
	created_at: '2026-11-20T00:00:00Z',
	...patch
});
const marker = (kind: string, result: object): Entry => ({
	kind: 'marker',
	entry_id: 'steer_job-1',
	marker_type: 'subagent-steer',
	content: 'Model-facing note',
	display: true,
	details: { kind, result }
});

test('dispatch_card_shows_pending_activity_finished_and_failed', async () => {
	const entry: Extract<Entry, { kind: 'assistant' }> = {
		kind: 'assistant',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_name: 'research',
				tool_call_id: 'call-1',
				arguments: {}
			}
		]
	};
	const result: api.ToolResult = {
		kind: 'tool_result',
		tool_name: 'research',
		tool_call_id: 'call-1',
		text: 'Dispatched',
		is_error: false
	};
	expect(responseProse(entry, undefined, true)).toEqual([]);
	expect(responseProse(entry, new Map([['call-1', result]]), true)).toEqual([
		{ kind: 'job', jobKind: 'research', toolCallId: 'call-1' }
	]);
	const screen = await render(DispatchCard, {
		kind: 'research',
		now: Date.parse('2026-11-20T00:00:03Z')
	});
	await expect.element(screen.getByText('Dispatched…')).toBeVisible();
	await screen.rerender({ job: job() });
	await expect.element(screen.getByText('Searching for sources')).toBeVisible();
	await screen.rerender({ job: job({ status: 'done' }) });
	await expect.element(screen.getByTestId('dispatch-settled')).toMatchTextContent(/finished/);
	await screen.rerender({ job: job({ status: 'error' }) });
	await expect.element(screen.getByTestId('dispatch-settled')).toMatchTextContent(/failed/);
});

test('marker_cards_render_research_pdf_visual_demo_abort_and_failures', async () => {
	const screen = await render(MarkerCard, {
		entry: marker('research', {
			brief: 'Sourced finding',
			sources: [{ title: 'Source', url: 'https://example.com' }]
		}),
		inverted: false,
		oninvert: vi.fn()
	});
	await screen.getByText('view brief').click();
	await expect.element(screen.getByRole('link', { name: 'Source' })).toBeVisible();
	await screen.rerender({
		entry: marker('pdf', { brief: 'Page findings', pages_read: [2], pages_consulted: [2, 3] })
	});
	await expect.element(screen.getByTestId('pdf-complete-badge')).toMatchTextContent(/read 1 page/);
	await screen.getByText('view brief').click();
	await expect.element(screen.getByText('Pages consulted: 2, 3')).toBeVisible();
	await screen.rerender({
		entry: marker('visual', {
			svg: '<svg width="80" height="40"><rect width="80" height="40"/></svg>'
		})
	});
	await expect
		.element(screen.getByRole('switch', { name: 'Invert figure brightness' }))
		.toBeVisible();
	await screen.rerender({ entry: marker('demo', { title: 'Working demo', html: '<p>Demo</p>' }) });
	await expect
		.element(screen.getByTestId('demo-iframe'))
		.toHaveAttribute('sandbox', 'allow-scripts');
	await screen.rerender({
		entry: marker('demo', { title: 'Failed', html: '', notes: 'Browser unavailable' })
	});
	await expect
		.element(screen.getByTestId('demo-card-failed'))
		.toMatchTextContent(/Browser unavailable/);
	await screen.rerender({ entry: marker('visual', { svg: '', notes: 'Drawing failed' }) });
	await expect
		.element(screen.getByTestId('visual-card-failed'))
		.toMatchTextContent(/Drawing failed/);
	await screen.rerender({
		entry: marker('research', { brief: 'Research failed: unavailable', sources: [] })
	});
	await expect.element(screen.getByTestId('research-brief-card')).toMatchTextContent(/failed/);
	await screen.rerender({
		entry: {
			kind: 'marker',
			marker_type: 'subagent-abort',
			content: '',
			display: true,
			details: { kind: 'research' }
		}
	});
	await expect
		.element(screen.getByTestId('job-aborted-badge'))
		.toMatchTextContent(/aborted by the learner/);
	await screen.rerender({
		entry: {
			kind: 'marker',
			marker_type: 'subagent-abort',
			content: '',
			display: true,
			details: { failure: 'Delivery failed' }
		}
	});
	await expect.element(screen.getByRole('alert')).toMatchTextContent(/Delivery failed/);
});

test.each([undefined, 404, 409, 500])('jobs_panel_end_states_%s', async (status) => {
	const feed = new JobsFeed('one', vi.fn());
	flushSync(() => {
		feed.jobs = [job()];
	});
	vi.mocked(api.getJobs).mockResolvedValue({ turn_in_flight: false, jobs: [] });
	let finish!: () => void;
	vi.mocked(api.abortJob).mockImplementation(
		() =>
			new Promise<void>((resolve, reject) => {
				finish = () => (status ? reject(new api.ApiError(status, undefined, 'Failed')) : resolve());
			})
	);
	const screen = await render(JobsPanel, { feed, title: 'Lesson' });
	try {
		await expect.element(screen.getByTestId('job-cost')).toHaveTextContent('—');
		await screen.getByRole('button', { expanded: false }).click();
		await expect.element(screen.getByTestId('job-detail')).toMatchTextContent(/Researcher/);
		await screen.getByTestId('job-end').click();
		await expect.element(screen.getByTestId('job-end')).toBeDisabled();
		await expect.element(screen.getByText('Stopping…')).toBeVisible();
		finish();
		if (status === 500) {
			await expect.element(screen.getByText('Abort failed — try again')).toBeVisible();
			await expect.element(screen.getByTestId('job-end')).toBeDisabled();
		} else {
			await expect.element(screen.getByTestId('job-row')).not.toBeInTheDocument();
		}
	} finally {
		feed.dispose();
	}
});

test('jobs_feed_debounces_announcements_and_syncs_only_a_seen_settlement', async () => {
	vi.useFakeTimers();
	const settled = vi.fn();
	const feed = new JobsFeed('one', settled);
	try {
		vi.mocked(api.getJobs).mockResolvedValue({
			turn_in_flight: false,
			jobs: [job({ status: 'done' })]
		});
		await feed.refresh();
		expect(settled).not.toHaveBeenCalled();
		vi.mocked(api.getJobs).mockResolvedValue({ turn_in_flight: false, jobs: [job()] });
		feed.schedule();
		feed.schedule();
		await vi.advanceTimersByTimeAsync(249);
		expect(api.getJobs).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect(api.getJobs).toHaveBeenCalledTimes(2);
		vi.mocked(api.getJobs).mockResolvedValue({
			turn_in_flight: false,
			jobs: [job({ status: 'done' })]
		});
		await feed.refresh();
		expect(settled).toHaveBeenCalledOnce();
		await feed.refresh();
		expect(settled).toHaveBeenCalledOnce();
	} finally {
		feed.dispose();
		vi.useRealTimers();
	}
});

test('photo_snapshot_is_not_refetched_when_the_session_record_refreshes', async () => {
	vi.mocked(loadSnapshot).mockResolvedValue(
		'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf1sAAAAASUVORK5CYII='
	);
	const photo = () =>
		marker('visual', {
			svg: '<svg width="10" height="10"><image href="learner-image" width="10" height="10"/></svg>',
			image: { path: '/tmp/photo.png', snapshot_id: 'a'.repeat(64) }
		});
	const screen = await render(MarkerCard, { entry: photo(), inverted: true, oninvert: vi.fn() });
	await expect.element(screen.getByRole('img')).toBeVisible();
	await screen.rerender({ entry: photo() });
	await expect.element(screen.getByRole('img')).toBeVisible();
	expect(loadSnapshot).toHaveBeenCalledOnce();
	await expect.element(screen.getByRole('switch')).not.toBeInTheDocument();
});

test('demo_zoom_opens_in_place_holds_its_height_and_closes_on_escape_message_from_its_frame', async () => {
	const screen = await render(MarkerCard, {
		entry: marker('demo', { title: 'Working demo', html: '<p>Demo</p>' }),
		inverted: false,
		oninvert: vi.fn()
	});
	const card = screen.getByTestId('demo-card').element() as HTMLDialogElement;
	await expect.element(screen.getByTestId('demo-iframe')).toBeInTheDocument();
	const frame = screen.getByTestId('demo-iframe').element() as HTMLIFrameElement;
	(screen.getByTestId('demo-zoom').element() as HTMLButtonElement).click();
	expect(card.open).toBe(true);
	expect(card.matches(':modal')).toBe(true);
	expect(screen.getByTestId('demo-iframe').element()).toBe(frame);
	await expect.element(screen.getByTestId('demo-spacer')).toBeInTheDocument();
	window.dispatchEvent(
		new MessageEvent('message', { data: { type: 'demo-escape' }, source: window })
	);
	expect(card.open).toBe(true);
	window.dispatchEvent(
		new MessageEvent('message', { data: { type: 'demo-escape' }, source: frame.contentWindow })
	);
	expect(card.open).toBe(false);
	await expect.element(screen.getByTestId('demo-spacer')).not.toBeInTheDocument();
	expect(screen.getByTestId('demo-iframe').element()).toBe(frame);
});

test('figure_zoom_opens_a_popup_with_the_figure_and_closes_with_its_button', async () => {
	const screen = await render(MarkerCard, {
		entry: marker('visual', {
			svg: '<svg width="80" height="40"><rect width="80" height="40"/></svg>'
		}),
		inverted: false,
		oninvert: vi.fn()
	});
	await expect
		.element(screen.getByRole('img', { name: 'Enlarged figure' }))
		.not.toBeInTheDocument();
	await screen.getByRole('button', { name: 'Zoom figure' }).click();
	await expect.element(screen.getByRole('img', { name: 'Enlarged figure' })).toBeVisible();
	await screen.getByRole('button', { name: 'Close zoomed view' }).click();
	await expect
		.element(screen.getByRole('img', { name: 'Enlarged figure' }))
		.not.toBeInTheDocument();
});
