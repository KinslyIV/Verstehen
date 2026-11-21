import type { SessionCoverage, SettingsStatus } from '#lib/api/client.js';

export const DEFAULT_CHUNK_TOKENS = 4096;
export const CHUNK_TOKENS_FLOOR = 500;

/** Reads the chunk size field: null is empty (the default), undefined is invalid input. */
export function parseChunkTokens(text: string): number | null | undefined {
	if (text.trim() === '') return null;
	const tokens = Number(text);
	if (!Number.isFinite(tokens) || tokens <= 0) return undefined;
	return Math.max(CHUNK_TOKENS_FLOOR, Math.round(tokens));
}

/** How full the ring is: uncovered tokens over the chunk size, clamped to 0..1 (1 means a run fires). */
export function ringFill(uncoveredTokens: number, chunkTokens: number): number {
	if (!(chunkTokens > 0)) return 0;
	return Math.min(1, Math.max(0, uncoveredTokens / chunkTokens));
}

/** The graph settings the ring and the Extract button read; extraction defaults to on. */
export function graphRead(settings: SettingsStatus): { enabled: boolean; chunkTokens: number } {
	return {
		enabled: settings.graph?.enabled ?? true,
		chunkTokens: settings.graph?.extraction_chunk_tokens ?? DEFAULT_CHUNK_TOKENS
	};
}

export type CoverageState =
	| { state: 'running' }
	| { state: 'complete' }
	| { state: 'uncovered'; tokens: number; messages: number };

/** What the session menu's block says: extracting, fully extracted, or what is still uncovered. */
export function coverageState(coverage: SessionCoverage, extracting: boolean): CoverageState {
	if (coverage.running || extracting) return { state: 'running' };
	if (coverage.uncovered_tokens === 0 && coverage.uncovered_count === 0)
		return { state: 'complete' };
	return {
		state: 'uncovered',
		tokens: coverage.uncovered_tokens,
		messages: coverage.uncovered_count
	};
}
