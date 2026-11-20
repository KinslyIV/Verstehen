import type { Page } from '@playwright/test';
import { expect } from './fixtures';

export function planPanel(page: Page) {
	return page.getByRole('complementary', { name: 'Plan and activity' });
}

export async function waitForPlan(page: Page) {
	await expect(planPanel(page).getByRole('tab', { name: 'Plan' })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(planPanel(page).getByTestId('plan-node-slope')).toBeVisible();
	await expect(page.getByTestId('plan-block')).toBeVisible();
}

export async function sendLessonMessage(page: Page, text: string) {
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill(text);
	await page.getByRole('button', { name: 'Send', exact: true }).click();
}
