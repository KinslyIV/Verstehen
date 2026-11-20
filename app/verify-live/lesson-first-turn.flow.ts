import type { Page } from '@playwright/test';
import type { ModelPick, SessionDetail } from '../src/lib/api/client';
import { expect, test } from '../verify/fixtures';
import { startLesson } from '../verify/questions';

test.use({ script: 'none' });

async function expectTurnStream(page: Page) {
	const response = await page.waitForResponse(
		(response) => /\/api\/sessions\/[^/]+\/stream$/.test(response.url()),
		{ timeout: 120_000 }
	);
	expect(response.status()).toBe(200);
	expect(response.headers()['content-type']).toContain('text/event-stream');
	return response.url();
}

test('lesson-first-turn', async ({ page, request }) => {
	const model: ModelPick = { account: 'claude_code', model: 'haiku', thinking_level: 'low' };
	const saved = await request.put('/api/settings', {
		data: { models: { strong: model, cheap: model, vision: model } }
	});
	expect(saved.ok(), 'Claude Code Haiku must be available through the model settings API').toBe(
		true
	);

	const lesson = page.getByRole('region', { name: 'Lesson' });
	const stop = lesson.getByRole('button', { name: 'Stop', exact: true });
	await Promise.all([
		expectTurnStream(page),
		expect(stop).toBeVisible(),
		startLesson(
			page,
			'Teach me to calculate the slope of a straight line from two points. Start with one quick question.'
		)
	]);
	const dock = lesson.getByTestId('question-dock');
	await expect(dock, 'Opening turn must end with a question in the dock').toBeVisible();
	const submit = dock.getByRole('button', { name: 'Submit answer' });
	const option = dock.getByRole('radio').or(dock.getByRole('checkbox')).first();
	if (await option.count()) {
		await option.click();
		await expect(option).toHaveAttribute('aria-checked', 'true');
		if (await dock.getByRole('slider', { name: 'Confidence' }).count()) {
			await option.press('ArrowRight');
			await expect(dock.getByTestId('confidence-value')).toHaveText('70%');
		}
		await dock.getByRole('textbox', { name: 'Your thinking' }).fill('I compared rise and run.');
	} else {
		await dock.getByRole('textbox', { name: 'Your answer' }).fill('Slope is rise over run.');
	}
	await expect(submit).toBeEnabled();
	const [reaction] = await Promise.all([
		expectTurnStream(page),
		expect(stop).toBeVisible(),
		submit.click()
	]);
	await expect(lesson.getByTestId('answered-card').first()).toBeVisible();
	await expect(stop).toBeHidden();
	await expect(lesson.getByRole('alert')).toHaveCount(0);
	const response = await request.get(reaction.replace(/\/stream$/, ''));
	expect(response.ok()).toBe(true);
	const session: SessionDetail = await response.json();
	expect(session).toMatchObject({
		model_account: model.account,
		model_id: model.model,
		thinking_level: model.thinking_level,
		turn_in_flight: false,
		turn_error: null
	});
});
