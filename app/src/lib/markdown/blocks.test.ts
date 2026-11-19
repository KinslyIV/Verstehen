import { expect, test } from 'vitest';
import { parseMarkdownIntoBlocks } from './blocks';
test('blocks_keep_fences_lists_html_and_display_math_together', () => {
	for (const text of [
		'```ts\n\nconst x = 1\n```',
		'- one\n- two',
		'<div>\n\ninside\n\n</div>',
		'$$\na\n\nb\n$$'
	]) {
		expect(parseMarkdownIntoBlocks(text).filter((block) => block.trim())).toEqual([text]);
	}
});
test('footnotes_keep_document_scope', () => {
	const text = 'A note[^one]\n\n[^one]: The note';
	expect(parseMarkdownIntoBlocks(text)).toEqual([text]);
});
