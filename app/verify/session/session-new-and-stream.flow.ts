import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/session-new-and-stream.json' });

test('session-new-and-stream', async ({ page }) => {
	await page.goto('/');
	await page
		.getByRole('textbox', { name: 'What do you want to learn?' })
		.fill('Understanding derivatives');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	const thinking = page.getByRole('button', { name: 'Thinking...', exact: true });
	await expect(thinking).toHaveAttribute('aria-expanded', 'false');
	await thinking.click();
	await expect(thinking).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByText('Let me connect this idea to what you already know.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
	await page.screenshot({
		path: test.info().outputPath('thinking-streaming.png'),
		animations: 'disabled'
	});
	await expect(page.getByText('A derivative describes', { exact: false })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: "AGENT'S THINKING" })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
	await page.getByRole('button', { name: "AGENT'S THINKING" }).click();
	await expect(page.getByText('Let me connect this idea to what you already know.')).toBeVisible();
	await page.waitForTimeout(1200);
	await expect(page.getByRole('button', { name: "AGENT'S THINKING" })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	await expect(
		page.getByRole('button', { name: 'Photosynthesis basics', exact: true })
	).toBeVisible();
	await expect(
		page
			.getByTestId('session-header')
			.getByRole('button', { name: 'Photosynthesis basics', exact: true })
	).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Photosynthesis basics', exact: true })
	).toHaveCount(1);
	await expect(page.getByRole('link', { name: /Photosynthesis basics/ })).toContainText('just now');
	const footer = page.getByTestId('message-footer').last();
	await expect(footer.getByTestId('message-time')).toBeVisible();
	const copyButton = footer.getByTestId('copy-message-button');
	await expect(copyButton).toBeVisible();
	await copyButton.click();
	await expect(copyButton).toHaveAttribute('aria-label', 'Copied');
	await page.screenshot({
		path: test.info().outputPath('session-settled-header-footer.png'),
		animations: 'disabled'
	});
});
