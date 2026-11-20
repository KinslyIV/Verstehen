import { expect, test } from './fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings-quizzing', async ({ page }) => {
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	const group = page.getByRole('group', { name: 'Quizzing' });
	await expect(group).toHaveAccessibleDescription('How the tutor checks your understanding');
	await expect(group.getByRole('button', { name: 'Multiple choice' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await group.getByRole('button', { name: 'Free recall' }).click();
	await expect(group.getByRole('button', { name: 'Free recall' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await page.reload();
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await expect(group.getByRole('button', { name: 'Free recall' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
});
