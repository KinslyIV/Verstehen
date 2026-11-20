import type { Entry, QuestionAnswer } from '#lib/api/client.js';
import { asObject, parseQuestionInput } from './question-input.js';
import { questionKinds, type Question, type QuestionTool } from './question-core.js';
import { recoverToolContent } from '#lib/markdown/tool-content.js';

export function answerForPresentation(answer: QuestionAnswer, source?: Question): QuestionAnswer {
	if (!source || answer.dismissed) return answer;
	const projected = { ...answer, question_text: source.question };
	if (answer.kind === 'quiz') projected.explanation = source.explanation;
	if (answer.kind === 'explain') projected.committed = source.committed;
	const saved = answer.options;
	const original = source.options;
	if (!saved?.length || !original.length) return projected;

	const bindings = new Map<number, number>();
	const used = new Set<number>();
	function bindUnique(candidates: number[][]) {
		for (const [index, row] of candidates.entries()) {
			if (bindings.has(index)) continue;
			const possible = row.filter((position) => !used.has(position));
			if (possible.length !== 1) continue;
			const position = possible[0]!;
			if (
				candidates.some((other, i) => i !== index && !bindings.has(i) && other.includes(position))
			)
				continue;
			bindings.set(index, position);
			used.add(position);
		}
	}
	bindUnique(
		saved.map(({ index }) => {
			const values = answer.answers
				.filter((option) => option.index === index)
				.map(({ value }) => value);
			return original.flatMap(({ value }, position) => (values.includes(value) ? [position] : []));
		})
	);
	const recoveredLabels = original.map(({ label }) => recoverToolContent(label));
	bindUnique(
		saved.map(({ label }) =>
			original.flatMap((option, position) =>
				option.label === label || recoveredLabels[position] === label ? [position] : []
			)
		)
	);
	if (saved.length === original.length && bindings.size === saved.length - 1) {
		bindings.set(
			saved.findIndex((_, i) => !bindings.has(i)),
			original.findIndex((_, i) => !used.has(i))
		);
	}
	projected.options = saved.map((option, i) => {
		const position = bindings.get(i);
		return position === undefined ? option : { ...option, label: original[position]!.label };
	});
	return projected;
}

/** Pair each answer with the call in its own batch, including reused call IDs. */
export function answeredQuestions(entries: Entry[]) {
	const cards = new Map<string, { answer: QuestionAnswer; source?: Question }>();
	let owner: Extract<Entry, { kind: 'assistant' }> | undefined;
	for (const entry of entries) {
		if (entry.kind === 'assistant') owner = entry;
		if (
			entry.kind !== 'tool_result' ||
			entry.is_error ||
			!Object.hasOwn(questionKinds, entry.tool_name)
		)
			continue;
		const details = asObject(entry.details);
		if (
			!details ||
			details.kind !== questionKinds[entry.tool_name as QuestionTool] ||
			typeof details.question_text !== 'string' ||
			!Array.isArray(details.answers)
		)
			continue;
		const call = owner?.parts.find(
			(part) =>
				part.type === 'tool_call' &&
				part.tool_call_id === entry.tool_call_id &&
				part.tool_name === entry.tool_name
		);
		const source =
			call?.type === 'tool_call'
				? parseQuestionInput(entry.tool_name as QuestionTool, call.arguments)
				: undefined;
		cards.set(entry.entry_id!, { answer: details as unknown as QuestionAnswer, source });
	}
	return cards;
}
