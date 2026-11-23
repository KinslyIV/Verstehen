import { beforeEach, expect, test } from 'vitest';
import type { SessionItem } from '#lib/api/client.js';
import {
	isSearchFolded,
	kindIncludes,
	noSearchFolds,
	readKindFilter,
	saveKindFilter,
	readOpenFolders,
	saveOpenFolders,
	sessionMeta,
	toggleSearchFold,
	walkIndex
} from './session-list-model.js';

const now = new Date('2026-01-01T01:00:00Z');
const session = (patch: Partial<SessionItem> = {}): SessionItem => ({
	id: 's',
	title: 'T',
	kind: 'teach',
	updated_at: '2026-01-01T00:00:00Z',
	busy: false,
	...patch
});

beforeEach(() => localStorage.clear());

test('the_kind_filter_keeps_all_sessions_or_only_one_kind', () => {
	const sessions = [session({ id: 'a' }), session({ id: 'b', kind: 'practice' })];
	expect(sessions.filter(kindIncludes('all'))).toHaveLength(2);
	expect(sessions.filter(kindIncludes('teach')).map(({ id }) => id)).toEqual(['a']);
	expect(sessions.filter(kindIncludes('practice')).map(({ id }) => id)).toEqual(['b']);
});

test('the_kind_filter_defaults_to_all_and_survives_reloads', () => {
	expect(readKindFilter()).toBe('all');
	saveKindFilter('practice');
	expect(readKindFilter()).toBe('practice');
	localStorage.setItem('verstehen-session-kind-filter', 'nonsense');
	expect(readKindFilter()).toBe('all');
});

test('the_open_folders_are_remembered_and_a_corrupt_value_means_none', () => {
	expect(readOpenFolders().size).toBe(0);
	saveOpenFolders(new Set(['f1', 'f2']));
	expect([...readOpenFolders()]).toEqual(['f1', 'f2']);
	localStorage.setItem('verstehen-sidebar-open-folders', '{nonsense');
	expect(readOpenFolders().size).toBe(0);
	localStorage.setItem('verstehen-sidebar-open-folders', '[1,"f3"]');
	expect([...readOpenFolders()]).toEqual(['f3']);
});

test('the_row_meta_names_what_the_session_waits_on', () => {
	expect(sessionMeta(session(), now)).toBe('1h ago');
	expect(sessionMeta(session({ busy: true }), now)).toBe('Working…');
	expect(sessionMeta(session({ pending_question: true }), now)).toBe('Waiting for input · 1h ago');
	const practice = session({ kind: 'practice', pending_problem: true });
	expect(sessionMeta(practice, now)).toBe('Problem waiting · 1h ago');
	expect(sessionMeta(session({ pending_problem: true }), now)).toBe('1h ago');
	expect(sessionMeta({ ...practice, pending_question: true }, now)).toBe(
		'Waiting for input · 1h ago'
	);
	expect(sessionMeta({ ...practice, compacting: true }, now)).toBe('Compacting context');
});

test('a_folder_closed_during_a_search_is_forgotten_when_the_query_changes', () => {
	const folds = toggleSearchFold(noSearchFolds, 'calc', 'f1');
	expect(isSearchFolded(folds, 'calc', 'f1')).toBe(true);
	expect(isSearchFolded(folds, 'calc', 'f2')).toBe(false);
	expect(isSearchFolded(folds, 'calcu', 'f1')).toBe(false);
	expect(isSearchFolded(toggleSearchFold(folds, 'calc', 'f1'), 'calc', 'f1')).toBe(false);
});

test('arrow_keys_start_at_the_first_or_last_row_and_wrap_around', () => {
	expect(walkIndex(null, 1, 3)).toBe(0);
	expect(walkIndex(null, -1, 3)).toBe(2);
	expect(walkIndex(2, 1, 3)).toBe(0);
	expect(walkIndex(0, -1, 3)).toBe(2);
	expect(walkIndex(1, 1, 3)).toBe(2);
	expect(walkIndex(5, 1, 3)).toBe(0);
});
