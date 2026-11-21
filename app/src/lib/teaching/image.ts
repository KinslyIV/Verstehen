export type ShownImage = {
	path: string;
	caption?: string;
	mime_type: 'image/png' | 'image/jpeg';
	sha256: string;
	width: number;
	height: number;
};

export function shownImage(value: unknown): ShownImage | undefined {
	if (!value || typeof value !== 'object') return;
	const image = value as Partial<ShownImage>;
	if (
		typeof image.path === 'string' &&
		typeof image.sha256 === 'string' &&
		/^[a-f0-9]{64}$/.test(image.sha256) &&
		(image.mime_type === 'image/png' || image.mime_type === 'image/jpeg') &&
		typeof image.width === 'number' &&
		Number.isInteger(image.width) &&
		image.width > 0 &&
		typeof image.height === 'number' &&
		Number.isInteger(image.height) &&
		image.height > 0 &&
		(image.caption === undefined || typeof image.caption === 'string')
	)
		return image as ShownImage;
}
