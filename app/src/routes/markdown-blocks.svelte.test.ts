import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { tick } from 'svelte';
import Assistant from '#lib/markdown/assistant-message.svelte';
import { parseMarkdown } from '#lib/markdown/pipeline.js';
vi.mock('#lib/markdown/pipeline.js', { spy: true });
test('finished_blocks_are_not_reparsed_or_rerendered_while_the_tail_streams', async () => {
	const screen = await render(Assistant, { content: '**Finished**\n\nTail' });
	await tick();
	vi.mocked(parseMarkdown).mockClear();
	const finished = document.querySelector('.markdown strong');
	const mutations: MutationRecord[] = [];
	const observer = new MutationObserver((records) => mutations.push(...records));
	observer.observe(finished!, {
		childList: true,
		subtree: true,
		characterData: true,
		attributes: true
	});
	await screen.rerender({ content: '**Finished**\n\nTail grows' });
	await tick();
	expect(document.querySelector('.markdown strong')).toBe(finished);
	expect(mutations).toHaveLength(0);
	expect(vi.mocked(parseMarkdown).mock.calls.map((call) => call[0])).toEqual(['Tail grows']);
	observer.disconnect();
});
