import { afterEach, expect, test } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import { sidecar } from '#lib/api/connection.svelte.js';
import StartupStatus from '#lib/components/startup-status.svelte';

afterEach(() => {
	sidecar.status = 'ready';
	sidecar.failure = null;
});

test('a_pending_sidecar_shows_a_quiet_status_and_leaves_the_shell_usable', async () => {
	sidecar.status = 'pending';
	await render(StartupStatus);
	await expect.element(page.getByRole('status')).toHaveTextContent('Starting Verstehen…');
	await expect.element(page.getByRole('alert')).not.toBeInTheDocument();
});

test('a_failed_start_names_the_reason_and_the_log', async () => {
	sidecar.status = 'failed';
	sidecar.failure =
		"The sidecar didn't start. See /home/learner/.local/share/verstehen/logs/verstehen.log";
	await render(StartupStatus);
	await expect
		.element(page.getByRole('heading', { name: /Verstehen couldn.t start/ }))
		.toBeVisible();
	await expect.element(page.getByText(/See .*verstehen\.log/)).toBeVisible();
});

test('a_ready_sidecar_shows_nothing', async () => {
	await render(StartupStatus);
	await expect.element(page.getByRole('status')).not.toBeInTheDocument();
	await expect.element(page.getByRole('alert')).not.toBeInTheDocument();
});
