import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';

/** Gives Android's Back to `handle` first; if it declines, Back goes back or leaves the app.
 * Returns the stop function.
 */
export function onAndroidBack(handle: () => boolean): () => void {
	if (Capacitor.getPlatform() !== 'android') return () => {};
	const listener = App.addListener('backButton', ({ canGoBack }) => {
		if (handle()) return;
		if (canGoBack) history.back();
		else void App.exitApp();
	});
	return () => void listener.then((registered) => registered.remove());
}
