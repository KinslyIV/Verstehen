import { expect, test } from 'vitest';
import {
	buildAnswer,
	emptyDraft,
	seededRandom,
	shuffleOptions,
	toggleDontKnow,
	toggleOption,
	toggleOther
} from './question-core.js';
import { parseQuestionInput, questionNeedsReveal } from './question-input.js';
import { answerForPresentation } from './answer-presentation.js';
import { needsContinuation, pendingQuestionOf, questionCallsOf } from './pending.js';
import { probeArguments, questionBatch, questionResult } from './question-fixtures.js';

test('shuffle_matches_learnharness_for_known_ids', () => {
	const options = Array.from({ length: 6 }, (_, i) => ({
		label: String(i + 1),
		value: String(i + 1)
	}));
	for (const [seed, expected] of Object.entries({
		'call-1-0': '214536',
		'quiz-a': '412365',
		'λ🧪': '641532'
	})) {
		expect(
			shuffleOptions(options, seededRandom(seed))
				.map(({ value }) => value)
				.join('')
		).toBe(expected);
	}
	expect(options.map(({ value }) => value).join('')).toBe('123456');
});

test('quiz_grades_the_exact_set_of_display_indices_and_drops_confidence_on_dont_know', () => {
	const question = parseQuestionInput(
		'probe',
		{
			...probeArguments,
			options: [...probeArguments.options, { label: 'Four', value: 'four.' }],
			correctAnswer: ['four.', ':two'],
			multiSelect: true
		},
		'random-id'
	)!;
	const answer = buildAnswer(question, {
		values: ['four.', 'two'],
		confidence: 50,
		thinking: ' Divisible by two. '
	});
	expect(answer.correct).toBe(true);
	expect(answer.answers.map(({ index }) => index)).toEqual(answer.correct_indices);
	expect(answer.confidence).toBe(50);
	expect(answer.thinking).toBe('Divisible by two.');
	expect(buildAnswer(question, { values: ['two'], confidence: 70 }).correct).toBe(false);
	const unknown = buildAnswer(question, { dontKnow: true, confidence: 70 });
	expect(unknown.correct).toBe(false);
	expect(unknown.confidence).toBeUndefined();
});

test('ask_answers_preserve_other_and_plain_text_without_grading', () => {
	const question = parseQuestionInput('ask_user_question', {
		question: 'Preference?',
		options: probeArguments.options
	})!;
	expect(buildAnswer(question, { values: ['two'], other: ' Ten ' })).toMatchObject({
		kind: 'ask',
		other: 'Ten',
		answers: [{ index: 1, label: 'Two', value: 'two' }]
	});
	const open = parseQuestionInput('ask_user_question', { question: 'Preference?' })!;
	const answer = buildAnswer(open, { text: 'Use a **graph**. ' });
	expect(answer.text).toBe('Use a **graph**.');
	expect(answer.correct).toBeUndefined();
});

test('explain_snapshots_the_committed_answer_without_grading', () => {
	const question = parseQuestionInput('recall', {
		question: 'What is a derivative?',
		correctAnswer: 'The instantaneous rate of change.'
	})!;
	expect(buildAnswer(question, { text: ' A slope. ' })).toMatchObject({
		kind: 'explain',
		text: 'A slope.',
		committed: 'The instantaneous rate of change.'
	});
	expect(buildAnswer(question, { text: 'A slope.' }).correct).toBeUndefined();
});

test('single_select_displaces_other_and_never_toggles_off_a_listed_option', () => {
	const selected = toggleOption('single-select', emptyDraft().selection, 1);
	expect(toggleOption('single-select', selected, 1)).toEqual(selected);
	const other = toggleOther('single-select', selected);
	expect(other).toEqual({ selected: new Set(), otherSelected: true, dontKnow: false });
	expect(toggleOption('single-select', other, 1)).toEqual(selected);
});

test('multi_select_toggles_each_option_and_other_independently', () => {
	let state = toggleOption('multi-select', emptyDraft().selection, 1);
	state = toggleOther('multi-select', state);
	state = toggleOption('multi-select', state, 2);
	expect(state.selected).toEqual(new Set([1, 2]));
	expect(state.otherSelected).toBe(true);
	state = toggleOption('multi-select', state, 1);
	expect(toggleOther('multi-select', state)).toEqual({
		selected: new Set([2]),
		otherSelected: false,
		dontKnow: false
	});
	expect(toggleDontKnow(state)).toEqual({
		selected: new Set(),
		otherSelected: false,
		dontKnow: true
	});
});

