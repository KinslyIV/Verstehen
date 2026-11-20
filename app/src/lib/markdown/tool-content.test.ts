import { expect, test } from 'vitest';
import { recoverToolContent } from './tool-content.js';

test('a_complete_extra_encoded_standalone_fence_decodes_once', () => {
	const decoded = ['```js', 'const message = "line\\nline";', '```'].join('\n');
	const encoded = JSON.stringify(decoded).slice(1, -1);
	expect(recoverToolContent(encoded)).toBe(decoded);
});

test('mixed_incomplete_and_invalid_fences_stay_literal_when_prose_recovers', () => {
	for (const literal of [
		'```js\\nconst x = 1;\n```',
		'```js\\nconst x = 1;',
		'```js\\nconst x = \\q;\\n```',
		'````markdown\n```js\\na\\n```\n````'
	]) {
		expect(recoverToolContent(`One\\n\\nTwo\n\n${literal}`)).toBe(`One\n\nTwo\n\n${literal}`);
	}
});

test('native_code_is_literal_while_known_tex_commands_recover', () => {
	expect(recoverToolContent('`\\n` and $\\\\frac{1}{2}$')).toBe('`\\n` and $\\frac{1}{2}$');
});
