import { expect, test } from 'vitest';
import type { Entry } from '#lib/api/client.js';
import {
	compactionDividers,
	cutDividerText,
	failedResponseAtEnd,
	parseCompactionLimit
} from './compaction.js';

const user = (id: string): Entry => ({ kind: 'user', entry_id: id, text: id });
const marker = (id: string, details: Record<string, unknown>): Entry => ({
	kind: 'marker',
	entry_id: id,
	marker_type: 'compaction',
	content: 'summary',
	display: true,
	details: details as never
});
const failure: Entry = {
	kind: 'assistant',
	entry_id: 'bad',
	parts: [],
	stop_reason: 'error',
	error_text: 'Provider failed'
};

test('the_moment_line_follows_the_summarized_entry_and_the_cut_precedes_the_kept_one', () => {
	const entries = [
		user('a'),
		user('b'),
		user('c'),
		user('d'),
		marker('m', {
			first_kept_entry_id: 'c',
			last_summarized_entry_id: 'b',
			tokens_before: 42_400
		})
	];
	const { cutBefore, momentsAfter } = compactionDividers(entries);
	expect(cutBefore).toEqual({ entryId: 'c', tokensBefore: 42_400 });
	expect([...momentsAfter]).toEqual([['b', 1]]);
});

test('only_the_active_compaction_draws_a_cut_and_older_markers_keep_their_moment', () => {
	const entries = [
		user('a'),
		marker('m1', { first_kept_entry_id: 'a', last_summarized_entry_id: 'a', tokens_before: 1000 }),
		user('b'),
		user('c'),
		marker('m2', { first_kept_entry_id: 'c', last_summarized_entry_id: 'b', tokens_before: 9000 })
	];
	const { cutBefore, momentsAfter } = compactionDividers(entries);
	expect(cutBefore?.entryId).toBe('c');
	expect(momentsAfter.get('a')).toBe(1);
	expect(momentsAfter.get('b')).toBe(1);
});

test('a_missing_summarized_entry_places_the_moment_at_the_marker_and_a_missing_kept_one_draws_no_cut', () => {
	const entries = [
		user('a'),
		marker('m', { first_kept_entry_id: 'gone', last_summarized_entry_id: 'gone' })
	];
	const { cutBefore, momentsAfter } = compactionDividers(entries);
	expect(cutBefore).toBeUndefined();
	expect(momentsAfter.get('m')).toBe(1);
});

test('the_cut_chip_rounds_thousands_and_omits_an_unknown_count', () => {
	expect(cutDividerText(42_400)).toBe('History compacted · 42k tok');
	expect(cutDividerText(0)).toBe('History compacted');
});

test('a_failure_behind_display_markers_is_still_the_failure_at_the_end', () => {
	expect(failedResponseAtEnd([failure, marker('m', {})])).toEqual({
		errorText: 'Provider failed',
		afterCompaction: true
	});
	expect(failedResponseAtEnd([marker('m', {}), failure])?.afterCompaction).toBe(false);
	expect(failedResponseAtEnd([failure, user('a')])).toBeUndefined();
});

test('the_limit_field_reads_empty_as_default_raises_to_the_floor_and_rejects_bad_input', () => {
	expect(parseCompactionLimit('')).toBeNull();
	expect(parseCompactionLimit('  ')).toBeNull();
	expect(parseCompactionLimit('1000')).toBe(32_000);
	expect(parseCompactionLimit('200000.4')).toBe(200_000);
	expect(parseCompactionLimit('abc')).toBeUndefined();
	expect(parseCompactionLimit('-5')).toBeUndefined();
	expect(parseCompactionLimit('0')).toBeUndefined();
});
