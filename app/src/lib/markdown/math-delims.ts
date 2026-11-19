import { readContentSpans } from './content-reader';
const escaped = (text: string, i: number) => {
	let n = 0;
	while (i > 0 && text[--i] === '\\') n++;
	return n % 2 === 1;
};

function indented(text: string, i: number): boolean {
	const prefix = text.slice(text.lastIndexOf('\n', i - 1) + 1, i);
	return prefix.length > 0 && /^[ \t]+$/.test(prefix);
}
function blockPosition(text: string, i: number): boolean {
	return /^[ \t]*$/.test(text.slice(text.lastIndexOf('\n', i - 1) + 1, i));
}

function replaceEscapedDollars(content: string): string {
	let out = '';
	for (let i = 0; i < content.length; i++) {
		if (content[i] === '\\' && content[i + 1] === '$' && !escaped(content, i)) {
			out += '\\text{\\textdollar}';
			i++;
		} else out += content[i];
	}
	return out;
}

export function transformMathDelimiters(markdown: string): string {
	let offset = 0;
	return readContentSpans(markdown)
		.map((span) => {
			const start = offset;
			offset += span.raw.length;
			if (span.kind !== 'math') return span.raw;
			if (span.open === '$') return '$' + replaceEscapedDollars(span.body) + span.close;
			if (span.open !== '\\(' && span.open !== '\\[') return span.raw;
			const body = span.body.trim();
			if (!body) return span.raw;
			if (span.open === '\\(') return `$$${body}$$`;
			if (indented(markdown, start)) return `$$${body.replace(/\s*\n\s*/g, ' ')}$$`;
			const before = blockPosition(markdown, start) ? '' : '\n\n';
			const end = start + span.raw.length;
			const after = end === markdown.length || markdown[end] === '\n' ? '' : '\n\n';
			return `${before}$$\n${body}\n$$${after}`;
		})
		.join('');
}
