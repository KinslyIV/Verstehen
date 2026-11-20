export const concurrencyError = 'Enter a positive, safely representable whole number.';

export function parseConcurrency(value: string): number | null | undefined {
	const draft = value.trim();
	if (!draft) return null;
	const number = Number(draft);
	if (!Number.isSafeInteger(number) || number <= 0) return undefined;
	const decimal = draft.match(/^\+?(\d+(?:\.\d*)?|\.\d+)(?:e([+-]?\d+))?$/i);
	if (!decimal) return undefined;
	const mantissa = decimal[1];
	const fractionalPlaces = mantissa.split('.')[1]?.length ?? 0;
	const coefficient = mantissa.replace('.', '');
	const trailingZeroes = coefficient.length - coefficient.replace(/0+$/, '').length;
	return Number(decimal[2] ?? 0) - fractionalPlaces + trailingZeroes < 0 ? undefined : number;
}
