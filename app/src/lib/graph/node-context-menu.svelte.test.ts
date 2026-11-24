import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { hasOpenOverlay } from '#lib/questions/keyboard.js';
import { onAndroidBack } from '#lib/session/android-back.js';
import NodeContextMenu from './node-context-menu.svelte';

const backListeners = vi.hoisted(() => new Set<(event: { canGoBack: boolean }) => void>());
vi.mock('@capacitor/core', async (original) => ({
	...(await original<typeof import('@capacitor/core')>()),
	Capacitor: { getPlatform: () => 'android' }
}));
vi.mock('@capacitor/app', () => ({
	App: {
		addListener: (_: string, listener: (event: { canGoBack: boolean }) => void) => {
			backListeners.add(listener);
			return Promise.resolve({ remove: () => backListeners.delete(listener) });
		},
		exitApp: vi.fn()
	}
}));

beforeEach(() => {
	vi.spyOn(history, 'back').mockImplementation(() => {});
});

test('android_back_closes_the_graph_context_menu_instead_of_leaving_the_page', async () => {
	const onclose = vi.fn();
	const screen = await render(NodeContextMenu, { x: 10, y: 10, ondelete: vi.fn(), onclose });
	await expect.element(screen.getByTestId('node-context-menu')).toBeVisible();
	expect(hasOpenOverlay()).toBe(true);
	const stop = onAndroidBack();
	backListeners.forEach((listener) => listener({ canGoBack: true }));
	stop();
	expect(onclose).toHaveBeenCalledOnce();
	expect(history.back).not.toHaveBeenCalled();
});
