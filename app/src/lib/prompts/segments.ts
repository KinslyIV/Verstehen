import type { PromptSegment, PromptSegments } from '#lib/api/client.js';

const agents = [
	{ id: 'teacher', label: 'Teacher' },
	{ id: 'prober', label: 'Prober' },
	{ id: 'practice', label: 'Practice' }
] as const;

export type PromptSection = {
	id: string;
	label: string;
	segments: (PromptSegment & { usage?: string })[];
};

/** "teacher/20-teaching.md" becomes "Teaching". */
export function segmentName(path: string): string {
	const file = (path.split('/').at(-1) ?? '').replace(/\.[^.]+$/, '');
	const name = file.replace(/^[\d-]+/, '').replace(/-+/g, ' ');
	return name.charAt(0).toUpperCase() + name.slice(1);
}

function joinNames(names: string[]): string {
	return names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names.at(-1)}` : names[0];
}

/** Teacher, Prober, Practice, then each shared fragment once with the agents that use it. */
export function sectionedSegments(view: PromptSegments): PromptSection[] {
	const shared = new Map<string, PromptSegment>();
	for (const { id } of agents)
		for (const segment of view[id])
			if (segment.shared && !shared.has(segment.path)) shared.set(segment.path, segment);
	return [
		...agents.map(({ id, label }) => ({
			id,
			label,
			segments: view[id].filter((segment) => !segment.shared)
		})),
		{
			id: 'shared',
			label: 'Shared',
			segments: [...shared.values()].map((segment) => ({
				...segment,
				usage: `Used by ${joinNames(
					agents
						.filter(({ id }) => view[id].some((other) => other.path === segment.path))
						.map(({ label }) => label)
				)}`
			}))
		}
	];
}
