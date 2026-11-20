import { expect, test } from 'vitest';
import { parseConcurrency } from './tools';

test.each(['', '   '])('empty concurrency %j restores the default', (draft) => {
	expect(parseConcurrency(draft)).toBeNull();
});
test.each(['0', '-1', '1.5', '8.0000000000000001', '9007199254740992', '1e', '0x10', 'Infinity'])(
	'invalid concurrency %j is rejected without rounding',
	(draft) => {
		expect(parseConcurrency(draft)).toBeUndefined();
	}
);
test.each([
	['4', 4],
	['+8', 8],
	['8.0', 8],
	['1e2', 100],
	['100e-2', 1],
	['9007199254740991', 9007199254740991]
])('whole concurrency %j commits as %j', (draft, expected) => {
	expect(parseConcurrency(draft)).toBe(expected);
});
