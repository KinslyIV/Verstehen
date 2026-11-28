/** The query string that opens the new-session page for a kind, optionally into a folder. */
export function newSessionQuery(mode: 'teach' | 'practice' | 'chat', folderId?: string): string {
	const parts = [
		...(mode !== 'teach' ? [`mode=${mode}`] : []),
		...(folderId ? [`folder=${encodeURIComponent(folderId)}`] : [])
	];
	return parts.length ? `?${parts.join('&')}` : '';
}
