import type { Page } from '@playwright/test';

export interface Point {
	x: number;
	y: number;
}

type TouchType = 'touchStart' | 'touchMove' | 'touchEnd';

async function gesture(page: Page, steps: { type: TouchType; points: Point[]; wait?: number }[]) {
	const session = await page.context().newCDPSession(page);
	try {
		for (const { type, points, wait } of steps) {
			await session.send('Input.dispatchTouchEvent', {
				type,
				touchPoints: points.map(({ x, y }, id) => ({ x, y, id }))
			});
			if (wait) await page.waitForTimeout(wait);
		}
	} finally {
		await session.detach();
	}
}

/** Presses one finger at `point` for `ms` without moving, then lifts it. */
export const holdTouch = (page: Page, point: Point, ms: number) =>
	gesture(page, [
		{ type: 'touchStart', points: [point], wait: ms },
		{ type: 'touchEnd', points: [] }
	]);

/** Drags one finger from `from` to `to` in ten steps, then lifts it. */
export const dragTouch = (page: Page, from: Point, to: Point) =>
	gesture(page, [
		{ type: 'touchStart', points: [from] },
		...Array.from({ length: 10 }, (_, step) => ({
			type: 'touchMove' as const,
			points: [
				{
					x: from.x + ((to.x - from.x) * (step + 1)) / 10,
					y: from.y + ((to.y - from.y) * (step + 1)) / 10
				}
			],
			wait: 16
		})),
		{ type: 'touchEnd', points: [] }
	]);
