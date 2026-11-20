/** Scores fields against a space-separated query: null when a token matches none, else higher is better. */
export function fuzzyScore(query: string, ...fields: string[]): number | null {
	const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
	if (tokens.length === 0) return 0;
	const haystack = fields.map((field) => field.toLowerCase());
	let total = 0;
	for (const token of tokens) {
		let best = -1;
		for (const field of haystack) {
			if (field === token) best = Math.max(best, 100);
			else if (field.startsWith(token)) best = Math.max(best, 60);
			else {
				const at = field.indexOf(token);
				if (at !== -1) best = Math.max(best, 30 - Math.min(at, 27));
			}
		}
		if (best < 0) return null;
		total += best;
	}
	if (haystack.some((field) => field.includes(tokens.join(' ')))) total += 50;
	return total;
}
