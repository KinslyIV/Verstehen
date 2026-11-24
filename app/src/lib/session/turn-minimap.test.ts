import { expect, test } from 'vitest';
import type { Entry, QuestionAnswer } from '#lib/api/client.js';
import { responseResults } from '#lib/teaching/delivery.js';
import { answeredQuestions } from '#lib/questions/answer-presentation.js';
import {
	activeTickId,
	fisheyeScale,
	nearestTick,
	previewTop,
	tickCenter,
	turnTicks
} from './turn-minimap.js';

const answer: QuestionAnswer = {
	kind: 'ask',
	tool: 'ask_user_question',
	question_text: 'Which example?',
	options: [
		{ index: 1, label: 'A bike' },
		{ index: 2, label: 'A clock' }
	],
	dont_know: false,
	answers: [{ index: 2, label: 'A clock', value: 'clock' }],
	answered_at: '2026-01-01T00:00:00Z'
};
const questionResult = (id: string, details: QuestionAnswer): Entry => ({
	kind: 'tool_result',
	entry_id: id,
	tool_call_id: `call-${id}`,
	tool_name: 'ask_user_question',
	is_error: false,
	text: '',
	details: details as never
});
const problemTurn: Entry[] = [
	{
		kind: 'assistant',
		entry_id: 'p',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: 'c1',
				tool_name: 'problem',
				arguments: '{"statement":"Differentiate x^3."}'
			}
		]
	},
	{
		kind: 'tool_result',
		entry_id: 'pr',
		tool_call_id: 'c1',
		tool_name: 'problem',
		is_error: false,
		text: ''
	}
];

function ticksOf(entries: Entry[]) {
	return turnTicks(entries, answeredQuestions(entries), responseResults(entries));
}

test('ticks_cover_typed_messages_answered_questions_and_problems_in_order', () => {
	const entries: Entry[] = [
		{ kind: 'user', entry_id: 'u1', text: 'Teach me\n  derivatives' },
		...problemTurn,
		questionResult('q1', answer)
	];
	expect(ticksOf(entries)).toEqual([
		{ id: 'u1', kind: 'message', label: 'You', excerpt: 'Teach me derivatives' },
		{ id: 'p', kind: 'problem', label: 'Problem', excerpt: 'Differentiate x^3.' },
		{ id: 'q1', kind: 'question', label: 'Question', excerpt: 'Which example? — A clock' }
	]);
});

test('dismissed_questions_and_plain_assistant_turns_get_no_tick', () => {
	const entries: Entry[] = [
		{
			kind: 'assistant',
			entry_id: 'a',
			stop_reason: 'stop',
			parts: [{ type: 'text', text: 'Hello' }]
		},
		questionResult('q1', { ...answer, dismissed: true, answers: [] })
	];
	expect(ticksOf(entries)).toEqual([]);
});

test('long_excerpts_are_shortened', () => {
	const [tick] = ticksOf([{ kind: 'user', entry_id: 'u', text: 'word '.repeat(100) }]);
	expect(tick!.excerpt.length).toBeLessThanOrEqual(161);
	expect(tick!.excerpt.endsWith('…')).toBe(true);
});

test('ticks_are_spread_evenly_and_the_nearest_one_is_found_from_the_pointer', () => {
	expect(tickCenter(0, 4, 56)).toBe(7);
	expect(tickCenter(3, 4, 56)).toBe(49);
	expect(nearestTick(20, 4, 56)).toBe(1);
	expect(nearestTick(-5, 4, 56)).toBe(0);
	expect(nearestTick(500, 4, 56)).toBe(3);
	expect(nearestTick(10, 0, 56)).toBeUndefined();
});

test('fisheye_scale_peaks_under_the_pointer_and_vanishes_beyond_its_reach', () => {
	expect(fisheyeScale(0)).toBe(2.5);
	expect(fisheyeScale(20)).toBeGreaterThan(fisheyeScale(40));
	expect(fisheyeScale(-20)).toBe(fisheyeScale(20));
	expect(fisheyeScale(56)).toBe(1);
	expect(fisheyeScale(300)).toBe(1);
});

test('preview_card_stays_inside_the_transcript_area', () => {
	expect(previewTop(5, 100, 400, 50)).toBe(5);
	expect(previewTop(5, 380, 400, 50)).toBe(40);
	expect(previewTop(375, 380, 400, 50)).toBe(340);
});

test('active_tick_is_the_last_visible_one', () => {
	const ticks = ticksOf([
		{ kind: 'user', entry_id: 'a', text: 'a' },
		{ kind: 'user', entry_id: 'b', text: 'b' }
	]);
	expect(activeTickId(ticks, ['a', 'b'])).toBe('b');
	expect(activeTickId(ticks, ['x'])).toBeUndefined();
});
