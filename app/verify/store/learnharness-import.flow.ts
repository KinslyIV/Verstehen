import { test, expect, learnHarnessFixture } from '../fixtures';
import { camera, waitForLayout } from '../graph';
import { openSideChatTab, sideThread } from '../side-chat';

test.use({ script: 'verify/scripts/health.json', learnHarnessFolder: learnHarnessFixture });

test('learnharness-import', async ({ page, request }) => {
	await page.goto('/');
	await expect(page.getByRole('link', { name: /Slopes/ })).toBeVisible();

	await page.getByRole('link', { name: /Slopes/ }).click();
	await expect(page.getByTestId('phase-divider-plan')).toBeVisible();
	const answered = page.getByTestId('answered-card');
	await expect(answered).toContainText('What is the slope of y = 2x?');
	await expect(answered).toContainText('90');
	await expect(page.getByTestId('research-brief-card')).toContainText('rise over run');
	await expect(page.getByTestId('visual-card')).toBeVisible();
	const { jobs } = await (await request.get('/api/jobs?session=chat_fx_teach')).json();
	expect(jobs.map((job: { status: string }) => job.status).sort()).toEqual([
		'done',
		'done',
		'error'
	]);
	await page.screenshot({ path: test.info().outputPath('session.png'), animations: 'disabled' });
	await answered.scrollIntoViewIfNeeded();
	await page.screenshot({ path: test.info().outputPath('question.png'), animations: 'disabled' });

	await openSideChatTab(page);
	await expect(sideThread(page).getByTestId('side-learner-message')).toContainText(
		'Why rise over run?'
	);
	await expect(sideThread(page).getByTestId('side-helper-message')).toContainText(
		'Because slope compares vertical to horizontal change.'
	);
	await page.screenshot({ path: test.info().outputPath('side-chat.png'), animations: 'disabled' });

	const { sessions } = await (await request.get('/api/sessions')).json();
	expect(sessions.map((session: { kind: string }) => session.kind).sort()).toEqual([
		'practice',
		'teach'
	]);
	await page.getByRole('link', { name: /Practice fixture/ }).click();
	await expect(page.getByTestId('phase-chip')).toHaveText(/Practice/);
	await expect(page.getByTestId('coverage-ring')).toHaveCount(0);
	await expect(page.getByTestId('model-solution')).toContainText('The power rule gives twice x.');
	await page.screenshot({ path: test.info().outputPath('practice.png'), animations: 'disabled' });

	await page.goto('/graph');
	const canvas = page.getByTestId('graph-canvas');
	await expect(canvas).toBeVisible();
	await expect
		.poll(() =>
			canvas.evaluate((element: HTMLCanvasElement) => {
				const { data } = element
					.getContext('2d')!
					.getImageData(0, 0, element.width, element.height);
				let drawn = 0;
				for (let i = 3; i < data.length; i += 4) if (data[i] > 0) drawn++;
				return drawn;
			})
		)
		.toBeGreaterThan(500);
	await waitForLayout(request, 3);
	await camera(page);
	const graph = await (await request.get('/api/graph')).json();
	expect(graph.propositions.map((node: { id: string }) => node.id).sort()).toEqual([
		'n_fx1',
		'n_fx2',
		'n_fx3'
	]);
	await page.screenshot({ path: test.info().outputPath('graph.png'), animations: 'disabled' });
});
