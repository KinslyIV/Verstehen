import type { RootContent } from 'hast';
import { parseMarkdown } from '#lib/markdown/pipeline.js';
import { recoverToolContent } from '#lib/markdown/tool-content.js';

const inline = new Set(['code', 'em', 'strong', 'del', 'span']);

export function questionPreview(source: string): RootContent[] {
	let stopped = false;
	function prefix(nodes: RootContent[]): RootContent[] {
		const preview: RootContent[] = [];
		for (const node of nodes) {
			if (stopped) break;
			if (node.type === 'text') {
				preview.push({ ...node, value: node.value.replace(/\s+/g, ' ') });
				continue;
			}
			if (node.type !== 'element') continue;
			const classes = node.properties.className;
			if (node.tagName === 'pre' || (Array.isArray(classes) && classes.includes('katex-display'))) {
				stopped = true;
			} else if (node.tagName === 'br' || node.tagName === 'img') {
				preview.push({ type: 'text', value: String(node.properties.alt ?? ' ') });
			} else if (node.tagName === 'code' || (Array.isArray(classes) && classes.includes('katex'))) {
				preview.push(node);
			} else if (inline.has(node.tagName) || node.tagName === 'a') {
				preview.push({
					type: 'element',
					tagName: node.tagName === 'a' ? 'span' : node.tagName,
					properties: {},
					children: prefix(node.children) as typeof node.children
				});
			} else {
				preview.push(...prefix(node.children), { type: 'text', value: ' ' });
			}
		}
		return preview;
	}
	const nodes = prefix(parseMarkdown(recoverToolContent(source), false).children);
	if (stopped) nodes.push({ type: 'text', value: '…' });
	return nodes;
}
