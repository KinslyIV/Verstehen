import { ApiError } from '#lib/api/client.js';

export const TRACES_COPY = {
	testid: 'delete-traces',
	checkbox: 'delete-traces-checkbox',
	title: 'Also remove its graph traces',
	body: 'This session’s topics, links, and events leave the graph too. Topics other sessions or imported notes also cover survive; topics only this session created are removed entirely.'
};

export const EXTRACTION_RETRY_LINE = 'An extraction is running — try again when it finishes.';

/** What a failed delete says: the extraction line for a running extraction, else the server's own text. */
export function deleteFailureText(cause: unknown): string {
	if (cause instanceof ApiError)
		return cause.code === 'extraction_running' ? EXTRACTION_RETRY_LINE : cause.message;
	return 'Delete failed — network error. Try again.';
}

/** The names a delete dialog lists: at most eight, then how many more. */
export function nameList(names: string[]): string {
	return names.slice(0, 8).join(', ') + (names.length > 8 ? `, and ${names.length - 8} more` : '');
}
