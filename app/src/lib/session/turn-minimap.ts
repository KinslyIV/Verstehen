import type { Entry, QuestionAnswer, ToolResult } from '#lib/api/client.js';
import type { Question } from '#lib/questions/question-core.js';
import { responseProse } from '#lib/teaching/response-prose.js';

export type TurnTick = {
	/** The transcript entry the tick jumps to; also the scroller item's message id. */
	id: string;
	kind: 'message' | 'question' | 'problem';
	label: string;
	excerpt: string;
};

export const TICK_SPACING = 8;
const FISHEYE_RADIUS = 32;
const FISHEYE_MAX = 2.5;
const EXCERPT_LENGTH = 160;

function excerptOf(text: string) {
	const flat = text.replace(/\s+/g, ' ').trim();
	return flat.length > EXCERPT_LENGTH ? `${flat.slice(0, EXCERPT_LENGTH).trimEnd()}…` : flat;
}

function answerText(answer: QuestionAnswer) {
	if (answer.dont_know) return "I don't know";
	const picked = new Set(answer.answers.map(({ index }) => index));
	const labels = (answer.options ?? [])
		.filter(({ index }) => picked.has(index))
		.map((o) => o.label);
	return [...labels, answer.other, answer.text].filter(Boolean).join(', ');
}

/** One tick per typed message, answered question, and practice problem, in transcript order. */
export function turnTicks(
	entries: Entry[],
	cards: Map<string, { answer: QuestionAnswer; source?: Question }>,
	results: Map<string, Map<string, ToolResult>>
): TurnTick[] {
	const ticks: TurnTick[] = [];
	for (const entry of entries) {
		const id = entry.entry_id;
		if (!id) continue;
		const card = cards.get(id);
		if (entry.kind === 'user') {
			ticks.push({ id, kind: 'message', label: 'You', excerpt: excerptOf(entry.text) });
		} else if (card && !card.answer.dismissed) {
			const answer = answerText(card.answer);
			ticks.push({
				id,
				kind: 'question',
				label: 'Question',
				excerpt: excerptOf(
					answer ? `${card.answer.question_text} — ${answer}` : card.answer.question_text
				)
			});
		} else if (entry.kind === 'assistant') {
			const problem = responseProse(entry, results.get(id), false).find(
				(item) => item.kind === 'problem'
			);
			if (problem) {
				ticks.push({
					id,
					kind: 'problem',
					label: 'Problem',
					excerpt: excerptOf(problem.statement)
				});
			}
		}
	}
	return ticks;
}

/** Vertical centre of tick `index` when `count` ticks are spread evenly over `height`. */
export function tickCenter(index: number, count: number, height: number) {
	return ((index + 0.5) * height) / count;
}

/** The tick closest to pointer position `y`, or undefined when there are none. */
export function nearestTick(y: number, count: number, height: number) {
	if (count === 0 || height <= 0) return undefined;
	return Math.min(count - 1, Math.max(0, Math.floor((y / height) * count)));
}

/** Growth factor from 1 (far from the pointer) to 2.5 (under it), eased like a fisheye lens. */
export function fisheyeScale(distance: number) {
	const reach = Math.abs(distance);
	if (reach >= FISHEYE_RADIUS) return 1;
	return 1 + ((FISHEYE_MAX - 1) * (1 + Math.cos((Math.PI * reach) / FISHEYE_RADIUS))) / 2;
}

/** Top of the preview card inside the rail, kept `half` px away from the transcript's edges. */
export function previewTop(center: number, railHeight: number, areaHeight: number, half: number) {
	const offset = (areaHeight - railHeight) / 2;
	const inArea = Math.min(Math.max(offset + center, half), Math.max(half, areaHeight - half));
	return inArea - offset;
}

/** The last tick whose item is on screen, or undefined when none is. */
export function activeTickId(ticks: TurnTick[], visibleIds: string[]) {
	const visible = new Set(visibleIds);
	return ticks.findLast((tick) => visible.has(tick.id))?.id;
}
