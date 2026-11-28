import { beforeEach, expect, test } from 'vitest';
import { isReturnablePath, returnPath } from './return-path.svelte.js';

beforeEach(() => {
	sessionStorage.clear();
	returnPath.reset();
});

test('isReturnablePath_rejects_settings_pair_and_external_paths', () => {
	expect(isReturnablePath('/')).toBe(true);
	expect(isReturnablePath('/session/abc')).toBe(true);
	expect(isReturnablePath('/graph')).toBe(true);
	expect(isReturnablePath('/settings')).toBe(false);
	expect(isReturnablePath('/settings/extra')).toBe(false);
	expect(isReturnablePath('/pair')).toBe(false);
	expect(isReturnablePath('/pair/confirm')).toBe(false);
	expect(isReturnablePath('//evil.example')).toBe(false);
});

test('returnPath_remembers_last_in_app_url_across_settings_and_persists_to_session_storage', () => {
	returnPath.remember(new URL('http://localhost/session/one?mode=teach'));
	expect(returnPath.path).toBe('/session/one?mode=teach');

	returnPath.remember(new URL('http://localhost/settings?section=models'));
	returnPath.remember(new URL('http://localhost/pair'));
	expect(returnPath.path).toBe('/session/one?mode=teach');
	expect(sessionStorage.getItem('verstehen-settings-return')).toBe('/session/one?mode=teach');
});
