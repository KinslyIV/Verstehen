/** Resolve a CSS color (oklch in this app) to #rrggbb through a 1px canvas. */
function cssColorToHex(css: string): string {
	const canvas = document.createElement('canvas');
	canvas.width = 1;
	canvas.height = 1;
	const ctx = canvas.getContext('2d', { willReadFrequently: true });
	if (!ctx) return '#888888';
	ctx.fillStyle = css;
	ctx.fillRect(0, 0, 1, 1);
	const { data } = ctx.getImageData(0, 0, 1, 1);
	return `#${[data[0], data[1], data[2]].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

/** A theme token such as `--primary` as hex; the canvas cannot read CSS variables. */
export function tokenHex(cssVariable: string): string {
	const value = getComputedStyle(document.documentElement).getPropertyValue(cssVariable).trim();
	return value ? cssColorToHex(value) : '#888888';
}
