import { getContext, setContext } from 'svelte';
import type { SessionController } from '#lib/session/controller.svelte.js';

export interface PlanPanel {
	watch: (controller: SessionController) => () => void;
	open: (tab?: 'plan' | 'side-chat') => void;
}

const planPanelKey = Symbol('plan panel');
export const getPlanPanel = () => getContext<PlanPanel | undefined>(planPanelKey);
export const setPlanPanel = (panel: PlanPanel) => setContext(planPanelKey, panel);
