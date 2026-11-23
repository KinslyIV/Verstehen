import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { onAndroidBack } from './android-back.js';

const { added, removed, exitApp } = vi.hoisted(() => ({
	added: [] as ((event: { canGoBack: boolean }) => void)[],
	removed: vi.fn(),
	exitApp: vi.fn()
}));
vi.mock('@capacitor/core', async (original) => ({
	...(await original<typeof import('@capacitor/core')>()),
	Capacitor: { getPlatform: () => 'android' }
}));
vi.mock('@capacitor/app', () => ({
	App: {
		addListener: (_: string, listener: (event: { canGoBack: boolean }) => void) => {
			added.push(listener);
			return Promise.resolve({ remove: removed });
		},
		exitApp
	}
}));

const stops: (() => void)[] = [];
const register = (handle?: () => boolean) => stops.push(onAndroidBack(handle));
const pressBack = (canGoBack = true) => added.at(-1)!({ canGoBack });

beforeEach(() => {
	added.length = 0;
	removed.mockReset();
	exitApp.mockReset();
	vi.spyOn(history, 'back').mockImplementation(() => {});
});
afterEach(() => stops.splice(0).forEach((stop) => stop()));

test('callers_share_one_native_listener_removed_with_the_last_of_them', async () => {
	register();
	register(() => false);
	expect(added).toHaveLength(1);
	stops[0]!();
	await Promise.resolve();
	expect(removed).not.toHaveBeenCalled();
	stops[1]!();
	await vi.waitFor(() => expect(removed).toHaveBeenCalledOnce());
});

test('back_closes_an_open_overlay_as_escape_before_any_handler_or_navigation', () => {
	const handle = vi.fn(() => true);
	register();
	register(handle);
	const overlay = document.createElement('div');
	overlay.dataset.slot = 'dialog-content';
	overlay.dataset.state = 'open';
	document.body.append(overlay);
	const escapes = vi.fn((event: KeyboardEvent) => event.key);
	document.addEventListener('keydown', escapes);
	pressBack();
	document.removeEventListener('keydown', escapes);
	overlay.remove();
	expect(escapes).toHaveReturnedWith('Escape');
	expect(handle).not.toHaveBeenCalled();
	expect(history.back).not.toHaveBeenCalled();
});

test('back_closes_a_native_modal_dialog_directly', async () => {
	const handle = vi.fn(() => true);
	register();
	register(handle);
	const dialog = document.createElement('dialog');
	const closed = vi.fn();
	dialog.addEventListener('close', closed);
	document.body.append(dialog);
	dialog.showModal();
	expect(dialog.open).toBe(true);
	pressBack();
	expect(dialog.open).toBe(false);
	await vi.waitFor(() => expect(closed).toHaveBeenCalledOnce());
	expect(handle).not.toHaveBeenCalled();
	expect(history.back).not.toHaveBeenCalled();
	dialog.remove();
});

test('back_goes_to_the_first_handler_that_takes_it_else_navigates', () => {
	const taker = vi.fn(() => true);
	register();
	register(taker);
	pressBack();
	expect(taker).toHaveBeenCalledOnce();
	expect(history.back).not.toHaveBeenCalled();

	taker.mockReturnValue(false);
	pressBack();
	expect(history.back).toHaveBeenCalledOnce();
});

test('back_leaves_the_app_when_there_is_no_history', () => {
	register();
	pressBack(false);
	expect(exitApp).toHaveBeenCalledOnce();
	expect(history.back).not.toHaveBeenCalled();
});
