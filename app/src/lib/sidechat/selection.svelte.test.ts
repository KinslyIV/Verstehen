import { expect, test } from 'vitest';
import { selectedText, selectionSource } from './selection.js';

function rangeOf(html: string): { root: HTMLElement; range: Range } {
	const root = document.createElement('div');
	root.innerHTML = html;
	document.body.append(root);
	const range = document.createRange();
	range.selectNodeContents(root);
	return { root, range };
}

test('selected_text_reads_formulas_as_tex_and_separates_blocks', () => {
	const { root, range } = rangeOf(
		'<p>Take <span class="katex"><span class="katex-mathml"><math><semantics><mi>x</mi><annotation encoding="application/x-tex">x^2</annotation></semantics></math></span><span>x2</span></span> now</p><p>Next</p>'
	);
	expect(selectedText(range)).toBe('Take $x^2$ now\nNext');
	root.remove();
});

test('selection_source_needs_the_whole_selection_inside_one_teacher_entry', () => {
	const viewport = document.createElement('div');
	viewport.innerHTML =
		'<div data-source-entry-id="a"><p>First</p></div><div data-source-entry-id="b"><p>Second</p></div>';
	document.body.append(viewport);
	const [first, second] = viewport.querySelectorAll('p');
	const selection = window.getSelection()!;
	selection.setBaseAndExtent(first!.firstChild!, 0, first!.firstChild!, 3);
	expect(selectionSource(selection, viewport)?.entryId).toBe('a');
	selection.setBaseAndExtent(first!.firstChild!, 0, second!.firstChild!, 3);
	expect(selectionSource(selection, viewport)).toBeUndefined();
	selection.removeAllRanges();
	viewport.remove();
});
