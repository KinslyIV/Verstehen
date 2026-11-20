import type { Page } from '@playwright/test';
import { expect } from './fixtures';

export async function startLesson(page: Page, prompt = 'Teach me about derivatives') {
	await page.goto('/');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill(prompt);
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
}

export async function selectOption(page: Page, label: string) {
	await page.getByRole('radio', { name: label, exact: true }).click();
	await expect(page.getByRole('radio', { name: label, exact: true })).toHaveAttribute(
		'aria-checked',
		'true'
	);
}
