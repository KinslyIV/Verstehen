import type { QuestionAnswer } from '#lib/api/client.js';

export const questionKinds = {
	probe: 'quiz',
	quiz: 'quiz',
	recall: 'explain',
	explain: 'explain',
	ask_user_question: 'ask'
} as const;
export type QuestionTool = keyof typeof questionKinds;
export type QuestionKind = QuestionAnswer['kind'];
export type SelectMode = 'single-select' | 'multi-select';

export interface Option {
	label: string;
	value: string;
	description?: string;
}

export interface Question {
	tool: QuestionTool;
	kind: QuestionKind;
	question: string;
	details?: string;
	options: Option[];
	mode: SelectMode | 'text';
	questionType?: 'predict' | 'check';
	correctIndices?: number[];
	explanation?: string;
	committed?: string;
}

export const CONFIDENCE_STOPS = [0, 30, 50, 70, 90, 100] as const;
export const CONFIDENCE_COLORS = [
	'#ef4444',
	'#f97316',
	'#eab308',
	'#84cc16',
	'#22c55e',
	'#10b981'
] as const;
export const DEFAULT_CONFIDENCE_INDEX = 2;

export interface DockSelection {
	selected: Set<number>;
	otherSelected: boolean;
	dontKnow: boolean;
}

export interface QuestionDraft {
	selection: DockSelection;
	thinking: string;
	readingThinking?: string;
	other: string;
	text: string;
	confidenceIndex: number;
}

export function emptyDraft(): QuestionDraft {
	return {
		selection: { selected: new Set(), otherSelected: false, dontKnow: false },
		thinking: '',
		readingThinking: '',
		other: '',
		text: '',
		confidenceIndex: DEFAULT_CONFIDENCE_INDEX
	};
}

export function toggleOption(
	mode: SelectMode,
	selection: DockSelection,
	index: number
): DockSelection {
	if (mode === 'single-select') {
		return { selected: new Set([index]), otherSelected: false, dontKnow: false };
	}
	const selected = new Set(selection.selected);
	if (selected.has(index)) selected.delete(index);
	else selected.add(index);
	return { ...selection, selected, dontKnow: false };
}

export function toggleOther(mode: SelectMode, selection: DockSelection): DockSelection {
	return mode === 'multi-select'
		? { ...selection, otherSelected: !selection.otherSelected, dontKnow: false }
		: { selected: new Set(), otherSelected: true, dontKnow: false };
}

export function toggleDontKnow(selection: DockSelection): DockSelection {
	return { selected: new Set(), otherSelected: false, dontKnow: !selection.dontKnow };
}

export function parseJson(value: unknown): unknown {
	if (typeof value !== 'string') return value;
	try {
		return JSON.parse(value);
	} catch {
		return value;
	}
}

export function normalizeOptions(
	options: { label: string; value?: string; description?: string }[]
): Option[] {
	return options.map(({ label, value, description }) => ({
		label: label.trim(),
		value: value?.trim() || label.trim(),
		description: description?.trim() || undefined
	}));
}

/** LearnHarness's FNV-1a string seed and mulberry32 generator. */
export function seededRandom(seed: string): () => number {
	let hash = 2166136261;
	for (let i = 0; i < seed.length; i++) {
		hash = Math.imul(hash ^ seed.charCodeAt(i), 16777619);
	}
	let state = hash >>> 0;
	return () => {
		state = (state + 0x6d2b79f5) | 0;
		let value = Math.imul(state ^ (state >>> 15), 1 | state);
		value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
		return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
	};
}

export function shuffleOptions(options: Option[], random = Math.random): Option[] {
	const shuffled = [...options];
	for (let i = shuffled.length - 1; i > 0; i--) {
		const j = Math.floor(random() * (i + 1));
		[shuffled[i], shuffled[j]] = [shuffled[j]!, shuffled[i]!];
	}
	return shuffled;
}

export function stripModelValueDebris(value: string): string {
	return value.replace(/^[\s:."'\x60]+|[\s:."'\x60]+$/g, '');
}

export function coerceCorrectAnswer(answer: string | string[], optionValues: string[]): string[] {
	const clean = (value: string) =>
		optionValues.includes(value.trim()) ? value.trim() : stripModelValueDebris(value);
	if (Array.isArray(answer)) return answer.map(clean);
	const trimmed = answer.trim();
	if (optionValues.includes(trimmed)) return [trimmed];
	const parsed = parseJson(trimmed);
	return Array.isArray(parsed) ? parsed.map((value) => clean(String(value))) : [clean(answer)];
}

export function resolveCorrect(answer: string | string[], options: Option[]): number[] | undefined {
	const values = options.map((option) => option.value);
	const indices = coerceCorrectAnswer(answer, values).map((value) => values.indexOf(value) + 1);
	if (!indices.length || indices.includes(0)) return;
	return [...new Set(indices)].sort((a, b) => a - b);
}

export function isCorrect(selected: number[], correct: number[]): boolean {
	const ordered = [...correct].sort((a, b) => a - b);
	return (
		selected.length === correct.length &&
		[...selected].sort((a, b) => a - b).every((index, i) => index === ordered[i])
	);
}

interface AnswerRequest {
	dontKnow?: boolean;
	values?: string[];
	other?: string;
	text?: string;
	thinking?: string;
	readingThinking?: string;
	confidence?: number;
}

export function buildAnswer(question: Question, request: AnswerRequest): QuestionAnswer {
	const dont_know = request.dontKnow === true;
	const options = question.options.map(({ label }, i) => ({ index: i + 1, label }));
	const byValue = new Map(
		question.options.map(({ value }, i) => [value, { ...options[i]!, value }])
	);
	const answers = (request.values ?? [])
		.flatMap((value) => byValue.get(value) ?? [])
		.sort((a, b) => a.index - b.index);
	const answer: QuestionAnswer = {
		kind: question.kind,
		tool: question.tool,
		question_type: question.questionType,
		question_text: question.question,
		options,
		dont_know,
		answers,
		other: request.other?.trim() || undefined,
		text: request.text?.trim() || undefined,
		thinking: request.thinking?.trim() || undefined,
		reading_thinking: request.readingThinking?.trim() || undefined,
		answered_at: new Date().toISOString()
	};
	if (question.kind === 'quiz') {
		answer.correct_indices = question.correctIndices ?? [];
		answer.correct =
			!dont_know &&
			isCorrect(
				answers.map(({ index }) => index),
				answer.correct_indices
			);
		answer.explanation = question.explanation;
		if (!dont_know && request.confidence !== undefined) {
			answer.confidence = Math.max(0, Math.min(100, Math.round(request.confidence)));
		}
	}
	if (question.kind === 'explain') answer.committed = question.committed;
	return answer;
}

export function dismissedAnswer(kind: QuestionKind, questionText: string): QuestionAnswer {
	return {
		kind,
		question_text: questionText,
		dont_know: false,
		answers: [],
		dismissed: true,
		answered_at: new Date().toISOString()
	};
}

export function questionLabel(
	kind: QuestionKind,
	tool?: string | null,
	type?: string | null
): string {
	if (tool === 'probe') return 'Probe';
	if (tool === 'recall') return 'Recall';
	if (kind === 'explain') return 'Explain';
	if (kind === 'ask') return 'Question';
	return type === 'predict' ? 'Prediction' : 'Check';
}