test('raw_arguments_keep_exact_keys_and_heal_model_encoded_options', () => {
	const options = [
		{ label: 'Dot.', value: 'dot.' },
		{ label: 'Seven', value: 7 }
	];
	const question = parseQuestionInput(
		'probe',
		JSON.stringify({
			...probeArguments,
			options: JSON.stringify(options),
			correctAnswer: '["dot.", 7]',
			multiSelect: 'true'
		})
	);
	expect(question?.correctIndices).toEqual([1, 2]);
	expect(
		parseQuestionInput('probe', { ...probeArguments, correctAnswer: 'missing' })
	).toBeUndefined();
	expect(
		parseQuestionInput('probe', { ...probeArguments, options: [options[0], options[0]] })
	).toBeUndefined();
});

test('only_teach_checks_would_need_reveal', () => {
	expect(questionNeedsReveal('quiz', { type: '"predict"' }, 'teach')).toBe(false);
	expect(questionNeedsReveal('explain', { type: 'check' }, 'teach')).toBe(true);
	expect(questionNeedsReveal('probe', {}, 'teach')).toBe(false);
	expect(questionNeedsReveal('quiz', {}, 'probe')).toBe(false);
});

test('pending_question_is_the_first_answerable_call_of_the_latest_completed_response', () => {
	const owner = questionBatch('one', 'two');
	expect(pendingQuestionOf([owner], owner.entry_id)).toBeUndefined();
	expect(pendingQuestionOf([owner])?.toolCallId).toBe('one');
	expect(pendingQuestionOf([owner, questionResult('one')])?.toolCallId).toBe('two');
	expect(
		questionCallsOf([{ ...owner, stop_reason: 'length' }]).map(({ question }) => question)
	).toEqual([undefined, undefined]);
	expect(
		pendingQuestionOf([
			owner,
			{ kind: 'assistant', entry_id: 'a2', parts: [], stop_reason: 'stop' }
		])
	).toBeUndefined();
});

test('continuation_waits_for_the_whole_batch_and_respects_dismissal_and_recovery', () => {
	const owner = questionBatch('one', 'two');
	const one = questionResult('one');
	const two = questionResult('two');
	expect(needsContinuation([owner, one])).toBe(false);
	expect(needsContinuation([owner, one, two])).toBe(true);
	expect(needsContinuation([owner, one, { ...two, details: { dismissed: true } }])).toBe(false);
	expect(
		needsContinuation([
			owner,
			one,
			{ ...two, is_error: true, details: { question_recovery: true } }
		])
	).toBe(false);
	expect(
		needsContinuation([
			owner,
			one,
			two,
			{ kind: 'marker', marker_type: 'side-question', content: '', display: true }
		])
	).toBe(true);
	expect(needsContinuation([owner, one, two, { kind: 'user', text: 'Next' }])).toBe(false);
});

test('presentation_recovers_model_text_without_reordering_or_regrading_saved_answers', () => {
	const question = parseQuestionInput('probe', probeArguments)!;
	const answer = buildAnswer(question, { values: ['two'], confidence: 90 });
	const rewritten = parseQuestionInput('probe', {
		...probeArguments,
		question: 'Updated question',
		options: [
			{ label: 'Three.', value: 'three' },
			{ label: 'Two.', value: 'two' }
		]
	})!;
	const projected = answerForPresentation(answer, rewritten);
	expect(projected.question_text).toBe('Updated question');
	expect(projected.options).toEqual([
		{ index: 1, label: 'Two.' },
		{ index: 2, label: 'Three.' }
	]);
	expect(projected.answers).toEqual(answer.answers);
	expect(projected.correct_indices).toEqual(answer.correct_indices);
	expect(answer.options?.[0]?.label).toBe('Two');
});

test('check_answers_keep_reading_thinking_separate_from_answer_thinking', () => {
	const question = parseQuestionInput('quiz', {
		...probeArguments,
		nodeId: 'slope',
		type: 'check'
	})!;
	expect(
		buildAnswer(question, {
			values: ['two'],
			readingThinking: ' The explanation compares slopes. ',
			thinking: ' I chose the steeper one. '
		})
	).toMatchObject({
		reading_thinking: 'The explanation compares slopes.',
		thinking: 'I chose the steeper one.'
	});
	expect(buildAnswer(question, { readingThinking: '  ' }).reading_thinking).toBeUndefined();
});
