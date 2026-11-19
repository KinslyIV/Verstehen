export const OPENING_FAILURE =
	'Couldn’t open the session. Your message is still here. Try sending again.';
const key = (id: string) => `verstehen.opening.${id}`;
export function stashOpening(id: string, text: string, attempted = false): void {
	const value = JSON.stringify({ text, attempted });
	sessionStorage.setItem(key(id), value);
	if (sessionStorage.getItem(key(id)) !== value) throw new Error(OPENING_FAILURE);
}
export function readOpening(id: string): { text: string; attempted: boolean } | undefined {
	try {
		const value = JSON.parse(sessionStorage.getItem(key(id)) ?? 'null');
		if (typeof value?.text === 'string' && typeof value?.attempted === 'boolean') return value;
	} catch {
		return;
	}
}
