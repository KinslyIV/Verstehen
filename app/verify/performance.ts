import type { Page } from '@playwright/test';

interface FramePerf {
	frames: number[];
	longTasks: number[];
	calls: Record<string, { n: number; ms: number }>;
}

/** Init script: records animation-frame gaps, long tasks, and time inside 2D-context draw calls. */
export const instrumentFrames = () => {
	const perf: FramePerf = { frames: [], longTasks: [], calls: {} };
	const proto = CanvasRenderingContext2D.prototype as unknown as Record<string, unknown>;
	for (const name of ['fill', 'stroke', 'fillText', 'drawImage', 'getImageData', 'putImageData']) {
		const original = proto[name] as (...args: unknown[]) => unknown;
		perf.calls[name] = { n: 0, ms: 0 };
		proto[name] = function (this: unknown, ...args: unknown[]) {
			const start = performance.now();
			try {
				return original.apply(this, args);
			} finally {
				perf.calls[name].n++;
				perf.calls[name].ms += performance.now() - start;
			}
		};
	}
	let last = performance.now();
	const loop = (now: number) => {
		perf.frames.push(now - last);
		last = now;
		requestAnimationFrame(loop);
	};
	requestAnimationFrame(loop);
	new PerformanceObserver((list) => {
		for (const entry of list.getEntries()) perf.longTasks.push(entry.duration);
	}).observe({ entryTypes: ['longtask'] });
	(window as unknown as { __perf: FramePerf }).__perf = perf;
};

/** Runs `gesture` and summarizes the frames, long tasks, and draw calls it caused. */
export async function framePerformance(page: Page, gesture: () => Promise<void>) {
	await page.evaluate(() => {
		const perf = (window as unknown as { __perf: FramePerf }).__perf;
		perf.frames.length = 0;
		perf.longTasks.length = 0;
		for (const call of Object.values(perf.calls)) call.n = call.ms = 0;
	});
	await gesture();
	const perf = await page.evaluate(() => (window as unknown as { __perf: FramePerf }).__perf);
	const gaps = [...perf.frames].sort((a, b) => a - b);
	const at = (q: number) => Math.round((gaps[Math.floor(gaps.length * q)] ?? 0) * 10) / 10;
	return {
		frames: gaps.length,
		frameP50Ms: at(0.5),
		frameP95Ms: at(0.95),
		frameMaxMs: Math.round((gaps.at(-1) ?? 0) * 10) / 10,
		framesOver50Ms: gaps.filter((gap) => gap > 50).length,
		longTasks: perf.longTasks.length,
		longTaskTotalMs: Math.round(perf.longTasks.reduce((sum, ms) => sum + ms, 0)),
		drawCalls: Object.fromEntries(
			Object.entries(perf.calls)
				.filter(([, call]) => call.n > 0)
				.map(([name, call]) => [name, { n: call.n, ms: Math.round(call.ms) }])
		)
	};
}
