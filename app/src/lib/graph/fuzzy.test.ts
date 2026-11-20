import { describe, expect, it } from 'vitest';
import { fuzzyScore } from './fuzzy.js';

const fields = (id: string, name: string) => ['openrouter', id, name];

describe('fuzzy score', () => {
	it('matches across fields without regard to case', () => {
		expect(fuzzyScore('GLM', ...fields('z-ai/glm-5.3-flash', 'ZAI: GLM 5.3 Flash'))).not.toBeNull();
	});

	it('needs every token to match some field', () => {
		expect(fuzzyScore('glm flash', ...fields('z-ai/glm-5.3-flash', 'x'))).not.toBeNull();
		expect(fuzzyScore('glm qwen', ...fields('z-ai/glm-5.3-flash', 'x'))).toBeNull();
	});

	it('ranks an exact field above a prefix above a buried substring', () => {
		const exact = fuzzyScore('flash', 'openrouter', 'flash', 'other')!;
		const prefix = fuzzyScore('flash', 'openrouter', 'flash-2', 'other')!;
		const buried = fuzzyScore('flash', 'openrouter', 'z-ai/glm-5.3-flash', 'other')!;
		expect(exact).toBeGreaterThan(prefix);
		expect(prefix).toBeGreaterThan(buried);
	});

	it('rewards a whole-query match inside one field', () => {
		const split = fuzzyScore('glm flash', ...fields('z-ai/glm-5.3-flash', 'x'))!;
		const joined = fuzzyScore('glm 5.3', ...fields('z-ai/glm-5.3-flash', 'x'))!;
		expect(joined).toBeGreaterThan(split);
	});

	it('scores an empty query as zero', () => {
		expect(fuzzyScore('', 'anything')).toBe(0);
		expect(fuzzyScore('   ', 'anything')).toBe(0);
	});
});
