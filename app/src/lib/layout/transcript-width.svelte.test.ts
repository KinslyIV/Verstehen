import { beforeEach, describe, expect, it } from 'vitest';
import { parseWidth, TranscriptWidth } from './transcript-width.svelte.js';

describe('the transcript width', () => {
	beforeEach(() => {
		localStorage.clear();
		document.documentElement.style.removeProperty('--verstehen-transcript-max');
	});

	it('is Full until a width is chosen, and ignores corrupt values', () => {
		expect(new TranscriptWidth().rem).toBeNull();
		for (const bad of ['', 'abc', '45', '47', '122', '70.5'])
			expect(parseWidth(bad), bad).toBeNull();
		expect(parseWidth('70')).toBe(70);
	});

	it('remembers a chosen width, sets the root variable, and returns to Full', () => {
		new TranscriptWidth().set(80);
		expect(new TranscriptWidth().rem).toBe(80);
		expect(document.documentElement.style.getPropertyValue('--verstehen-transcript-max')).toBe(
			'80rem'
		);
		new TranscriptWidth().set(null);
		expect(localStorage.getItem('verstehen-transcript-width')).toBeNull();
		expect(document.documentElement.style.getPropertyValue('--verstehen-transcript-max')).toBe('');
	});
});
