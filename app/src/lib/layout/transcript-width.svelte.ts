export const MIN_REM = 46;
export const MAX_REM = 120;
export const STEP_REM = 2;
const storageKey = 'verstehen-transcript-width';
const cssVariable = '--verstehen-transcript-max';

/** The stored rem width, or null for Full (also for a missing or invalid value). */
export function parseWidth(stored: string | null): number | null {
	const rem = Number(stored);
	const valid = Number.isInteger(rem) && rem >= MIN_REM && rem <= MAX_REM;
	return valid && (rem - MIN_REM) % STEP_REM === 0 ? rem : null;
}

function read(): number | null {
	try {
		return parseWidth(localStorage.getItem(storageKey));
	} catch {
		return null;
	}
}

/** How wide the lesson column may grow on this device; null means Full. */
export class TranscriptWidth {
	rem = $state<number | null>(read());

	set(next: number | null): void {
		this.rem = next;
		const style = document.documentElement.style;
		if (next === null) style.removeProperty(cssVariable);
		else style.setProperty(cssVariable, `${next}rem`);
		try {
			if (next === null) localStorage.removeItem(storageKey);
			else localStorage.setItem(storageKey, String(next));
		} catch {
			/* The width still applies for this visit. */
		}
	}
}

export const transcriptWidth = new TranscriptWidth();
