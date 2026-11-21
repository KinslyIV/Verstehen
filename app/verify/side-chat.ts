import type { Page } from '@playwright/test';
import { expect } from './fixtures';

export function sideThread(page: Page) {
	return page.getByTestId('side-thread');
}

export async function openSideChatTab(page: Page) {
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await page.getByRole('tab', { name: 'Side chat' }).click();
	await expect(sideThread(page)).toBeVisible();
}

export async function askSideQuestion(page: Page, text: string) {
	const input = sideThread(page).getByTestId('side-thread-input');
	await input.fill(text);
	await input.press('Enter');
}

/** Send the first lesson message and wait for the teacher's reply to settle. */
export async function startTaughtLesson(page: Page, reply: string, prompt = 'Derivatives') {
	await page.goto('/');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill(prompt);
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/[^/]+$/);
	await expect(page.getByText(reply, { exact: false })).toBeVisible();
	await expect(page.getByTestId('side-conversation-button').first()).toBeVisible();
}
