import type { APIRequestContext, Page } from '@playwright/test';
import { expect } from './fixtures';
import type { GraphSeed } from './fixtures';
import { createSession } from './compaction';

const CAMERA_KEY = 'verstehen-graph-camera';

/** Four clusters: three sessions with a multi-premise chain each, and one imported notes file. */
export async function demoGraph(request: APIRequestContext): Promise<GraphSeed> {
	const [rates, derivatives, integrals] = await Promise.all([
		createSession(request, 'Slope and rates'),
		createSession(request, 'Derivatives'),
		createSession(request, 'Integrals')
	]);
	const notes = 'src_limits';
	const node = (id: string, session: string, name: string, statement: string) => ({
		id: `n_${id}`,
		name,
		statement,
		session
	});
	const chain = (id: string, premises: string[], conclusion: string, session: string) => ({
		id: `arg_${id}`,
		premises: premises.map((p) => `n_${p}`),
		conclusion: `n_${conclusion}`,
		session
	});
	return {
		nodes: [
			node('a1', rates, 'Slope', 'The slope of a line is its rise divided by its run.'),
			node(
				'a2',
				rates,
				'Average rate',
				'The average rate of change is the change in output over the change in input.'
			),
			node(
				'a3',
				rates,
				'Secant line',
				'A secant line joins two points of a curve; its slope is the average rate between them.'
			),
			node('a4', rates, 'Straight lines', 'A straight line has the same slope everywhere.'),
			node(
				'a5',
				rates,
				'Rate units',
				'A rate of change is measured in output units per input unit.'
			),
			node(
				'b1',
				derivatives,
				'Instantaneous rate',
				'The instantaneous rate is the limit of average rates as the interval shrinks to a point.'
			),
			node(
				'b2',
				derivatives,
				'Tangent line',
				'The tangent line touches a curve at one point and has the curve’s slope there.'
			),
			node(
				'b3',
				derivatives,
				'Derivative',
				'The derivative at a point is the instantaneous rate of change at that point.'
			),
			node('b4', derivatives, 'Power rule', 'The derivative of x^n is n·x^(n−1).'),
			node('b5', derivatives, 'Sum rule', 'The derivative of a sum is the sum of the derivatives.'),
			node(
				'c1',
				integrals,
				'Area under a curve',
				'The area under a curve can be approximated by thin rectangles.'
			),
			node(
				'c2',
				integrals,
				'Riemann sum',
				'A Riemann sum adds the areas of rectangles under a curve.'
			),
			node(
				'c3',
				integrals,
				'Definite integral',
				'The definite integral is the limit of Riemann sums as the rectangles thin out.'
			),
			node(
				'c4',
				integrals,
				'Fundamental theorem',
				'Differentiation and integration undo each other.'
			),
			node(
				'd1',
				notes,
				'Limit',
				'A limit is the value a function approaches as its input approaches a point.'
			),
			node(
				'd2',
				notes,
				'One-sided limit',
				'A one-sided limit approaches a point from only the left or only the right.'
			),
			node(
				'd3',
				notes,
				'Continuity',
				'A function is continuous at a point when its limit there equals its value.'
			)
		],
		chains: [
			chain('ch1', ['a2'], 'a3', rates),
			chain('ch2', ['a2', 'a3'], 'b1', derivatives),
			chain('ch3', ['b1'], 'b3', derivatives),
			chain('ch4', ['b1', 'a3'], 'b2', derivatives),
			chain('ch5', ['b3'], 'b4', derivatives),
			chain('ch6', ['c1', 'c2'], 'c3', integrals),
			chain('ch7', ['c3', 'b3'], 'c4', integrals),
			chain('ch8', ['d1', 'd2'], 'd3', notes),
			chain('ch9', ['d1'], 'b1', derivatives)
		],
		sources: [{ id: notes, file_path: 'calculus/limits.md' }]
	};
}

export interface Camera {
	k: number;
	x: number;
	y: number;
}

/** Wait until the page has settled and saved the layout (every node has a position). */
export async function waitForLayout(request: APIRequestContext, count: number) {
	await expect
		.poll(
			async () => Object.keys((await (await request.get('/api/graph')).json()).positions).length
		)
		.toBeGreaterThanOrEqual(count);
}

export async function camera(page: Page): Promise<Camera> {
	await expect
		.poll(() => page.evaluate((key) => localStorage.getItem(key), CAMERA_KEY))
		.not.toBeNull();
	await page.waitForTimeout(400);
	return JSON.parse((await page.evaluate((key) => localStorage.getItem(key), CAMERA_KEY))!);
}

/** The screen point of a node: its saved world position under the saved camera. */
export async function nodePoint(page: Page, request: APIRequestContext, id: string) {
	const position = (await (await request.get('/api/graph')).json()).positions[id];
	const view = await camera(page);
	const box = (await page.getByTestId('graph-canvas').boundingBox())!;
	return { x: box.x + position.x * view.k + view.x, y: box.y + position.y * view.k + view.y };
}

/** Change graph settings through the API (the Settings screen for them comes later). */
export async function setGraphSettings(
	request: APIRequestContext,
	patch: { enabled?: boolean; rendering?: boolean; extraction_chunk_tokens?: number }
) {
	const settings = await (await request.get('/api/settings')).json();
	delete settings.file_access_error;
	const saved = await request.put('/api/settings', {
		data: { ...settings, graph: { ...settings.graph, ...patch } }
	});
	expect(saved.ok()).toBe(true);
}

/** Run extractors and auditors on the scripted fake model (the cheap slot normally titles). */
export async function scriptExtractors(request: APIRequestContext) {
	const settings = await (await request.get('/api/settings')).json();
	delete settings.file_access_error;
	const saved = await request.put('/api/settings', {
		data: { ...settings, models: { ...settings.models, cheap: { account: 'fake', model: 'fake' } } }
	});
	expect(saved.ok()).toBe(true);
}
