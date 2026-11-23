import type { ModelCatalog, ModelPick, SessionStats } from '#lib/api/client.js';
import { modelFor } from '#lib/models/picks.js';

/** 38000 becomes "38k" and 1234567 becomes "1.2M"; never "38.0k". */
export function formatTokens(tokens: number): string {
	if (tokens >= 1e6) return `${+(tokens / 1e6).toFixed(1)}M`;
	if (tokens >= 1e3) return `${+(tokens / 1e3).toFixed(1)}k`;
	return String(tokens);
}

/** "41k / 200k", just "41k" without a known window, and "?" without a measurement. */
export function contextLabel(tokens: number | null, limit: number | null): string {
	const used = tokens === null ? '?' : formatTokens(tokens);
	return limit === null ? used : `${used} / ${formatTokens(limit)}`;
}

/** The picked model's window: the catalog's, or for Claude Code the limit this server has read. */
export function contextLimit(
	catalog: ModelCatalog | undefined,
	pick: ModelPick | null | undefined,
	stats: Pick<SessionStats, 'claude_code_limits'>
): number | null {
	if (!pick) return null;
	const kind = catalog?.accounts.find((item) => item.account.id === pick.account)?.account.kind;
	if (kind === 'claude_code') return stats.claude_code_limits[pick.model] ?? null;
	return modelFor(catalog, pick)?.context_limit ?? null;
}

export const isClaudeCodePick = (catalog: ModelCatalog | undefined, pick?: ModelPick | null) =>
	catalog?.accounts.find((item) => item.account.id === pick?.account)?.account.kind ===
	'claude_code';

/** The plan the session's calls were billed to, or "—"; there is never a priced dollar amount. */
export const costLabel = (totals: Pick<SessionStats['totals'], 'plan_cost_label'>): string =>
	totals.plan_cost_label ?? '—';

export const turnCostLabel = (turn: Pick<SessionStats['turns'][number], 'cost_label'>): string =>
	turn.cost_label ?? '—';

export const stepsLabel = (steps: number): string => `${steps} ${steps === 1 ? 'step' : 'steps'}`;

export const cacheHitText = (rate: number): string => `${(rate * 100).toFixed(1)}%`;

/** The stats row appears once the session has billed turns or a measured context. */
export const hasStats = (stats: SessionStats | undefined): stats is SessionStats =>
	stats !== undefined && (stats.turns.length > 0 || stats.context_tokens !== null);
