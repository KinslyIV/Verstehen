import { test, expect } from '../fixtures';
import { startLesson } from '../questions';
import { sendLessonMessage, waitForPlan } from '../teaching';

test.use({ script: 'verify/scripts/plugins-tool.json', plugins: ['hello'] });

test('plugins-tool', async ({ page, request }) => {
	expect((await request.put('/api/plugins/hello/enabled', { data: { enabled: true } })).ok()).toBe(
		true
	);
	await startLesson(page);
	await waitForPlan(page);
	await sendLessonMessage(page, 'Let’s start.');
	await expect(page.getByText('The hello plugin knows that word.')).toBeVisible();

	const sessionId = new URL(page.url()).pathname.split('/').pop();
	const detail = await (await request.get(`/api/sessions/${sessionId}`)).json();
	expect(JSON.stringify(detail.entries)).toContain('hello knows slope');

	await page.getByTestId('plugin-action-hello:sidebar-open').click();
	await expect(page.getByTestId('hello-view').getByText('Lookups: 1')).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('plugin-tool-lookups.png'),
		animations: 'disabled'
	});
});
