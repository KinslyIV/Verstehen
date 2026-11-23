import { MediaQuery } from 'svelte/reactivity';

/** Below this width the layout is the phone's; the sidebar and the right panel become screens. */
export const PHONE_BELOW = 768;
/** Below this width the sidebar is a drawer; from it the desktop layout shows the sidebar. */
export const DRAWER_BELOW = 1280;

export class IsMobile extends MediaQuery {
	constructor(breakpoint: number = DRAWER_BELOW) {
		super(`max-width: ${breakpoint - 1}px`);
	}
}
