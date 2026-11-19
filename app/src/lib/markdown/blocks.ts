import { Lexer } from 'marked';

// Port of streamdown 2.5.0 parseMarkdownIntoBlocks; see streamdown-LICENSE.
const voidTags = [
	'area',
	'base',
	'br',
	'col',
	'embed',
	'hr',
	'img',
	'input',
	'link',
	'meta',
	'param',
	'source',
	'track',
	'wbr'
];
function openingCount(source: string, tag: string): number {
	if (voidTags.includes(tag.toLowerCase())) return 0;
	return (source.match(new RegExp(`<${tag}(?=[\\s>/])[^>]*>`, 'gi')) ?? []).filter(
		(value) => !value.trimEnd().endsWith('/>')
	).length;
}
function closingCount(source: string, tag: string): number {
	return source.match(new RegExp(`</${tag}(?=[\\s>])[^>]*>`, 'gi'))?.length ?? 0;
}
export function parseMarkdownIntoBlocks(markdown: string): string[] {
	if (/\[\^[\w-]{1,200}\](?!:)/.test(markdown) || /\[\^[\w-]{1,200}\]:/.test(markdown))
		return [markdown];
	const blocks: string[] = [];
	const openTags: string[] = [];
	let lastWasCode = false;
	for (const token of Lexer.lex(markdown, { gfm: true })) {
		const raw = token.raw;
		const last = blocks.length - 1;
		if (openTags.length) {
			blocks[last] += raw;
			const tag = openTags.at(-1)!;
			for (let i = 0; i < openingCount(raw, tag); i++) openTags.push(tag);
			for (let i = 0; i < closingCount(raw, tag); i++) if (openTags.at(-1) === tag) openTags.pop();
			continue;
		}
		if (token.type === 'html' && token.block) {
			const tag = raw.match(/<(\w+)[\s>]/)?.[1];
			if (tag && openingCount(raw, tag) > closingCount(raw, tag)) openTags.push(tag);
		}
		if (last >= 0 && !lastWasCode && (blocks[last].match(/\$\$/g)?.length ?? 0) % 2 === 1) {
			blocks[last] += raw;
			continue;
		}
		blocks.push(raw);
		if (token.type !== 'space') lastWasCode = token.type === 'code';
	}
	return blocks;
}
