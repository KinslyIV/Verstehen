import { expect, test } from 'vitest';
import { page } from 'vitest/browser';
import { layout } from './tiers.svelte.js';

test.each([
	[360, 780, 'phone'],
	[767, 900, 'phone'],
	[768, 1280, 'tablet'],
	[1279, 800, 'tablet'],
	[1280, 800, 'desktop']
] as const)('width_%i_is_the_%s_tier', async (width, height, tier) => {
	await page.viewport(width, height);
	await expect.poll(() => layout.tier).toBe(tier);
});
