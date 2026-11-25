import { test, expect } from '../fixtures';

test.use({ script: 'verify/scripts/health.json' });

test('settings', async ({ page, request }) => {
	const saved = async () => await (await request.get('/api/settings')).json();
	await page.goto('/settings');
	await page.getByRole('button', { name: 'Light', exact: true }).click();
	await expect(page.locator('html')).not.toHaveClass(/dark/);
	await expect(page.getByRole('heading', { name: 'Appearance', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Light', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await page.screenshot({
		path: test.info().outputPath('settings-light.png'),
		animations: 'disabled'
	});

	const width = page.getByRole('group', { name: 'Transcript width' });
	await expect(width.getByRole('button', { name: 'Full', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await width.getByRole('slider').focus();
	await page.keyboard.press('Home');
	await expect(width.getByText('46rem')).toBeVisible();
	await page.keyboard.press('ArrowRight');
	await expect(width.getByText('48rem')).toBeVisible();
	await page.reload();
	await expect(width.getByText('48rem')).toBeVisible();
	const transcriptMax = () =>
		page.evaluate(() =>
			document.documentElement.style.getPropertyValue('--verstehen-transcript-max')
		);
	const composerWidth = () =>
		page
			.getByPlaceholder('What do you want to learn?')
			.evaluate((element) => element.closest('form, div')?.getBoundingClientRect().width ?? 0);
	expect(await transcriptMax()).toBe('48rem');
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	const capped = await composerWidth();
	await page.goto('/settings');
	await width.getByRole('button', { name: 'Full', exact: true }).click();
	expect(await transcriptMax()).toBe('');
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'New session' })).toBeVisible();
	// Like LearnHarness's dock, the composer keeps its width; only the transcript follows the slider.
	expect(await composerWidth()).toBe(capped);
	await page.goto('/settings');

	await page.getByRole('button', { name: 'Models', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Choose Main model' })).toContainText(
		'Scripted teacher'
	);
	await expect(page.getByRole('button', { name: 'Choose Cheap model' })).toContainText(
		'Scripted title'
	);
	await expect(page.getByRole('button', { name: 'Choose Vision model' })).toContainText(
		'Scripted teacher'
	);
	const forced = page.waitForRequest(
		(item) => item.method() === 'POST' && item.url().endsWith('/api/models/refresh?force=true')
	);
	await page.getByRole('button', { name: 'Refresh model lists' }).click();
	await forced;
	await expect(page.getByText('Models are up to date.')).toBeVisible();
	await page.getByRole('button', { name: 'Choose Cheap model' }).click();
	await expect(page.getByRole('tab')).toHaveCount(0);
	await page.getByRole('button', { name: 'Scripted teacher', exact: true }).click();
	await expect.poll(async () => (await saved()).models?.cheap?.model).toBe('fake');
	await page.getByRole('button', { name: 'Scripted title', exact: true }).click();
	await expect.poll(async () => (await saved()).models?.cheap?.model).toBe('fake-title');
	await page.screenshot({
		path: test.info().outputPath('settings-models-picker.png'),
		animations: 'disabled'
	});
	await page.keyboard.press('Escape');

	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	const limit = page.getByRole('spinbutton', { name: 'Compaction limit' });
	await limit.fill('64000');
	await limit.press('Enter');
	await expect.poll(async () => (await saved()).compaction_limit).toBe(64_000);
	const row = page.getByTestId('file-access-row');
	const restrict = row.getByRole('switch', { name: 'Restrict to listed folders' });
	await restrict.click();
	const folder = row.getByRole('textbox', { name: 'Allowed folder path' });
	await folder.fill('~/Notes');
	await folder.press('Enter');
	await expect(row.getByText('Only listed folders and subfolders.')).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Lesson', exact: true }).click();
	await expect(limit).toHaveValue('64000');
	await expect(restrict).toHaveAttribute('aria-checked', 'true');
	await expect(row.getByText('~/Notes', { exact: true })).toBeVisible();
	await limit.fill('');
	await limit.press('Enter');
	await expect.poll(async () => (await saved()).compaction_limit).toBeNull();

	await page.getByRole('button', { name: 'Graph', exact: true }).click();
	const extraction = page.getByRole('switch', { name: 'extraction enabled' });
	const rendering = page.getByRole('switch', { name: 'graph rendering enabled' });
	const graphTools = page.getByRole('switch', { name: 'graph tools' });
	await expect(extraction).toBeChecked();
	await expect(rendering).toBeChecked();
	await expect(graphTools).toBeChecked();
	await graphTools.click();
	await expect.poll(async () => (await saved()).agent?.graph_tools).toBe(false);
	await rendering.click();
	await expect.poll(async () => (await saved()).graph?.rendering).toBe(false);
	await extraction.click();
	await expect.poll(async () => (await saved()).graph?.enabled).toBe(false);

	await page.getByRole('button', { name: 'Tools', exact: true }).click();
	const concurrency = page.getByRole('spinbutton', { name: 'Concurrent worker requests' });
	await concurrency.fill('4');
	await concurrency.press('Enter');
	await expect.poll(async () => (await saved()).worker_request_concurrency).toBe(4);

	await page.evaluate(() =>
		window.dispatchEvent(
			new CustomEvent('verstehen:link-refused', { detail: 'https://brave.com/search/api/' })
		)
	);
	await expect(page.getByRole('alert')).toHaveText(
		"Verstehen can't open https://brave.com/search/api/. Open it in your browser."
	);
	await page.getByRole('alert').scrollIntoViewIfNeeded();
	await page.screenshot({
		path: test.info().outputPath('settings-tools-link-refused.png'),
		animations: 'disabled'
	});
});
