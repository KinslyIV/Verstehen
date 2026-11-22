import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, expect } from '../fixtures';
import { scriptExtractors, waitForLayout } from '../graph';

test.use({ script: 'verify/scripts/graph-import.json' });

/** A one-page PDF: a large heading, then body lines in a smaller font. */
function pdf(heading: string, body: string[]): Buffer {
	const lines = [`BT /F1 22 Tf 72 720 Td (${heading}) Tj ET`];
	body.forEach((line, i) => lines.push(`BT /F1 11 Tf 72 ${680 - i * 16} Td (${line}) Tj ET`));
	const stream = lines.join('\n');
	const objects = [
		'<< /Type /Catalog /Pages 2 0 R >>',
		'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
		'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Resources << /Font << /F1 4 0 R >> >> >>',
		'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
		`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`
	];
	let out = '%PDF-1.4\n';
	const offsets = objects.map((object, i) => {
		const offset = out.length;
		out += `${i + 1} 0 obj\n${object}\nendobj\n`;
		return offset;
	});
	const xref = out.length;
	out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
	for (const offset of offsets) out += `${String(offset).padStart(10, '0')} 00000 n \n`;
	out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(out, 'latin1');
}

test('graph-import', async ({ page, request }) => {
	await scriptExtractors(request);
	await page.goto('/graph');
	await expect(page.getByRole('heading', { name: 'Knowledge graph' })).toBeVisible();
	await page.getByTestId('import-notes').click();
	const chooser = page.waitForEvent('filechooser');
	await page.getByRole('button', { name: 'Files', exact: true }).click();
	await (
		await chooser
	).setFiles([
		{
			name: 'limits.md',
			mimeType: 'text/markdown',
			buffer: Buffer.from('# Limits\n\nA limit is the value a function approaches.\n')
		},
		{
			name: 'mechanics.pdf',
			mimeType: 'application/pdf',
			buffer: pdf('Newtonian mechanics', [
				'A net force on an object equals its mass times its acceleration.',
				'Momentum is mass times velocity.'
			])
		}
	]);
	await expect(page.getByTestId('pipeline-pill').first()).toBeVisible({ timeout: 15_000 });
	await expect(page.getByText('Extracting…')).toBeVisible();
	await page.screenshot({ path: test.info().outputPath('running.png'), animations: 'disabled' });

	await expect(page.getByTestId('graph-canvas')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByTestId('pipeline-pill')).toHaveCount(0, { timeout: 30_000 });
	const graph = await (await request.get('/api/graph')).json();
	expect(graph.propositions).toHaveLength(6);
	expect(Object.values(graph.file_sources).sort()).toEqual(['limits.md', 'mechanics.pdf']);
	await waitForLayout(request, 7);
	await page.waitForTimeout(800);
	await page.screenshot({ path: test.info().outputPath('imported.png'), animations: 'disabled' });

	await page.getByTestId('import-notes').click();
	const second = page.waitForEvent('filechooser');
	await page.getByRole('button', { name: 'Files', exact: true }).click();
	await (
		await second
	).setFiles([{ name: 'diagram.png', mimeType: 'image/png', buffer: Buffer.from('not text') }]);
	await expect(page.getByRole('alert')).toContainText(
		"Skipped 1 file that isn't text, Markdown, or PDF (.png)."
	);
	await page.screenshot({ path: test.info().outputPath('skipped.png'), animations: 'disabled' });

	const settings = await (await request.get('/api/settings')).json();
	delete settings.file_access_error;
	const cleared = await request.put('/api/settings', {
		data: { ...settings, models: { ...settings.models, cheap: null } }
	});
	expect(cleared.ok()).toBe(true);

	const folderRoot = await mkdtemp(join(tmpdir(), 'verstehen-unconfigured-'));
	try {
		const folder = join(folderRoot, 'unconfigured-notes');
		await mkdir(join(folder, 'topic'), { recursive: true });
		await writeFile(join(folder, 'topic', 'draft.md'), '# Draft\n\nNo model configured.\n');
		await page.getByTestId('import-notes').click();
		const folderChooser = page.waitForEvent('filechooser');
		await page.getByRole('button', { name: 'Folder', exact: true }).click();
		await (await folderChooser).setFiles(folder);
		await expect(page.getByRole('alert')).toContainText('models_not_configured');
		await expect(page.getByRole('alert')).toContainText(
			'No model configured — set up your models first'
		);
		await page.screenshot({
			path: test.info().outputPath('refused-folder.png'),
			animations: 'disabled'
		});
	} finally {
		await rm(folderRoot, { recursive: true, force: true });
	}

	await page.getByTestId('open-chain-table').click();
	const table = page.getByTestId('chain-table');
	await expect(table).toBeVisible();
	await expect(table.locator('[data-testid^="folder-row-"]')).toHaveCount(0);
	await expect(table).not.toContainText('unconfigured-notes');
	await expect(table).not.toContainText('topic');
	await expect(table).not.toContainText('draft');
	const directory = await (await request.get('/api/graph/sources')).json();
	expect(directory.organization.folders).toEqual([]);
	expect(directory.sources.map((s: { file_path?: string }) => s.file_path).sort()).toEqual([
		'limits.md',
		'mechanics.pdf'
	]);
	await page.screenshot({
		path: test.info().outputPath('refused-chains.png'),
		animations: 'disabled'
	});
});
