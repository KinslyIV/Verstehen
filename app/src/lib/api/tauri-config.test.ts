import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { CLAUDE_CODE_INSTALL_URL } from './client';

const config = JSON.parse(readFileSync('src-tauri/tauri.conf.json', 'utf8'));
const allowed = new RegExp(config.plugins.shell.open);

test.each([
	'https://auth.openai.com/api/accounts/authorize?response_type=code&state=1',
	CLAUDE_CODE_INSTALL_URL
])('the desktop shell may open %s', (url) => {
	expect(allowed.test(url)).toBe(true);
});

test.each([
	'https://example.com/',
	'https://code.claude.com/evil',
	`${CLAUDE_CODE_INSTALL_URL}/extra`
])('the desktop shell refuses %s', (url) => {
	expect(allowed.test(url)).toBe(false);
});

test('the desktop build still bundles the sidecar', () => {
	expect(config.bundle.externalBin).toEqual(['binaries/verstehen-sidecar']);
	expect(config.identifier).toBe('local.verstehen.app');
});
