export function slugFilename(title: string): string {
	const slug = title
		.toLowerCase()
		.normalize('NFKD')
		.replace(/[\u0300-\u036f]/g, '')
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 64);
	return slug || 'demo';
}

export function downloadFile(name: string, content: string, mime: string): void {
	const url = URL.createObjectURL(new Blob([content], { type: mime }));
	const link = document.createElement('a');
	link.href = url;
	link.download = name;
	link.click();
	URL.revokeObjectURL(url);
}
