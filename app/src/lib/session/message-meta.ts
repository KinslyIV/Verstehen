import type { ResponseItem } from '#lib/teaching/response-prose.js';

export interface FormattedMessageTime {
	short: string;
	full: string;
}

/** Formats an ISO timestamp for message footers: time today, month/day + time this year, else with year. */
export function formatMessageTime(
	iso: string | undefined,
	now = new Date()
): FormattedMessageTime | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return null;
	const sameYear = date.getFullYear() === now.getFullYear();
	const sameDay =
		sameYear && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
	const short = new Intl.DateTimeFormat(undefined, {
		...(sameDay ? {} : { month: 'short', day: 'numeric' }),
		...(sameYear ? {} : { year: 'numeric' }),
		hour: '2-digit',
		minute: '2-digit'
	}).format(date);
	const full = new Intl.DateTimeFormat(undefined, {
		dateStyle: 'medium',
		timeStyle: 'medium'
	}).format(date);
	return { short, full };
}

/** Collects visible markdown prose blocks from a rendered assistant reply for copying. */
export function copyableAssistantText(items: ResponseItem[]): string {
	return items
		.filter((item): item is Extract<ResponseItem, { kind: 'text' }> => item.kind === 'text')
		.map((item) => item.text)
		.join('\n\n')
		.trim();
}
