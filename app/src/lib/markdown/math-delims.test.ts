import { describe, it, expect } from 'vitest';
import { transformMathDelimiters } from './math-delims';
describe('math delimiter transform (pure unit)', () => {
	it('converts inline \\(...\\) to the two-dollar inline form', () => {
		expect(transformMathDelimiters('a \\(x^2\\) b')).toBe('a $$x^2$$ b');
	});

	it('converts block-positioned \\[...\\] to flow math in place', () => {
		expect(transformMathDelimiters('text\n\n\\[\n\\int x\n\\]\n\nmore')).toBe(
			'text\n\n$$\n\\int x\n$$\n\nmore'
		);
	});

	it('pads mid-paragraph \\[...\\) with blank lines (forces a clean block)', () => {
		expect(transformMathDelimiters('mid \\[x^2\\] para')).toBe('mid \n\n$$\nx^2\n$$\n\n para');
	});

	it('degrades indented display math (list items) to the inline form', () => {
		expect(transformMathDelimiters('- item\n  \\[\n  x^2\n  \\]\n- next')).toBe(
			'- item\n  $$x^2$$\n- next'
		);
	});

	it('leaves currency untouched', () => {
		const md = 'It costs $5 and $10 more. $$big$$ sums too.';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it('leaves escaped delimiters untouched (\\\\( is a literal backslash)', () => {
		expect(transformMathDelimiters('escaped \\\\( and \\\\[ stay')).toBe(
			'escaped \\\\( and \\\\[ stay'
		);
	});

	it('does not transform inside fenced code blocks', () => {
		const md = '```js\n\\(x\\) and \\[y\\]\n```';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it('does not transform inside inline code spans', () => {
		const md = 'run `\\(x\\)` locally';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it('leaves unbalanced delimiters untouched (mid-stream chunks)', () => {
		expect(transformMathDelimiters('partial \\[ mid-stream')).toBe('partial \\[ mid-stream');
		expect(transformMathDelimiters('open \\( no close')).toBe('open \\( no close');
	});

	it('still converts a later balanced pair when an earlier one is unbalanced', () => {
		expect(transformMathDelimiters('\\[ partial\n\nbut \\(ok\\)')).toBe(
			'\\[ partial\n\nbut $$ok$$'
		);
	});
});

describe('escaped dollars inside math — transform units', () => {
	it('replaces \\$ inside a balanced inline span', () => {
		expect(transformMathDelimiters('It costs $x = \\$5$ at market.')).toBe(
			'It costs $x = \\text{\\textdollar}5$ at market.'
		);
	});

	it('replaces every escaped dollar in the span, including the \\text{\\$} form', () => {
		expect(transformMathDelimiters('$\\$3 + \\text{\\$}4 = \\$7$ exactly.')).toBe(
			'$\\text{\\textdollar}3 + \\text{\\text{\\textdollar}}4 = \\text{\\textdollar}7$ exactly.'
		);
	});

	it('does NOT replace even-backslash dollars (row break + dollar keeps closing)', () => {
		const md = '$a\\\\$b$ tail';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it('leaves prose escaped dollars and bare currency untouched', () => {
		const md = 'It costs \\$5 flat, then $5 and $10 more.';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it("leaves display spans untouched — a lone $ can't close $$, \\$ already survives", () => {
		const md = '$$x = \\$5,\\ q = \\$12$$';
		expect(transformMathDelimiters(md)).toBe(md);
	});

	it('leaves code spans, fences, and unbalanced spans untouched', () => {
		expect(transformMathDelimiters('Type `$x = \\$5$` literally.')).toBe(
			'Type `$x = \\$5$` literally.'
		);
		expect(transformMathDelimiters('```\n$x = \\$5$\n```')).toBe('```\n$x = \\$5$\n```');
		expect(transformMathDelimiters('Broken: $x = \\$5')).toBe('Broken: $x = \\$5');
	});

	it('clean spans stay byte-identical; only the escape-bearing span changes', () => {
		const md = '$a$ costs $5\\$10$ and $b$';
		expect(transformMathDelimiters(md)).toBe('$a$ costs $5\\text{\\textdollar}10$ and $b$');
	});
});
