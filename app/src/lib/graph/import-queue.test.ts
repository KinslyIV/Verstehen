import { describe, expect, it } from 'vitest';
import type { ImportResult } from '#lib/api/client.js';
import { MAX_IMPORT_BYTES, createNotesImportQueue } from './import-queue.js';

const tick = () => new Promise<void>((done) => setTimeout(done, 0));
const file = (name: string, path?: string) => {
	const f = new File(['notes'], name);
	if (path) Object.defineProperty(f, 'webkitRelativePath', { value: path });
	return f;
};
const success = (name: string): ImportResult => ({
	request_index: 0,
	file_path: name,
	ok: true,
	outcome: 'completed',
	stats: { nodes: 0, chains: 0, dropped_chains: 0 }
});

describe('notes import queue', () => {
	it('stays three-wide across selections, refilling behind a slow first file', async () => {
		const calls: {
			file: File;
			resolve: (result: ImportResult) => void;
			reject: (error: Error) => void;
		}[] = [];
		const queue = createNotesImportQueue(
			(f) => new Promise((resolve, reject) => calls.push({ file: f, resolve, reject }))
		);
		queue.append(['a', 'b', 'c', 'd'].map((n) => file(`${n}.md`)));
		queue.append(['e', 'f'].map((n) => file(`${n}.md`)));
		expect(calls).toHaveLength(3);
		calls[1].resolve(success('b.md'));
		await tick();
		expect(calls).toHaveLength(4);
		expect(calls[3].file.name).toBe('d.md');
		calls[2].reject(new Error('lost response'));
		await tick();
		expect(calls).toHaveLength(5);
		calls[3].resolve(success('d.md'));
		calls[4].resolve(success('e.md'));
		await tick();
		calls[5].resolve(success('f.md'));
		await tick();
		expect(queue.getSnapshot().importing).toBe(true);
		expect(queue.getSnapshot().completion).toBe(0);
		calls[0].resolve(success('a.md'));
		await tick();
		expect(queue.getSnapshot().importing).toBe(false);
		expect(queue.getSnapshot().completion).toBe(1);
		expect(queue.getSnapshot().errors).toEqual(['c.md: lost response']);
		expect(calls).toHaveLength(6);
	});

	it('keeps errors and notices in selection order when requests settle backwards', async () => {
		const pending: ((result: ImportResult) => void)[] = [];
		const queue = createNotesImportQueue(() => new Promise((resolve) => pending.push(resolve)));
		queue.append([file('same.md', 'A/same.md'), file('same.md', 'B/same.md')]);
		queue.append([file('c.pdf', 'B/c.pdf')]);
		pending[2]({ ...success('B/c.pdf'), notice: 'Scanner caveat' });
		pending[1]({ ...success('B/same.md'), ok: false, outcome: 'partial', error: 'second' });
		pending[0]({ ...success('A/same.md'), ok: false, outcome: 'busy', error: 'first' });
		await tick();
		expect(queue.getSnapshot().errors).toEqual(['A/same.md: first', 'B/same.md: second']);
		expect(queue.getSnapshot().notices).toEqual(['B/c.pdf: Scanner caveat']);
	});

	it('sends only supported, safe files and summarizes what it skipped', async () => {
		const paths: string[] = [];
		const queue = createNotesImportQueue(async (_f, path) => {
			paths.push(path);
			return success(path);
		});
		queue.append([
			file('.DS_Store', 'Root/.DS_Store'),
			file('a.png', 'Root/Images/a.png'),
			file('notes.md', 'Root/Sub/notes.md'),
			file('bad.pptx', '../bad.pptx')
		]);
		await tick();
		expect(paths).toEqual(['Root/Sub/notes.md']);
		expect(queue.getSnapshot().errors).toEqual([
			"Skipped 1 file that isn't text, Markdown, or PDF (.png).",
			"Skipped 1 file with a name the import can't use (e.g. a ':' in the name)."
		]);
	});

	it('skips dot-directories and hidden files in folder picks, even below a hidden root', async () => {
		const paths: string[] = [];
		const queue = createNotesImportQueue(async (_f, path) => {
			paths.push(path);
			return success(path);
		});
		queue.append([
			file('app.json', 'Vault/.obsidian/app.json'),
			file('config', 'Vault/.git/config'),
			file('.draft.md', 'Vault/.draft.md'),
			file('notes.v2.md', 'Vault/Course.v2/notes.v2.md')
		]);
		queue.append([file('a.md', '.notes/a.md')]);
		await tick();
		expect(paths).toEqual(['Vault/Course.v2/notes.v2.md', '.notes/a.md']);
		expect(queue.getSnapshot().errors).toEqual([]);
	});

	it('imports hidden notes picked as files and reports unsupported dotfiles', async () => {
		const paths: string[] = [];
		const queue = createNotesImportQueue(async (f) => {
			paths.push(f.name);
			return success(f.name);
		});
		queue.append([file('.draft.md'), file('.DS_Store')]);
		await tick();
		expect(paths).toEqual(['.draft.md']);
		expect(queue.getSnapshot().errors).toEqual([
			"Skipped 1 file that isn't text, Markdown, or PDF (no extension)."
		]);
	});

	it('checks the file type before the size and reports oversized files', () => {
		const queue = createNotesImportQueue(async (f) => success(f.name));
		const huge = (name: string) => {
			const f = file(name);
			Object.defineProperty(f, 'size', { value: MAX_IMPORT_BYTES + 1 });
			return f;
		};
		queue.append([huge('huge.docx'), huge('huge.md')]);
		expect(queue.getSnapshot().errors).toEqual([
			"Skipped 1 file that isn't text, Markdown, or PDF (.docx).",
			'huge.md: Too big. Max 25 MB.'
		]);
	});

	it('shows a failed result with its code and reason on a second line', async () => {
		const queue = createNotesImportQueue(async (f) => ({
			...success(f.name),
			ok: false,
			outcome: 'failed',
			error: 'No model',
			code: 'models_not_configured',
			reason: 'slot cheap',
			missing: ['cheap']
		}));
		queue.append([file('a.md')]);
		await tick();
		expect(queue.getSnapshot().errors).toEqual([
			'a.md: No model\nmodels_not_configured — slot cheap — cheap'
		]);
	});
});
