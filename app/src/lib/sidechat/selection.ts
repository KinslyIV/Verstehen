const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, pre, tr, blockquote, div';

/** The selected text with formulas as their TeX source and a newline after each block. */
export function selectedText(range: Range): string {
	const holder = document.createElement('div');
	holder.append(range.cloneContents());
	for (const formula of holder.querySelectorAll('.katex')) {
		const tex = formula.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
		const display = formula.closest('.katex-display');
		formula.replaceWith(tex ? (display ? `$$${tex}$$` : `$${tex}$`) : '');
	}
	holder.querySelectorAll('.katex-display').forEach((display) => display.append('\n'));
	holder.querySelectorAll(BLOCKS).forEach((block) => block.append('\n'));
	return (holder.textContent ?? '').replace(/\n{2,}/g, '\n').trim();
}

/** The entry whose teacher prose holds the whole selection, if it sits in one entry inside `viewport`. */
export function selectionSource(
	selection: Selection | null,
	viewport: HTMLElement
): { entryId: string; range: Range } | undefined {
	if (!selection || selection.isCollapsed || selection.rangeCount === 0) return;
	const range = selection.getRangeAt(0);
	const sourceOf = (node: Node) =>
		(node instanceof Element ? node : node.parentElement)?.closest<HTMLElement>(
			'[data-source-entry-id]'
		);
	const start = sourceOf(range.startContainer);
	if (!start || start !== sourceOf(range.endContainer) || !viewport.contains(start)) return;
	return { entryId: start.dataset.sourceEntryId!, range };
}
