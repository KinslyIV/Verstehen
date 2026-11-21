import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import * as api from '#lib/api/client.js';
import { SideChatFeed } from './feed.svelte.js';
import SideChatPanel from './side-chat-panel.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSideChats: vi.fn(),
	askSideChat: vi.fn(),
	streamSideChat: vi.fn(),
	stopSideChat: vi.fn()
}));

const user = (text: string) => ({
	id: text,
	role: 'user' as const,
	text,
	stopped: false,
	pending: false
});
const helper = (text: string, extra = {}) => ({
	id: `answer ${text}`,
	role: 'assistant' as const,
	text,
	stopped: false,
	pending: false,
	...extra
});
const thread = (segment: string, messages: api.SideExchange[] = []): api.SideThread => ({
	id: `side_${segment}`,
	anchor: { entry_id: segment, block_text: '' },
	messages
});

let current = 'b';
const feedFor = (threads: api.SideThread[] = []) => {
	const feed = new SideChatFeed(
		'one',
		() => current,
		() => ''
	);
	feed.threads = threads;
	return feed;
};

beforeEach(() => {
	current = 'b';
	vi.mocked(api.askSideChat).mockReset();
	vi.mocked(api.streamSideChat).mockReset().mockResolvedValue(true);
	vi.mocked(api.stopSideChat).mockReset().mockResolvedValue();
});

test('an_empty_thread_asks_for_a_first_side_question', async () => {
	const screen = await render(SideChatPanel, { feed: feedFor() });
	await expect
		.element(screen.getByRole('textbox', { name: 'Side question' }))
		.toHaveAttribute('placeholder', 'Ask a side question…');
	await expect.element(screen.getByRole('button', { name: 'Send side question' })).toBeDisabled();
	await expect
		.element(screen.getByRole('button', { name: 'Retry answer' }))
		.not.toBeInTheDocument();
});

test('a_streaming_answer_shows_answering_until_text_arrives_and_offers_stop', async () => {
	const feed = feedFor([thread('b', [user('Why?')])]);
	feed.live = { side_b: '' };
	const screen = await render(SideChatPanel, { feed });
	await expect.element(screen.getByText('Answering')).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: 'Retry answer' }))
		.not.toBeInTheDocument();
	feed.live = { side_b: 'Because **reasons**' };
	await expect.element(screen.getByText('reasons')).toBeVisible();
	await expect.element(screen.getByText('Answering')).not.toBeInTheDocument();
	await screen.getByRole('button', { name: 'Stop side answer' }).click();
	expect(api.stopSideChat).toHaveBeenCalledWith('one', 'side_b');
});

test('a_stopped_answer_keeps_its_text_and_says_stopped', async () => {
	const feed = feedFor([thread('b', [user('Why?'), helper('Partial text', { stopped: true })])]);
	const screen = await render(SideChatPanel, { feed });
	await expect.element(screen.getByText('Partial text')).toBeVisible();
	await expect.element(screen.getByText('Stopped')).toBeVisible();
	await expect
		.element(screen.getByRole('button', { name: 'Retry answer' }))
		.not.toBeInTheDocument();
});

test('a_failed_answer_shows_its_error_and_retry_asks_again_on_the_same_thread', async () => {
	const failed = thread('b', [user('Why?'), helper('', { error: 'Provider failed' })]);
	const feed = feedFor([failed]);
	vi.mocked(api.askSideChat).mockResolvedValue(failed);
	const screen = await render(SideChatPanel, { feed });
	await expect.element(screen.getByText('Provider failed')).toBeVisible();
	await screen.getByRole('button', { name: 'Retry answer' }).click();
	expect(api.askSideChat).toHaveBeenCalledWith(
		'one',
		expect.objectContaining({ retry: true, thread_id: 'side_b', text: '' }),
		expect.anything()
	);
});

test('a_failed_ask_keeps_the_question_in_the_draft', async () => {
	const feed = feedFor();
	vi.mocked(api.askSideChat).mockRejectedValue(new api.ApiError(409, undefined, 'Still answering'));
	const screen = await render(SideChatPanel, { feed });
	const input = screen.getByRole('textbox', { name: 'Side question' });
	await input.fill('What is slope?');
	await screen.getByRole('button', { name: 'Send side question' }).click();
	await expect.element(screen.getByText('Still answering')).toBeVisible();
	await expect.element(input).toHaveValue('What is slope?');
});

test('drafts_are_kept_per_thread', async () => {
	const feed = feedFor([thread('a', [user('Earlier')]), thread('b')]);
	const screen = await render(SideChatPanel, { feed });
	const input = screen.getByRole('textbox', { name: 'Side question' });
	await input.fill('Draft for b');
	feed.open('a');
	await expect.element(input).toHaveValue('');
	await input.fill('Draft for a');
	feed.goToCurrentStep();
	await expect.element(input).toHaveValue('Draft for b');
	feed.open('a');
	await expect.element(input).toHaveValue('Draft for a');
});

test('go_to_current_step_appears_only_off_the_current_segment', async () => {
	const feed = feedFor([thread('a', [user('Earlier')]), thread('b')]);
	const screen = await render(SideChatPanel, { feed });
	await expect.element(screen.getByTestId('side-current-step')).not.toBeInTheDocument();
	feed.open('a');
	await expect.element(screen.getByTestId('side-current-step')).toBeVisible();
	await screen.getByTestId('side-current-step').click();
	await expect.element(screen.getByTestId('side-current-step')).not.toBeInTheDocument();
	expect(feed.segmentId).toBe('b');
});
