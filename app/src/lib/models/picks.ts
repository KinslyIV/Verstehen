import type { CatalogModel, ModelCatalog, ModelPick, ModelSlots } from '#lib/api/client.js';

export type ModelTab = 'strong' | 'cheap' | 'vision';
export const modelTabs = [
	{ key: 'strong', label: 'Main' },
	{ key: 'cheap', label: 'Cheap' },
	{ key: 'vision', label: 'Vision' }
] as const;
export function modelFor(catalog: ModelCatalog | undefined, pick: ModelPick | null | undefined) {
	return catalog?.accounts
		.find((item) => item.account.id === pick?.account)
		?.models.find((model) => model.id === pick?.model);
}
export function pickModel(
	account: string,
	model: CatalogModel,
	previous?: ModelPick | null
): ModelPick {
	const level = previous?.thinking_level;
	return {
		account,
		model: model.id,
		thinking_level:
			level && model.thinking_levels?.includes(level)
				? level
				: (model.default_thinking_level ?? null)
	};
}
export function cycleLevel(pick: ModelPick, model: CatalogModel): ModelPick {
	const levels = model.thinking_levels ?? [];
	if (!levels.length) return pick;
	const index = pick.thinking_level ? levels.indexOf(pick.thinking_level) : -1;
	return { ...pick, thinking_level: levels[(index + 1) % levels.length] };
}
export function modelLabel(catalog: ModelCatalog | undefined, pick?: ModelPick | null): string {
	if (!pick) return 'Choose model';
	const name = modelFor(catalog, pick)?.name ?? pick.model;
	const level = pick.thinking_level;
	return level ? `${name} · ${level[0].toUpperCase()}${level.slice(1)}` : name;
}
export function setupStage(catalog: ModelCatalog | undefined): 'loading' | 'connect' | 'models' {
	if (!catalog) return 'loading';
	return catalog.accounts.some((item) => item.models.length > 0) ? 'models' : 'connect';
}
export function slotsComplete(slots: ModelSlots): boolean {
	return modelTabs.every((tab) => !!slots[tab.key]);
}
