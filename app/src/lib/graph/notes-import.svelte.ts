import { importNotes } from '#lib/api/client.js';
import { createNotesImportQueue, type ImportQueueSnapshot } from './import-queue.js';

const queue = createNotesImportQueue(importNotes);

/** The shared notes-import queue as rune state; `onfinish` fires each time it drains. */
export class NotesImport {
	snapshot = $state.raw<ImportQueueSnapshot>(queue.getSnapshot());
	private unsubscribe: () => void;

	constructor(onfinish: () => void) {
		let completion = queue.getSnapshot().completion;
		this.unsubscribe = queue.subscribe(() => {
			this.snapshot = queue.getSnapshot();
			if (this.snapshot.completion !== completion) {
				completion = this.snapshot.completion;
				onfinish();
			}
		});
	}

	add(files: FileList | null): void {
		if (files && files.length > 0) queue.append(Array.from(files));
	}

	dispose(): void {
		this.unsubscribe();
	}
}
