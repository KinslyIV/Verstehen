import type { Element, ElementContent, RootContent } from 'hast';
import { toText } from 'hast-util-to-text';

export function texSource(node: RootContent): string {
	if (node.type !== 'element') return '';
	if (node.tagName === 'annotation')
		return node.children.map((n) => (n.type === 'text' ? n.value : '')).join('');
	return node.children.map(texSource).join('');
}

export function tableMarkdown(table: Element): string {
	const rows: string[][] = [];
	function collect(node: RootContent) {
		if (node.type !== 'element') return;
		if (node.tagName === 'tr')
			rows.push(
				node.children
					.filter((n): n is Element => n.type === 'element')
					.map((n) => toText(n).replace(/\|/g, '\\|').replace(/\n/g, ' '))
			);
		else node.children.forEach(collect);
	}
	collect(table);
	return rows
		.flatMap((row, i) => {
			const line = `| ${row.join(' | ')} |`;
			return i === 0 ? [line, `| ${row.map(() => '---').join(' | ')} |`] : [line];
		})
		.join('\n');
}

export function alertContent(node: Element): { kind: string; children: RootContent[] } | null {
	const paragraph = node.children.find((n) => n.type === 'element' && n.tagName === 'p');
	if (paragraph?.type !== 'element' || paragraph.children[0]?.type !== 'text') return null;
	const match = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\n|$)/i.exec(
		paragraph.children[0].value
	);
	if (!match) return null;
	const rest: ElementContent[] = [
		{ type: 'text', value: paragraph.children[0].value.slice(match[0].length) },
		...paragraph.children.slice(1)
	];
	while (
		rest[0] &&
		((rest[0].type === 'text' && !rest[0].value.trim()) ||
			(rest[0].type === 'element' && rest[0].tagName === 'br'))
	)
		rest.shift();
	return {
		kind: match[1].toUpperCase(),
		children: node.children.flatMap((n) =>
			n === paragraph ? (rest.length ? [{ ...paragraph, children: rest }] : []) : [n]
		)
	};
}
