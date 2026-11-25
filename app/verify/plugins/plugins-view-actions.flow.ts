import { test, expect } from '../fixtures';
import { startLesson } from '../questions';

test.use({ script: 'verify/scripts/plugins-tool.json', plugins: ['hello'] });

test('plugins-view-actions', async ({ page, request }) => {
	expect((await request.put('/api/plugins/hello/enabled', { data: { enabled: true } })).ok()).toBe(
		true
	);
	await page.goto('/');
	const sidebarAction = page.getByTestId('plugin-action-hello:sidebar-open');
	await expect(sidebarAction).toBeVisible();
	await sidebarAction.click();
	await expect(page).toHaveURL(/\/plugin\/hello\/main$/);
	await expect(page.getByTestId('plugin-view-title')).toHaveText('Hello');
	const view = page.getByTestId('hello-view');
	await expect(view.getByText('Lookups: 0')).toBeVisible();
	await view.getByRole('textbox', { name: 'Name' }).fill('Grace');
	await view.getByRole('button', { name: 'Greet', exact: true }).click();
	await expect(page.getByTestId('hello-answer')).toHaveText('Hello, Grace!');
	await page.screenshot({
		path: test.info().outputPath('plugin-view.png'),
		animations: 'disabled'
	});

	await startLesson(page);
	await expect(page.getByTestId('plugin-action-hello:top-greet')).toBeVisible();
	await page.getByTestId('plugin-action-hello:top-greet').click();
	const dialog = page.getByRole('dialog', { name: 'Hello' });
	await expect(dialog.getByTestId('hello-dialog-message')).toContainText('Hello, session');
	await page.screenshot({
		path: test.info().outputPath('plugin-session-action.png'),
		animations: 'disabled'
	});
	await page.keyboard.press('Escape');
	await expect(dialog).toBeHidden();
});
