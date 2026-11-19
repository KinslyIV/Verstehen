import { expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import { tick } from 'svelte';
import { setMode } from 'mode-watcher';
import Assistant from '#lib/markdown/assistant-message.svelte';
import Learner from '#lib/markdown/learner-message.svelte';
import { completeFixture, streamingFixture } from '#lib/markdown/fixtures.js';
import './layout.css';

function annotations() {
	return [...document.querySelectorAll('annotation')].map((n) => n.textContent);
}

test('single_newlines_break_but_code_and_lists_keep_structure', async () => {
	await render(Assistant, { content: 'one\ntwo\n\n- alpha\n- beta\n\n```text\na\nb\n```' });
	expect(document.querySelectorAll('br')).toHaveLength(1);
	expect(document.querySelectorAll('li')).toHaveLength(2);
	await expect.element(page.getByTestId('md-code')).toBeVisible();
});

test('cjk_emphasis_and_literal_link_boundaries_match_lh', async () => {
	await render(Assistant, {
		content: '中文**「重点」**。日本語**「大切」**。한국어**「중요」**.\nhttps://example.com。后续'
	});
	expect(document.querySelectorAll('strong')).toHaveLength(3);
	await page.getByRole('link', { name: 'https://example.com', exact: true }).click();
	await expect
		.element(page.getByRole('link', { name: 'Open link' }))
		.toHaveAttribute('href', 'https://example.com/');
});

test('single_dollar_legacy_and_less_than_math_preserve_tex_and_currency', async () => {
	await render(Assistant, {
		content: String.raw`$a<b$ \(x^2\) \[y^2\] A price: $5.`,
		streaming: false
	});
	expect(annotations()).toEqual(['a<b', 'x^2', 'y^2']);
	expect(document.body.textContent).toContain('$5');
	expect(document.querySelectorAll('.katex-error')).toHaveLength(0);
});

test('hardening_removes_scripts_events_unsafe_links_and_all_images', async () => {
	await render(Assistant, {
		content:
			'<script>alert(1)</script><b onclick="alert(1)">safe</b>\n\n[unsafe](javascript:alert) ![remote](https://example.com/a) ![data](data:image/png;base64,AAAA)'
	});
	expect(
		document.querySelectorAll('.markdown script, .markdown [onclick], .markdown img')
	).toHaveLength(0);
	expect(document.body.textContent).toContain('[blocked]');
	expect(document.body.textContent).not.toContain('alert(1)');
});

test('learner_text_keeps_whitespace_and_markdown_literal', async () => {
	const content = '**literal**\n  <b>text</b> $a$';
	await render(Learner, { content });
	expect(document.querySelector('[data-slot="message-content"]')?.textContent).toBe(content);
	expect(document.querySelectorAll('strong, b, .katex')).toHaveLength(0);
});

for (const theme of ['dark', 'light'] as const)
	test(`streaming_prefixes_update_the_same_renderer_without_losing_less_than_text_${theme}`, async () => {
		setMode(theme);
		document.documentElement.classList.toggle('dark', theme === 'dark');
		await tick();
		const screen = await render(Assistant, { content: '' });
		for (const source of [
			'$a',
			'$a<',
			'$a<b',
			'$a<b TAIL',
			'$a<b$ TAIL',
			'before <b TAIL',
			'**bold TAIL'
		]) {
			await screen.rerender({ content: source });
			await tick();
			if (source.includes('TAIL')) expect(document.body.textContent).toContain('TAIL');
			if (source.includes('<b')) expect(document.body.textContent).toContain('<b');
		}
		expect(document.querySelector('strong')?.textContent).toBe('bold TAIL');
		for (let i = 0; i <= streamingFixture.length; i++) {
			await screen.rerender({ content: streamingFixture.slice(0, i) });
			await tick();
			expect(
				document.querySelectorAll('.markdown script, .markdown img, .katex-error')
			).toHaveLength(0);
		}
		expect(annotations()).toEqual(['a<b']);
	});

for (const theme of ['dark', 'light']) {
	for (const [name, content] of [
		['complete', completeFixture],
		['streaming', streamingFixture]
	]) {
		test(`markdown_fixture_${name}_${theme}`, async () => {
			await page.viewport(1280, 1400);
			setMode(theme as 'dark' | 'light');
			document.documentElement.classList.toggle('dark', theme === 'dark');
			await tick();
			const screen = await render(Assistant, { content });
			screen.container.style.cssText =
				'max-width:760px;margin:32px auto;padding:24px;background:var(--background);color:var(--foreground)';
			if (name === 'complete')
				await expect
					.poll(() => document.querySelector('[data-testid="md-mermaid"] svg'), { timeout: 15000 })
					.toBeTruthy();
			expect(document.documentElement.classList.contains('dark')).toBe(theme === 'dark');
			await document.fonts.ready;
			await page.screenshot({
				path: `../../markdown-output/${name}-${theme}.png`,
				element: screen.container
			});
			expect(document.querySelectorAll('.katex-error')).toHaveLength(0);
		});
	}
}

test('mermaid_renders_a_valid_graph', async () => {
	const { renderMermaid } = await import('#lib/markdown/mermaid-render.js');
	const svg = await renderMermaid('graph LR\n A --> B', true);
	expect(svg).toContain('<svg');
});

test('block_controls_copy_literal_code_tex_and_markdown_table', async () => {
	const copy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
	const source = 'const a = 1;\nconst b = 2;';
	const screen = await render(Assistant, {
		content:
			'```js startLine=7\n' + source + '\n```\n\n$$\nx^2\n$$\n\n| a | b |\n|---|---|\n| 1 | 2 |'
	});
	await expect.poll(() => document.querySelector('.code-line')?.textContent).toBe('7const a = 1;');
	await page.getByRole('button', { name: 'Copy code', exact: true }).click();
	expect(copy).toHaveBeenLastCalledWith(source);
	await page.getByRole('button', { name: 'Copy TeX', exact: true }).click();
	expect(copy).toHaveBeenLastCalledWith('x^2');
	await page.getByRole('button', { name: 'Copy table', exact: true }).click();
	expect(copy).toHaveBeenLastCalledWith('| a | b |\n| --- | --- |\n| 1 | 2 |');
	await screen.rerender({ content: '```unknown-language noLineNumbers\n' + source + '\n```' });
	await expect.poll(() => document.querySelector('.code-line')?.textContent).toBe('const a = 1;');
	copy.mockRestore();
});

test('mermaid_streaming_updates_render_latest_source_and_recover_after_error', async () => {
	const screen = await render(Assistant, {
		content: '```mermaid\ngraph LR\n A --> B',
		streaming: true
	});
	await expect.poll(() => document.querySelector('[data-testid="md-mermaid"] svg')).toBeTruthy();
	await screen.rerender({ content: '```mermaid\ngraph LR\n A --> C' });
	await expect
		.poll(() => document.querySelector('[data-testid="md-mermaid"] svg')?.textContent)
		.toContain('C');
	await screen.rerender({ content: '```mermaid\nnot a diagram' });
	await expect.element(page.getByText('Diagram failed to render')).toBeVisible();
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect.element(page.getByText('Diagram failed to render')).toBeVisible();
	await screen.rerender({ content: '```mermaid\ngraph LR\n A --> D' });
	await expect
		.poll(() => document.querySelector('[data-testid="md-mermaid"] svg')?.textContent)
		.toContain('D');
});

test('long_stream_keeps_finalized_dom_stable', async () => {
	const prefix =
		Array.from({ length: 50 }, (_, i) => `Paragraph ${i}: **Explain the idea** with $x^2$.`).join(
			'\n\n'
		) + '\n\n';
	const screen = await render(Assistant, { content: prefix });
	const first = document.querySelector('.markdown p');
	for (let i = 0; i <= 50; i++)
		await screen.rerender({ content: prefix + streamingFixture.slice(0, i) });
	expect(document.querySelector('.markdown p')).toBe(first);
	expect(document.querySelectorAll('.katex-error')).toHaveLength(0);
	expect(annotations()).toHaveLength(51);
});

test('all_five_alert_markers_are_case_insensitive_and_require_a_marker_line', async () => {
	const content =
		['note', 'TIP', 'Important', 'warning', 'CAUTION']
			.map((kind) => `> [!${kind}]\n> Explain why.`)
			.join('\n\n') + '\n\n> [!NOTE] inline prose stays a quote';
	await render(Assistant, { content });
	expect(document.querySelectorAll('.markdown aside')).toHaveLength(5);
	expect(document.querySelector('blockquote')?.textContent).toContain('[!NOTE] inline prose');
});

test('streaming_code_prefixes_keep_dollars_and_legacy_delimiters_literal', async () => {
	const screen = await render(Assistant, { content: '' });
	const source = '```text\n$a<b$ and \\(x\\)\n```';
	for (let i = 8; i <= source.length; i++) {
		await screen.rerender({ content: source.slice(0, i) });
		expect(annotations()).toEqual([]);
	}
	await expect
		.poll(() => document.querySelector('[data-testid="md-code"] code')?.textContent)
		.toContain('$a<b$ and \\(x\\)');
});
