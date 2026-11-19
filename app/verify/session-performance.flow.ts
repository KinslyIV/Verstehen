import { test } from './fixtures';
import { measurePerformance } from './performance';
test.use({ script: 'verify/scripts/long.json' });
test('session-performance', async ({ page }, testInfo) => {
	await measurePerformance(page, testInfo);
});
