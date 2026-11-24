/** The query string that opens the new-session page for a kind, optionally into a folder. */
export function newSessionQuery(mode: 'teach' | 'practice', folderId?: string): string {
	const parts = [
		...(mode === 'practice' ? ['mode=practice'] : []),
		...(folderId ? [`folder=${encodeURIComponent(folderId)}`] : [])
	];
	return parts.length ? `?${parts.join('&')}` : '';
}
