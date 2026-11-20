import { test, expect } from './fixtures';
import { startLesson } from './questions';

test.use({ script: 'verify/scripts/send-to-user.json' });

test('send-to-user', async ({ page, request }) => {
	const model = { account: 'fake', model: 'fake-claude' };
	expect((await request.post('/api/settings/default-model', { data: model })).ok()).toBe(true);
	await startLesson(page);
	const partial = page.locator('strong').filter({ hasText: 'secant slope' });
	await expect(partial).toBeVisible();
	await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	await expect(
		page.getByText('A secant slope is the average rate of change between two points.')
	).toBeVisible();
	await expect(page.getByText('Could not send message')).toBeVisible();
	await expect(page.getByText('Input should be a valid string')).toBeVisible();
	await expect(page.getByText('We can now compare two secants.')).toBeVisible();
	await expect(page.getByText('Message received for display.')).toHaveCount(0);
});
