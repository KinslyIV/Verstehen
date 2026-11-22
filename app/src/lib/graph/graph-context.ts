import type { Entry, GraphContext } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';

/** The picked propositions and chains a graph-context marker carries, if its details are well formed. */
export function graphContextOf(entry: Entry): GraphContext | undefined {
	if (entry.kind !== 'marker' || entry.marker_type !== 'graph-context') return;
	const details = asObject(entry.details);
	if (!Array.isArray(details?.propositions)) return;
	const propositions = details.propositions.flatMap((item) => {
		const pick = asObject(item);
		return typeof pick?.id === 'string' &&
			typeof pick.name === 'string' &&
			typeof pick.statement === 'string'
			? [{ id: pick.id, name: pick.name, statement: pick.statement }]
			: [];
	});
	const chains = Array.isArray(details.chains)
		? details.chains.filter((chain): chain is string => typeof chain === 'string')
		: [];
	return { propositions, chains };
}
