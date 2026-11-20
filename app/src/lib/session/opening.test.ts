import { describe, expect, it } from 'vitest';
import type { Entry } from '#lib/api/client.js';
import { awaitsOpening } from './opening.js';

const marker = (marker_type: string) => ({ kind: 'marker', marker_type, content: '' }) as Entry;

describe('session opening', () => {
	it('awaits the opening message when empty or holding only the graph-context marker', () => {
		expect(awaitsOpening([])).toBe(true);
		expect(awaitsOpening([marker('graph-context')])).toBe(true);
	});

	it('has begun once anything else is in the session', () => {
		expect(awaitsOpening([marker('graph-context'), { kind: 'user', text: 'hi' } as Entry])).toBe(
			false
		);
		expect(awaitsOpening([marker('compaction')])).toBe(false);
	});
});
