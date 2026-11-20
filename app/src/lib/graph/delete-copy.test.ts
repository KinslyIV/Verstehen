import { describe, expect, it } from 'vitest';
import { ApiError } from '#lib/api/client.js';
import { EXTRACTION_RETRY_LINE, deleteFailureText, nameList } from './delete-copy.js';

describe('delete dialog copy', () => {
	it('names a running extraction instead of quoting the server', () => {
		const running = new ApiError(409, 'extraction_running', 'An extraction is running — x');
		expect(deleteFailureText(running)).toBe(EXTRACTION_RETRY_LINE);
	});

	it('shows the server’s line for other refusals and a network line for transport failures', () => {
		expect(deleteFailureText(new ApiError(503, 'extraction_winding_down', 'In a moment'))).toBe(
			'In a moment'
		);
		expect(deleteFailureText(new TypeError('failed'))).toBe(
			'Delete failed — network error. Try again.'
		);
	});

	it('lists eight names and counts the rest', () => {
		const names = Array.from({ length: 10 }, (_, i) => `n${i}`);
		expect(nameList(names.slice(0, 2))).toBe('n0, n1');
		expect(nameList(names)).toBe('n0, n1, n2, n3, n4, n5, n6, n7, and 2 more');
	});
});
