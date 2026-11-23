import { MediaQuery } from 'svelte/reactivity';
import { DRAWER_BELOW, IsMobile, PHONE_BELOW } from '#lib/components/ui/hooks/is-mobile.svelte.js';

export type LayoutTier = 'phone' | 'tablet' | 'desktop';

/** The width tier and the input type the layout adapts to; one instance serves the whole app. */
class Layout {
	private belowPhone = new IsMobile(PHONE_BELOW);
	private belowDesktop = new IsMobile(DRAWER_BELOW);
	private touch = new MediaQuery('pointer: coarse');
	tier = $derived<LayoutTier>(
		this.belowPhone.current ? 'phone' : this.belowDesktop.current ? 'tablet' : 'desktop'
	);
	/** The primary input is a finger: targets are touch-sized and `/graph` uses gestures. */
	get coarse(): boolean {
		return this.touch.current;
	}
}

export const layout = new Layout();
