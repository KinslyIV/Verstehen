import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { hasOpenOverlay } from '#lib/questions/keyboard.js';

/** Android's Back closes an open overlay (as Escape would), else offers itself to `handle`;
 * if that declines, it goes back or leaves the app. Returns the stop function.
 */
export function onAndroidBack(handle: () => boolean): () => void {
	if (Capacitor.getPlatform() !== 'android') return () => {};
	const listener = App.addListener('backButton', ({ canGoBack }) => {
		if (hasOpenOverlay()) pressEscape();
		else if (!handle()) leave(canGoBack);
	});
	return () => void listener.then((registered) => registered.remove());
}

function pressEscape(): void {
	const target = document.activeElement ?? document.body;
	target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

function leave(canGoBack: boolean): void {
	if (canGoBack) history.back();
	else void App.exitApp();
}
