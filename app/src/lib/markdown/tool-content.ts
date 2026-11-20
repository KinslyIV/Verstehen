import {
	canParseTex,
	knownTexCommand,
	mapMathContent,
	numericPercentEscape,
	outsideTexComments,
	recoverDocumentLayout,
	texRanges
} from './content-reader.js';

const DEBRIS: Record<string, string> = {
	'\b': '\\b',
	'\t': '\\t',
	'\v': '\\v',
	'\f': '\\f',
	'\r': '\\r'
};

export function restoreMathEscapes(text: string): string {
	if (!/[\b\t\n\v\f\r]/.test(text)) return text;
	return mapMathContent(text, (body, display) =>
		outsideTexComments(body, (part) => {
			const restored = part.replace(/[\b\t\v\f\r]/g, (char, offset: number) => {
				if (char === '\r' && part[offset + 1] === '\n') return char;
				const suffix = /^[A-Za-z]+/.exec(part.slice(offset + 1))?.[0];
				return suffix && knownTexCommand(DEBRIS[char]!.slice(1) + suffix) ? DEBRIS[char]! : char;
			});
			if (display) return restored;
			return restored.replace(/\n([A-Za-z]+)/g, (whole, suffix: string) =>
				knownTexCommand('n' + suffix) ? '\\n' + suffix : whole
			);
		})
	);
}

const commandSymbol = /[,;:!|{}%]/;

function recoverCommandRuns(inner: string, display: boolean): string {
	const ranges = texRanges(inner);
	const recovered = inner.replace(/\\+/g, (run: string, offset: number) => {
		const contexts = ranges.filter((r) => offset >= r.start && offset < r.end);
		if (contexts.some((r) => r.kind === 'row' || r.kind === 'comment') || run.length % 2 !== 0)
			return run;
		const next = inner[offset + run.length] ?? '';
		const encoded = contexts.filter((r) => r.kind === 'encoded').at(-1);
		const word = /^[A-Za-z]+/.exec(inner.slice(offset + run.length))?.[0];
		if (encoded) {
			const factor = encoded.factor!;
			const rows = run.length % (2 * factor) === 0;
			const command = word ? knownTexCommand(word) : commandSymbol.test(next);
			if (run.length % factor === 0 && (rows || command)) return '\\'.repeat(run.length / factor);
			return run;
		}
		if (next === '%') return numericPercentEscape(inner, offset + run.length) ? '\\' : run;
		if (word) return word.length > 1 && knownTexCommand(word) ? '\\' : run;
		return next && commandSymbol.test(next) ? '\\' : run;
	});
	if (recovered !== inner && !canParseTex(recovered, display) && canParseTex(inner, display))
		return inner;
	return recovered;
}

export function healOverescapedCommands(text: string): string {
	return text.includes('\\\\') ? mapMathContent(text, recoverCommandRuns) : text;
}

export function recoverToolContent(text: string): string {
	return healOverescapedCommands(restoreMathEscapes(recoverDocumentLayout(text)));
}
