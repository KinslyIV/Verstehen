import { test } from './fixtures';
import { measurePerformance } from './performance';
test.use({ script: 'verify/scripts/realistic-long.json' });
test('session-performance-realistic', async ({ page }, testInfo) => {
	await measurePerformance(page, testInfo);
});
