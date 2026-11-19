import { fromMarkdown } from 'mdast-util-from-markdown';
import { mathFromMarkdown } from 'mdast-util-math';
import { math } from 'micromark-extension-math';

export type ContentSpan =
	| { kind: 'prose'; raw: string }
	| { kind: 'code'; raw: string; escapedFence?: true }
	| { kind: 'math'; raw: string; open: string; body: string; close: string; display: boolean };
const blankLine = /^\r?\n[ \t]*\r?\n/;
const escaped = (text: string, i: number) => {
	let n = 0;
	while (i > 0 && text[--i] === '\\') n++;
	return n % 2 === 1;
};
const runLength = (text: string, i: number, char: string) => {
	let n = 0;
	while (text[i + n] === char) n++;
	return n;
};
type MarkdownNode = {
	type: string;
	position?: { start: { offset?: number }; end: { offset?: number } };
	children?: MarkdownNode[];
};
type LiteralRange = { start: number; end: number; escapedFence?: true };

function escapedFenceRanges(
	text: string,
	native: LiteralRange[]
): { fences: LiteralRange[]; native: LiteralRange[] } {
	if (!text.includes('\\n') || !/`{3,}|~{3,}/.test(text)) return { fences: [], native };
	const lines: Array<{ start: number; end: number }> = [];
	let start = 0;
	for (const match of text.matchAll(/\r\n?|\n|(\\+)(r\\n|n)?/g)) {
		if (match[1] && (!match[2] || match[1].length % 2 === 0)) continue;
		const boundary = match.index + (match[1] ? match[1].length - 1 : 0);
		lines.push({ start, end: boundary });
		start = match.index + match[0].length;
	}
	lines.push({ start, end: text.length });
	const ranges: LiteralRange[] = [];
	const protect = (start: number, end: number, complete: boolean) => {
		const fenceStart = start + /^ {0,3}/.exec(text.slice(start, start + 3))![0].length;

		if (
			!native.some(
				(literal) =>
					literal.start <= fenceStart &&
					literal.end > start &&
					(literal.start < start || literal.end > end)
			)
		) {
			ranges.push({ start, end, ...(complete ? { escapedFence: true as const } : {}) });
			if (
				native.some((literal) => literal.start >= start && literal.start < end && literal.end > end)
			) {
				native = [
					...native.filter((literal) => literal.start < start),
					...nativeLiteralRanges(text.slice(end), end)
				];
			}
		}
	};
	let opening: { start: number; fence: string } | undefined;
	for (const line of lines) {
		const value = text.slice(line.start, line.end);
		if (!opening) {
			const match = /^[ ]{0,3}(`{3,}|~{3,})(.*)$/.exec(value);
			if (!match || (match[1]![0] === '`' && match[2]!.includes('`'))) continue;

			if (native.some((range) => range.start < line.start && range.end > line.start)) continue;
			opening = { start: line.start, fence: match[1]! };
			continue;
		}
		const close = /^[ ]{0,3}(`{3,}|~{3,})[ \t]*$/.exec(value)?.[1];
		if (!close || close[0] !== opening.fence[0] || close.length < opening.fence.length) continue;
		protect(opening.start, line.end, true);
		opening = undefined;
	}

	if (opening) protect(opening.start, text.length, false);
	return { fences: ranges, native };
}

function nativeLiteralRanges(text: string, offset = 0): LiteralRange[] {
	const pending: MarkdownNode[] = [
		fromMarkdown(text, {
			extensions: [math({ singleDollarTextMath: true })],
			mdastExtensions: [mathFromMarkdown()]
		})
	];
	const ranges: LiteralRange[] = [];
	while (pending.length) {
		const node = pending.pop()!;
		if (node.type === 'code' || node.type === 'inlineCode') {
			const start = node.position?.start.offset,
				end = node.position?.end.offset;
			if (start !== undefined && end !== undefined)
				ranges.push({ start: start + offset, end: end + offset });
		} else if (node.children) pending.push(...node.children);
	}
	return ranges;
}

function literalRanges(text: string): LiteralRange[] {
	const { fences, native } = escapedFenceRanges(text, nativeLiteralRanges(text));

	return [
		...native.filter(
			(range) => !fences.some((fence) => fence.start <= range.start && range.start < fence.end)
		),
		...fences
	].sort((a, b) => a.start - b.start);
}

export function readContentSpans(text: string): ContentSpan[] {
	const spans: ContentSpan[] = [];
	const literals = literalRanges(text);
	let literal = 0,
		i = 0,
		plain = 0;
	const opaque = ({ end, escapedFence }: LiteralRange) => {
		if (plain < i) spans.push({ kind: 'prose', raw: text.slice(plain, i) });
		spans.push({
			kind: 'code',
			raw: text.slice(i, end),
			...(escapedFence ? { escapedFence } : {})
		});
		i = plain = end;
	};
	while (i < text.length) {
		while (literal < literals.length && literals[literal]!.end <= i) literal++;
		const barrier = literals[literal]?.start ?? Infinity;
		if (i >= barrier) {
			opaque(literals[literal]!);
			continue;
		}
		let open = '',
			close = '',
			display = false,
			after = -1,
			at = -1;
		if (text[i] === '\\' && !escaped(text, i) && ['(', '['].includes(text[i + 1] ?? '')) {
			open = text.slice(i, i + 2);
			close = open === '\\(' ? '\\)' : '\\]';
			display = open === '\\[';
			for (let j = i + 2; j < text.length - 1; j++) {
				if (j >= barrier || (!display && blankLine.test(text.slice(j)))) break;
				if (text.startsWith(close, j) && !escaped(text, j)) {
					at = j;
					after = j + 2;
					break;
				}
			}
		} else if (text[i] === '$' && !escaped(text, i)) {
			const size = runLength(text, i, '$');
			open = '$'.repeat(size);
			const eol = text.indexOf('\n', i + size);
			const before = text.slice(text.lastIndexOf('\n', i - 1) + 1, i);
			display =
				size >= 2 &&
				/^[ \t]{0,3}$/.test(before) &&
				!text.slice(i + size, eol < 0 ? text.length : eol).includes('$');
			if (display) {
				let start = eol;
				while (start >= 0 && start < text.length) {
					start++;
					const next = text.indexOf('\n', start);
					const match = /^([ \t]{0,3})(\$+)[ \t]*\r?$/.exec(
						text.slice(start, next < 0 ? text.length : next)
					);
					if (match && match[2]!.length >= size) {
						at = start + match[1]!.length;
						close = match[2]!;
						after = at + close.length;
						break;
					}
					start = next;
				}
			} else {
				for (let j = i + size; j < text.length;) {
					if (j >= barrier || blankLine.test(text.slice(j))) break;
					if (text[j] === '$' && !escaped(text, j)) {
						const n = runLength(text, j, '$');
						if (n === size) {
							at = j;
							close = open;
							after = j + n;
							break;
						}
						j += n;
					} else j++;
				}
			}
		}
		if (at >= 0) {
			if (plain < i) spans.push({ kind: 'prose', raw: text.slice(plain, i) });
			spans.push({
				kind: 'math',
				raw: text.slice(i, after),
				open,
				body: text.slice(i + open.length, at),
				close,
				display
			});
			i = plain = after;
		} else i += open.length || 1;
	}
	if (plain < text.length) spans.push({ kind: 'prose', raw: text.slice(plain) });
	return spans;
}
