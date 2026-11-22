import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/practice-session.json' });

test('practice-session', async ({ page, request }) => {
	await page.goto('/session/new?mode=practice');
	await expect(page.getByTestId('kind-practice')).toHaveAttribute('aria-current', 'page');
	await page.getByRole('textbox', { name: 'What do you want to learn?' }).fill('The power rule');
	await page.getByRole('button', { name: 'Send', exact: true }).click();
	await expect(page).toHaveURL(/\/session\/(?!new)[^/]+$/);
	const id = new URL(page.url()).pathname.split('/').at(-1)!;

	const dock = page.getByTestId('practice-dock');
	await expect(dock).toContainText('Differentiate');
	await expect(dock.getByRole('textbox', { name: 'Your thinking' })).toBeVisible();
	await expect(page.getByTestId('phase-chip')).toHaveText(/Practice/);
	await expect(page.getByTestId('coverage-ring')).toHaveCount(0);
	await expect(page.getByTestId('problem-card')).toHaveCount(1);
	await expect(page.getByRole('link', { name: /Problem waiting/ })).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('posed.png'), animations: 'disabled' });

	// Reloading an open problem keeps the dock and starts no continue turn.
	await page.reload();
	await expect(dock).toContainText('Differentiate');
	const reloaded = await (await request.get(`/api/sessions/${id}`)).json();
	expect(reloaded.turn_in_flight).toBe(false);
	expect(
		reloaded.entries.filter((entry: { kind: string }) => entry.kind === 'assistant')
	).toHaveLength(1);

	// Scrolling up collapses the dock to its bar and keeps the draft.
	const field = dock.getByRole('textbox', { name: 'Your thinking' });
	const viewport = page.getByLabel('Conversation');
	const bar = page.getByTestId('practice-dock-bar');
	await expect(async () => {
		if (await bar.isVisible()) await bar.click();
		await expect(dock).toBeVisible({ timeout: 500 });
	}).toPass();
	await field.fill('Bring down the exponent');
	await viewport.hover();
	await page.mouse.wheel(0, -900);
	await expect(bar).toBeVisible();
	await expect(dock).toBeHidden();
	await page.screenshot({ path: test.info().outputPath('collapsed.png'), animations: 'disabled' });
	await bar.click();
	await expect(field).toHaveValue('Bring down the exponent');

	// Esc opens the discard confirmation; Cancel keeps the problem.
	await page.keyboard.press('Escape');
	const discard = page.getByRole('dialog', { name: 'Discard this problem?' });
	await expect(discard).toContainText('no solution is revealed');
	await page.screenshot({ path: test.info().outputPath('discard.png'), animations: 'disabled' });
	await discard.getByRole('button', { name: 'Cancel' }).click();
	await expect(dock).toBeVisible();

	// Submitting thinking concludes the problem and reveals the committed solution.
	await field.fill('Bring down the exponent: $3x^2$, the power rule.');
	await field.press('Enter');
	await expect(page.getByTestId('thinking-card')).toContainText('the power rule');
	const conclusion = page.getByTestId('conclude-card');
	await expect(conclusion).toContainText('You named the power rule');
	await expect(page.getByTestId('conclude-outcome')).toHaveText('Solved');
	await expect(page.getByTestId('model-solution')).toContainText('bring the exponent down');
	await expect(dock).toHaveCount(0);
	await expect(page.getByTestId('next-problem')).toBeVisible();
	await conclusion.getByTestId('metadata-toggle').click();
	await expect(page.getByTestId('metadata-box')).toContainText('untagged');
	await page.screenshot({ path: test.info().outputPath('concluded.png'), animations: 'disabled' });
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('metadata-box')).toHaveCount(0);

	// Next problem poses a second problem.
	await page.getByTestId('next-problem').click();
	await expect(page.getByTestId('practice-next-line')).toBeVisible();
	await expect(dock).toContainText('5x^4');
	await page.screenshot({ path: test.info().outputPath('second.png'), animations: 'disabled' });

	// Discarding it needs no turn; Enter on the empty composer moves on and records the dismissal.
	await page.keyboard.press('Escape');
	await page
		.getByRole('dialog', { name: 'Discard this problem?' })
		.getByRole('button', { name: 'Discard' })
		.click();
	await expect(dock).toHaveCount(0);
	await expect(page.getByTestId('next-problem')).toBeVisible();
	await page.getByRole('textbox').press('Enter');
	await expect(page.getByText('Problem dismissed.')).toBeVisible();
	await expect(dock).toContainText('x^2 + x');
	const saved = await (await request.get(`/api/sessions/${id}`)).json();
	expect(saved.kind).toBe('practice');
	expect(saved.coverage).toBeNull();
	expect(saved.turn_in_flight).toBe(false);
	await page.screenshot({ path: test.info().outputPath('dismissed.png'), animations: 'disabled' });
});
