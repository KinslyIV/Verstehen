import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { test, expect } from './fixtures';
import { sendLessonMessage } from './teaching';

const sourceDirectory = await mkdtemp(resolve(tmpdir(), 'verstehen-show-image-'));
const png = resolve(sourceDirectory, 'learner-figure.png');
const script = resolve(sourceDirectory, 'show-image.json');
await promisify(execFile)(resolve('../backend/.venv/bin/python'), [
	'-c',
	'import sys; from resvg_py import svg_to_bytes; from pathlib import Path; Path(sys.argv[1]).write_bytes(svg_to_bytes(svg_string=sys.argv[2]))',
	png,
	'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="260"><rect width="480" height="260" rx="16" fill="#1e293b"/><path d="M60 200H420M60 200V35" stroke="#94a3b8" stroke-width="2"/><path d="M80 180L390 65" stroke="#38bdf8" stroke-width="4"/><circle cx="150" cy="154" r="7" fill="#fbbf24"/><circle cx="320" cy="91" r="7" fill="#fbbf24"/><text x="180" y="220" fill="#cbd5e1" font-family="sans-serif" font-size="16">Secant slope</text></svg>'
]);
await writeFile(
	script,
	(await readFile('verify/scripts/show-image.json', 'utf8')).replace('PLACEHOLDER', png)
);

test.use({ script });
test.afterAll(() => rm(sourceDirectory, { recursive: true, force: true }));

test('show-image', async ({ page, request, appendEntries }) => {
	const created = await request.post('/api/sessions', { data: { title: 'Secant slopes' } });
	expect(created.ok()).toBe(true);
	const { id } = await created.json();
	await appendEntries(id, [
		{
			kind: 'assistant',
			stop_reason: 'stop',
			parts: [
				{
					type: 'tool_call',
					tool_call_id: 'assessment',
					tool_name: 'probe_done',
					arguments: {
						assessment: { strands: [{ strand: 'Slope', assessment: 'Understands two points.' }] }
					}
				}
			]
		},
		{
			kind: 'tool_result',
			is_error: false,
			tool_call_id: 'assessment',
			tool_name: 'probe_done',
			text: 'Assessment recorded.',
			details: { ok: true }
		},
		{ kind: 'marker', marker_type: 'probe-handoff', content: '', display: true }
	]);
	await page.goto(`/session/${id}`);
	await sendLessonMessage(page, png);
	const card = page.getByTestId('image-card');
	await expect(card).toBeVisible();
	await expect(page.getByTestId('image-caption')).toHaveText(
		'The secant connects the two marked points.'
	);
	await expect(card.getByRole('img')).toHaveAttribute('src', /^blob:/);
	await expect
		.poll(() => card.getByRole('img').evaluate((image) => (image as HTMLImageElement).naturalWidth))
		.toBe(480);
	await expect(card.getByText(png)).toBeVisible();
	await expect(page.getByText('Shown to the learner:', { exact: false })).toHaveCount(0);
	await page.reload();
	await expect(page.getByTestId('image-card')).toBeVisible();
	await expect
		.poll(() =>
			page
				.getByTestId('image-card')
				.getByRole('img')
				.evaluate((image) => (image as HTMLImageElement).naturalWidth)
		)
		.toBe(480);
});
