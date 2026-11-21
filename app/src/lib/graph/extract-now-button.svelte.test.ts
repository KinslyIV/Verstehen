import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import ExtractNowButton from './extract-now-button.svelte';
vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	extractCoverage: vi.fn()
}));
const props = { sessionId: 's', busy: false, complete: false, testid: 'extract' };
beforeEach(() => vi.clearAllMocks());
test('refused_start_shows_the_servers_reason_near_the_button', async () => {
	vi.mocked(api.extractCoverage).mockRejectedValue(
		new api.ApiError(503, 'model_unavailable', 'unavailable', 'Sign in again.')
	);
	await render(ExtractNowButton, props);
	await page.getByRole('button', { name: 'Extract now', exact: true }).click();
	await expect.element(page.getByRole('alert')).toHaveTextContent('Sign in again.');
	await expect.element(page.getByRole('button', { name: 'Try again' })).toBeVisible();
});
test('a_failure_after_launch_reported_in_coverage_shows_its_reason', async () => {
	await render(ExtractNowButton, { ...props, failure: 'ChatGPT authorization expired.' });
	await expect.element(page.getByRole('alert')).toHaveTextContent('ChatGPT authorization expired.');
});
test('a_refusal_is_retired_when_coverage_shows_a_newer_run_or_completion', async () => {
	vi.mocked(api.extractCoverage).mockRejectedValue(
		new api.ApiError(503, 'model_unavailable', 'unavailable', 'Sign in again.')
	);
	const screen = await render(ExtractNowButton, props);
	await page.getByRole('button', { name: 'Extract now', exact: true }).click();
	await expect.element(page.getByRole('alert')).toBeVisible();
	await screen.rerender({ ...props, busy: true });
	await screen.rerender({ ...props, busy: false });
	await expect.element(page.getByRole('alert')).not.toBeInTheDocument();
	await expect.element(page.getByRole('button', { name: 'Extract now' })).toBeVisible();
});
test('a_new_coverage_failure_replaces_an_older_refusal', async () => {
	vi.mocked(api.extractCoverage).mockRejectedValue(
		new api.ApiError(503, 'model_unavailable', 'unavailable', 'Sign in again.')
	);
	const screen = await render(ExtractNowButton, props);
	await page.getByRole('button', { name: 'Extract now', exact: true }).click();
	await screen.rerender({ ...props, failure: 'Newer failure.' });
	await expect.element(page.getByRole('alert')).toHaveTextContent('Newer failure.');
});
