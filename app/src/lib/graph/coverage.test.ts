import { describe, expect, it } from 'vitest';
import type { SessionCoverage } from '#lib/api/client.js';
import { coverageState, graphRead, ringFill } from './coverage.js';

const coverage = (patch: Partial<SessionCoverage> = {}): SessionCoverage => ({
	total_messages: 10,
	covered_count: 6,
	uncovered_count: 4,
	covered_tokens: 3000,
	uncovered_tokens: 1000,
	running: false,
	last_folded_at: null,
	...patch
});

describe('coverage ring', () => {
	it('fills with uncovered tokens over the chunk size and stops at full', () => {
		expect(ringFill(1024, 4096)).toBe(0.25);
		expect(ringFill(9000, 4096)).toBe(1);
		expect(ringFill(0, 4096)).toBe(0);
		expect(ringFill(100, 0)).toBe(0);
	});

	it('reads the graph switch and chunk size with their defaults', () => {
		expect(graphRead({})).toEqual({ enabled: true, chunkTokens: 4096 });
		expect(
			graphRead({ graph: { enabled: false, rendering: true, extraction_chunk_tokens: 800 } })
		).toEqual({ enabled: false, chunkTokens: 800 });
	});

	it('says extracting while a run is in flight or was just requested', () => {
		expect(coverageState(coverage({ running: true }), false).state).toBe('running');
		expect(coverageState(coverage(), true).state).toBe('running');
	});

	it('says fully extracted when nothing is uncovered, else the uncovered numbers', () => {
		expect(coverageState(coverage({ uncovered_tokens: 0, uncovered_count: 0 }), false).state).toBe(
			'complete'
		);
		expect(coverageState(coverage(), false)).toEqual({
			state: 'uncovered',
			tokens: 1000,
			messages: 4
		});
	});
});
