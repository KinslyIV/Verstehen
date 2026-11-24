import { App, type BackButtonListenerEvent } from '@capacitor/app';
import { Capacitor, type PluginListenerHandle } from '@capacitor/core';
import { hasOpenOverlay } from '#lib/questions/keyboard.js';

const handlers = new Set<() => boolean>();
let listener: Promise<PluginListenerHandle> | undefined;

/** Android's Back closes an open overlay as Escape would, else offers itself to each `handle`,
 * else goes back or leaves the app. One native listener serves all callers; returns the stop.
 */
export function onAndroidBack(handle: () => boolean = () => false): () => void {
	if (Capacitor.getPlatform() !== 'android') return () => {};
	handlers.add(handle);
	listener ??= App.addListener('backButton', pressBack);
	return () => {
		handlers.delete(handle);
		if (handlers.size > 0) return;
		void listener?.then((registered) => registered.remove());
		listener = undefined;
	};
}

function pressBack({ canGoBack }: BackButtonListenerEvent): void {
	const modal = [...document.querySelectorAll<HTMLDialogElement>('dialog:modal')].at(-1);
	if (modal) modal.close();
	else if (hasOpenOverlay()) pressEscape();
	else if (![...handlers].some((handle) => handle())) leave(canGoBack);
}

function pressEscape(): void {
	const target = document.activeElement ?? document.body;
	target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

function leave(canGoBack: boolean): void {
	if (canGoBack) history.back();
	else void App.exitApp();
}
