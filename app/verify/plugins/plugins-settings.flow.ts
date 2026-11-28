import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json', plugins: ['hello'] });

test('plugins-settings', async ({ page }) => {
	await page.goto('/settings?section=plugins');
	const hello = page.getByTestId('plugin-hello');
	await expect(hello).toContainText('Hello');
	await expect(page.getByTestId('plugin-status-hello')).toHaveText('disabled');
	await expect(page.getByTestId('plugin-action-hello:sidebar-open')).toHaveCount(0);
	await expect(page.getByTestId('plugins-directory')).toContainText('plugins');
	await page.screenshot({
		path: test.info().outputPath('plugins-disabled.png'),
		animations: 'disabled'
	});

	await hello.getByRole('switch', { name: 'Enable Hello' }).click();
	await expect(page.getByTestId('plugin-status-hello')).toHaveText('active');
	await hello.getByTestId('plugin-open-settings-hello').click();
	await expect(page.getByRole('heading', { name: 'Hello', level: 3 })).toBeVisible();
	const body = page.getByTestId('plugin-settings-body');
	const name = body.getByRole('textbox', { name: 'Name to greet' });
	await expect(name).toHaveValue('friend');
	await name.fill('Ada');
	await name.press('Enter');
	await body.getByRole('switch', { name: 'Loud greeting' }).click();
	await page.screenshot({
		path: test.info().outputPath('plugin-settings-page.png'),
		animations: 'disabled'
	});

	await page.reload();
	await expect(page.getByTestId('plugin-settings-body').getByRole('textbox')).toHaveValue('Ada');
	await expect(
		page.getByTestId('plugin-settings-body').getByRole('switch', { name: 'Loud greeting' })
	).toBeChecked();

	await page.getByTestId('plugin-settings-back').click();
	await page.getByRole('switch', { name: 'Enable Hello' }).click();
	await expect(page.getByTestId('plugin-status-hello')).toHaveText('disabled');
	await expect(page.getByTestId('plugin-open-settings-hello')).toHaveCount(0);
});
