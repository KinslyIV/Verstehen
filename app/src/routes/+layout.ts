import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import { clientMode, isPaired, loadConnection } from '#lib/api/connection.js';
import type { LayoutLoad } from './$types';

export const ssr = false;

export const load: LayoutLoad = async ({ url }) => {
	if (
		clientMode() === 'remote' &&
		url.pathname !== resolve('/pair') &&
		!isPaired(await loadConnection())
	)
		redirect(307, resolve('/pair'));
};
