import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { test, expect } from './fixtures';
import { seedTeaching } from './jobs';
import { sendLessonMessage } from './teaching';

const sourceDirectory = await mkdtemp(resolve(tmpdir(), 'verstehen-visual-annotate-'));
const png = resolve(sourceDirectory, 'learner-figure.png');
const script = resolve(sourceDirectory, 'job-visual-annotate.json');
await promisify(execFile)(resolve('../backend/.venv/bin/python'), [
	'-c',
	'import sys; from resvg_py import svg_to_bytes; from pathlib import Path; Path(sys.argv[1]).write_bytes(svg_to_bytes(svg_string=sys.argv[2]))',
	png,
	'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="260"><rect width="480" height="260" rx="16" fill="#1e293b"/><path d="M60 200H420M60 200V35" stroke="#94a3b8" stroke-width="2"/><path d="M80 180L390 65" stroke="#38bdf8" stroke-width="4"/><circle cx="150" cy="154" r="7" fill="#fbbf24"/><circle cx="320" cy="91" r="7" fill="#fbbf24"/></svg>'
]);
const annotation =
	'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="260" viewBox="0 0 480 260"><image href="learner-image" x="0" y="0" width="480" height="260"/><circle cx="150" cy="154" r="16" fill="none" stroke="#ef4444" stroke-width="3"/><circle cx="320" cy="91" r="16" fill="none" stroke="#ef4444" stroke-width="3"/><text x="170" y="236" font-family="sans-serif" font-size="18" fill="#ffffff">secant</text></svg>';
await writeFile(
	script,
	(await readFile('verify/scripts/job-visual-annotate.json', 'utf8'))
		.replace('PLACEHOLDER', png)
		.replace('"ANNOTATION"', JSON.stringify(annotation))
);

test.use({ script });
test.afterAll(() => rm(sourceDirectory, { recursive: true, force: true }));

test('job-visual-annotate', async ({ page, request, appendEntries }, testInfo) => {
	const id = await seedTeaching(request, appendEntries, 'Secant slopes');
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, 'Draw a secant');
	const figure = page.getByTestId('visual-card').first();
	await expect(figure).toBeVisible({ timeout: 30_000 });
	await expect(figure.getByRole('switch', { name: 'Invert figure brightness' })).toBeVisible();
	await figure.getByRole('switch', { name: 'Invert figure brightness' }).click();
	await expect(figure.getByTestId('visual-svg')).toHaveCSS('filter', /invert/);
	await expect(page.getByText('Both pictures are done.')).toBeVisible({ timeout: 30_000 });
	const photo = page.getByTestId('visual-card').nth(1);
	await expect(photo.getByRole('img', { name: 'Figure' })).toBeVisible();
	await expect(photo.getByRole('switch')).toHaveCount(0);
	await expect(photo).toContainText('Figure');
	await expect
		.poll(() =>
			photo.getByRole('img').evaluate((image) => (image as HTMLImageElement).naturalWidth)
		)
		.toBe(480);
	await figure.scrollIntoViewIfNeeded();
	await page.screenshot({ path: testInfo.outputPath('figure.png'), animations: 'disabled' });
	await photo.scrollIntoViewIfNeeded();
});
