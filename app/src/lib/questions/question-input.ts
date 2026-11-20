import {
	normalizeOptions,
	parseJson,
	questionKinds,
	resolveCorrect,
	seededRandom,
	shuffleOptions,
	stripModelValueDebris,
	type Option,
	type Question,
	type QuestionTool
} from './question-core.js';

export function asObject(value: unknown): Record<string, unknown> | undefined {
	if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
		return value as Record<string, unknown>;
	}
}

function modelText(value: unknown): string | undefined {
	if (value === null || ['string', 'number', 'boolean'].includes(typeof value))
		return String(value);
}

function readOptions(value: unknown, withDescriptions: boolean): Option[] | undefined {
	const parsed = parseJson(value);
	if (!Array.isArray(parsed) || parsed.length < 2) return;
	const options = [];
	for (const item of parsed) {
		const option = asObject(item);
		if (!option) return;
		const label = modelText(option.label);
		const key = modelText(option.value);
		const description = withDescriptions ? modelText(option.description) : undefined;
		if (!label?.trim() || (key === undefined && option.value !== undefined)) return;
		if (withDescriptions && description === undefined && option.description !== undefined) return;
		options.push({ label, value: key, description });
	}
	const normalized = normalizeOptions(options);
	if (new Set(normalized.map(({ value }) => value)).size === normalized.length) return normalized;
}

/** Mirror T1's display validation before using raw model arguments in the dock. */
export function parseQuestionInput(
	tool: QuestionTool,
	input: unknown,
	shuffleSeed?: string
): Question | undefined {
	const source = asObject(parseJson(input));
	if (!source) return;
	const question = modelText(source.question);
	const details = modelText(source.details);
	if (question === undefined || (details === undefined && source.details !== undefined)) return;
	const kind = questionKinds[tool];
	const rawMode = source.multiSelect;
	const parsedMode = parseJson(rawMode);
	const modeFlag = typeof parsedMode === 'boolean' ? parsedMode : rawMode;
	const mode = typeof modeFlag === 'string' ? modeFlag.toLowerCase() : modeFlag;
	const multi = mode === true || mode === 1 || mode === '1' || mode === 'true';
	const single = mode == null || mode === false || mode === 0 || mode === '0' || mode === 'false';
	if (kind !== 'explain' && !multi && !single) return;
	let options =
		kind === 'quiz' || (kind === 'ask' && source.options != null)
			? readOptions(source.options, kind === 'ask')
			: [];
	if (!options) return;
	if (kind === 'quiz' && shuffleSeed !== undefined) {
		options = shuffleOptions(options, seededRandom(shuffleSeed));
	}
	const rawRole = modelText(parseJson(source.type));
	const role = rawRole === undefined ? undefined : stripModelValueDebris(rawRole);
	const data: Question = {
		tool,
		kind,
		question,
		details,
		options,
		mode: options.length ? (multi ? 'multi-select' : 'single-select') : 'text',
		questionType: kind === 'quiz' && (role === 'predict' || role === 'check') ? role : undefined
	};
	if (kind === 'ask') return data;
	if (kind === 'explain') {
		const committed = modelText(source.correctAnswer);
		if (committed?.trim()) return { ...data, committed };
		return;
	}
	const rawAnswer = source.correctAnswer;
	const answer = Array.isArray(rawAnswer) ? rawAnswer.map(modelText) : modelText(rawAnswer);
	const explanation = modelText(source.explanation);
	if (explanation === undefined || answer === undefined) return;
	const keys = Array.isArray(answer)
		? answer.filter((key): key is string => key !== undefined)
		: answer;
	if (Array.isArray(answer) && keys.length !== answer.length) return;
	const correctIndices = resolveCorrect(keys, options);
	if (correctIndices && (multi || correctIndices.length === 1)) {
		return { ...data, explanation, correctIndices };
	}
}

export function questionNeedsReveal(tool: QuestionTool, input: unknown, phase: string): boolean {
	if (phase !== 'teach' || (tool !== 'quiz' && tool !== 'explain')) return false;
	const role = asObject(parseJson(input))?.type;
	return typeof role !== 'string' || stripModelValueDebris(role) !== 'predict';
}
