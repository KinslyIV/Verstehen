import { beforeEach, expect, test, vi } from 'vitest';
import { render } from 'vitest-browser-svelte';
import { page } from 'vitest/browser';
import * as api from '#lib/api/client.js';
import CoverageRing from './coverage-ring.svelte';

vi.mock('#lib/api/client.js', async (original) => ({
	...(await original<typeof api>()),
	getSettings: vi.fn()
}));

const coverage: api.SessionCoverage = {
	total_messages: 4,
	covered_count: 2,
	uncovered_count: 2,
	uncovered_tokens: 1000,
	covered_tokens: 1000,
	last_folded_at: null,
	running: false,
	failure_reason: null
};

beforeEach(() => {
	vi.mocked(api.getSettings)
		.mockReset()
		.mockResolvedValue({
			graph: { enabled: true, rendering: true, extraction_chunk_tokens: 4000 }
		} as unknown as api.SettingsStatus);
});

test('coverage_ring_updates_and_hides_when_settings_change_event_fires', async () => {
	const screen = await render(CoverageRing, { sessionId: 's-1', coverage });
	const ring = page.getByTestId('coverage-ring');
	await expect.element(ring).toHaveAttribute('data-fill', '0.25');

	window.dispatchEvent(
		new CustomEvent('verstehen:settings-changed', {
			detail: { graph: { enabled: true, rendering: true, extraction_chunk_tokens: 2000 } }
		})
	);
	await expect.element(ring).toHaveAttribute('data-fill', '0.50');

	window.dispatchEvent(
		new CustomEvent('verstehen:settings-changed', {
			detail: { graph: { enabled: false, rendering: true, extraction_chunk_tokens: 2000 } }
		})
	);
	await expect.element(ring).not.toBeInTheDocument();

	await screen.unmount();
	window.dispatchEvent(
		new CustomEvent('verstehen:settings-changed', {
			detail: { graph: { enabled: true, rendering: true, extraction_chunk_tokens: 4000 } }
		})
	);
	await expect.element(ring).not.toBeInTheDocument();
});
