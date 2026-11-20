import type { APIRequestContext } from '@playwright/test';
import type { Entry } from '../src/lib/api/client';
import { expect } from './fixtures';

/** Older lesson history of learner/tutor exchanges; `reportedTokens` is the last reply's usage. */
export function filler(pairs: number, characters: number, reportedTokens?: number): Entry[] {
	const text = (label: string) =>
		`${label}. ${'We compared slopes and rates of change. '.repeat(Math.ceil(characters / 40))}`.slice(
			0,
			characters
		);
	return Array.from({ length: pairs }, (_, i): Entry[] => [
		{ kind: 'user', entry_id: `old-u${i}`, text: text(`Learner turn ${i + 1}`) },
		{
			kind: 'assistant',
			entry_id: `old-a${i}`,
			stop_reason: 'stop',
			parts: [{ type: 'text', text: text(`Tutor turn ${i + 1}`) }],
			usage:
				i === pairs - 1 && reportedTokens
					? {
							input_tokens: reportedTokens,
							output_tokens: 0,
							cache_read_tokens: 0,
							cache_write_tokens: 0,
							reasoning_tokens: 0
						}
					: undefined
		}
	]).flat();
}

export async function setCompactionLimit(request: APIRequestContext, limit: number) {
	const settings = await (await request.get('/api/settings')).json();
	delete settings.file_access_error;
	const saved = await request.put('/api/settings', {
		data: { ...settings, compaction_limit: limit }
	});
	expect(saved.ok()).toBe(true);
}

export async function createSession(request: APIRequestContext, title: string): Promise<string> {
	const created = await request.post('/api/sessions', { data: { title } });
	expect(created.ok()).toBe(true);
	return (await created.json()).id;
}
