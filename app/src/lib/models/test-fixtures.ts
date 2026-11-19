import type { ModelCatalog, ModelPick, Settings } from '#lib/api/client.js';
export const mainPick: ModelPick = { account: 'fake', model: 'fake', thinking_level: 'medium' };
export const titlePick: ModelPick = { account: 'fake', model: 'fake-title', thinking_level: 'low' };
export const testSettings: Settings = {
	models: { strong: mainPick, cheap: titlePick, vision: mainPick },
	background: { chatgpt: true, claude_code: true }
};
export const testCatalog: ModelCatalog = {
	slots: testSettings.models!,
	accounts: [
		{
			account: { id: 'fake', kind: 'fake', label: 'Scripted model', state: 'ready' },
			models: [
				{
					id: 'fake',
					name: 'Scripted teacher',
					thinking_levels: ['low', 'medium', 'high'],
					default_thinking_level: 'medium',
					priced: false,
					accepts_images: true
				},
				{
					id: 'fake-title',
					name: 'Scripted title',
					thinking_levels: ['low'],
					default_thinking_level: 'low',
					priced: false,
					accepts_images: false
				}
			]
		}
	]
};
