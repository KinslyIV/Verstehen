import { expect, test } from 'vitest';
import {
	demoSrcDoc,
	isDemoEscape,
	embedLearnerImage,
	formatElapsed,
	INITIAL_DEMO_BRIDGE_STATE,
	jobCostLabel,
	reduceDemoBridgeState,
	svgDataUri,
	totalCostLabel
} from './jobs.js';
import type { JobRecord } from '#lib/api/client.js';

test('unpriced_job_cost_uses_the_subscription_label_and_total_deduplicates', () => {
	const chatgpt = { usage: { account_kind: 'chatgpt' } } as JobRecord;
	const claude = { usage: { account_kind: 'claude_code' } } as JobRecord;
	expect(jobCostLabel(chatgpt)).toBe('ChatGPT');
	expect(jobCostLabel(claude)).toBe('—');
	expect(totalCostLabel([chatgpt, chatgpt, claude])).toBe('ChatGPT');
	expect(totalCostLabel([claude])).toBe('—');
	expect(formatElapsed(4320)).toBe('1h 12m');
});

test('demo_bridge_bounds_height_and_reports_errors', () => {
	const state = INITIAL_DEMO_BRIDGE_STATE;
	expect(reduceDemoBridgeState(state, { type: 'demo-resize', height: NaN })).toBe(state);
	expect(reduceDemoBridgeState(state, { type: 'demo-resize', height: 5000 }).height).toBe(2400);
	expect(reduceDemoBridgeState(state, { type: 'demo-error', message: 'Oops' }).error).toBe('Oops');
	expect(demoSrcDoc('<body>demo</body>')).toContain('postMessage');
	expect(demoSrcDoc('<body>demo</body>')).toMatch(/<script>[\s\S]*<\/script><\/body>$/);
	expect(demoSrcDoc('<body>demo</body>')).toContain('"demo-escape"');
	expect(isDemoEscape({ type: 'demo-escape' })).toBe(true);
	expect(isDemoEscape({ type: 'demo-resize' })).toBe(false);
	expect(isDemoEscape('demo-escape')).toBe(false);
});

test('annotation_embeds_only_the_image_placeholder_and_svg_is_an_image', () => {
	const svg = '<svg width="10"><image href="learner-image"/><text>learner-image</text></svg>';
	const embedded = embedLearnerImage(svg, 'data:image/png;base64,AAA');
	expect(embedded).toContain('href="data:image/png;base64,AAA"');
	expect(embedded).toContain('<text>learner-image</text>');
	expect(decodeURIComponent(svgDataUri(embedded))).toContain('xmlns="http://www.w3.org/2000/svg"');
});
