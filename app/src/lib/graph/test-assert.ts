import { expect } from 'vitest';

export const ok = (value: unknown, message?: string) => expect(value, message).toBeTruthy();
export const equal = (actual: unknown, expected: unknown, message?: string) =>
	expect(actual, message).toBe(expected);
export const deepEqual = (actual: unknown, expected: unknown, message?: string) =>
	expect(actual, message).toEqual(expected);
