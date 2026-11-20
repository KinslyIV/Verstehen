import type { ImportResult } from '#lib/api/client.js';

export const MAX_IMPORT_BYTES = 25 * 1024 * 1024;
const IMPORT_EXTENSION_NAMES = ['txt', 'md', 'markdown', 'rst', 'org', 'adoc', 'tex', 'pdf'];
const IMPORT_EXTENSIONS = new RegExp(`\\.(?:${IMPORT_EXTENSION_NAMES.join('|')})$`, 'i');
export const IMPORT_ACCEPT = IMPORT_EXTENSION_NAMES.map((name) => `.${name}`).join(',');
const CONCURRENT_IMPORTS = 3;

/** The name an imported file is known by: its folder-relative path, else its file name. */
export const notesPath = (file: File): string => file.webkitRelativePath || file.name;

/** A relative path that is identity only: no backslash, colon, control characters, or dot parts. */
export function validNotesPath(path: string, filename: string): boolean {
	const parts = path.split('/');
	return (
		path.length > 0 &&
		path.length <= 1024 &&
		// eslint-disable-next-line no-control-regex
		!/[\\:\x00-\x1f\x7f]/.test(path) &&
		parts.every((part) => part.length > 0 && part !== '.' && part !== '..') &&
		(parts.at(-1) === filename || path === filename)
	);
}

/** Folder picks skip dot-prefixed files and folders below the chosen root. */
const hiddenInFolder = (file: File): boolean =>
	file.webkitRelativePath
		.split('/')
		.slice(1)
		.some((part) => part.startsWith('.'));

const extensionLabel = (name: string): string => {
	const dot = name.lastIndexOf('.');
	return dot > 0 && dot < name.length - 1 ? name.slice(dot).toLowerCase() : 'no extension';
};

const unsupportedSummary = (extensions: readonly string[]): string =>
	`Skipped ${extensions.length} ${extensions.length === 1 ? "file that isn't" : "files that aren't"} text, Markdown, or PDF (${[...new Set(extensions)].join(', ')}).`;

const unsafeSummary = (count: number): string =>
	`Skipped ${count} ${count === 1 ? 'file with a name' : 'files with names'} the import can't use (e.g. a ':' in the name).`;

export interface ImportQueueSnapshot {
	importing: boolean;
	errors: string[];
	notices: string[];
	/** Counts each time the queue drains, so listeners can refresh once per batch. */
	completion: number;
}

export const EMPTY_IMPORT_QUEUE: ImportQueueSnapshot = {
	importing: false,
	errors: [],
	notices: [],
	completion: 0
};

export type PostNotes = (file: File, path: string) => Promise<ImportResult | undefined>;

/** One queue per page: three uploads at a time; a failed file is reported, never retried. */
export function createNotesImportQueue(post: PostNotes) {
	const listeners = new Set<() => void>();
	const pending: { file: File; index: number }[] = [];
	const failures = new Map<number, string>();
	const notices = new Map<number, string>();
	let active = 0;
	let sequence = 0;
	let snapshot = EMPTY_IMPORT_QUEUE;
	const ordered = (map: Map<number, string>) =>
		[...map].sort(([a], [b]) => a - b).map(([, text]) => text);
	const publish = (completed = false) => {
		snapshot = {
			importing: active > 0 || pending.length > 0,
			errors: ordered(failures),
			notices: ordered(notices),
			completion: snapshot.completion + Number(completed)
		};
		for (const listener of [...listeners]) listener();
	};

	function pump(): void {
		while (active < CONCURRENT_IMPORTS && pending.length > 0) {
			const { file, index } = pending.shift()!;
			active++;
			void (async () => {
				try {
					const result = await post(file, notesPath(file));
					if (!result) throw new Error('Invalid import response. Check the graph before retrying.');
					if (!result.ok) {
						const details = [result.reason, result.missing?.join(', ')].filter(Boolean);
						failures.set(
							index,
							`${result.file_path}: ${result.error}${result.code ? `\n${[result.code, ...details].join(' — ')}` : ''}`
						);
					} else if (result.notice) notices.set(index, `${result.file_path}: ${result.notice}`);
				} catch (error) {
					failures.set(
						index,
						`${notesPath(file)}: ${error instanceof Error ? error.message : String(error)}`
					);
				} finally {
					active--;
					pump();
					publish(active === 0 && pending.length === 0);
				}
			})();
		}
	}

	return {
		getSnapshot: () => snapshot,
		subscribe(listener: () => void) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
		append(files: readonly File[]) {
			if (files.length === 0) return;
			if (!snapshot.importing) {
				failures.clear();
				notices.clear();
				sequence = 0;
			}
			const unsafe: number[] = [];
			const unsupported: { index: number; extension: string }[] = [];
			for (const file of files) {
				const index = sequence++;
				const path = notesPath(file);
				if (file.webkitRelativePath && hiddenInFolder(file)) continue;
				if (!validNotesPath(path, file.name)) unsafe.push(index);
				else if (!IMPORT_EXTENSIONS.test(file.name))
					unsupported.push({ index, extension: extensionLabel(file.name) });
				else if (file.size > MAX_IMPORT_BYTES) failures.set(index, `${path}: Too big. Max 25 MB.`);
				else pending.push({ file, index });
			}
			if (unsafe.length > 0) failures.set(unsafe[0], unsafeSummary(unsafe.length));
			if (unsupported.length > 0)
				failures.set(
					unsupported[0].index,
					unsupportedSummary(unsupported.map(({ extension }) => extension))
				);
			const hadWork = active > 0 || pending.length > 0;
			pump();
			publish(!hadWork);
		}
	};
}
