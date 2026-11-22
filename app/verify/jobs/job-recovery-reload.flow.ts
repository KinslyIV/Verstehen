import { writeFile } from 'node:fs/promises';
import { test, expect } from '../fixtures';
import { dispatchEntries, seedJob, seedTeaching } from '../jobs';

test.use({ script: 'verify/scripts/job-recovery-reload.json' });

const input = { question: 'What is the slope of a secant line?' };
const brief = {
	brief:
		'## Summary\nA secant slope is the average rate of change.\n\n[Khan Academy](https://www.khanacademy.org/math/ap-calculus-ab)',
	sources: [{ title: 'Khan Academy', url: 'https://www.khanacademy.org/math/ap-calculus-ab' }]
};

test('job-recovery-reload', async ({
	page,
	request,
	appendEntries,
	dataDirectory,
	restartSidecar
}) => {
	const resting = [
		{
			kind: 'assistant' as const,
			stop_reason: 'stop' as const,
			parts: [{ type: 'text' as const, text: 'Looking into it.' }]
		}
	];
	const finished = await seedTeaching(request, appendEntries, 'Finished before the restart');
	await appendEntries(finished, [...dispatchEntries('research', 'research-1', input), ...resting]);
	await seedJob(
		dataDirectory,
		{ session_id: finished, kind: 'research', tool_call_id: 'research-1', input, result: brief },
		writeFile
	);
	const interrupted = await seedTeaching(request, appendEntries, 'Interrupted by the restart');
	await appendEntries(interrupted, [
		...dispatchEntries('research', 'research-2', input),
		...resting
	]);
	await seedJob(
		dataDirectory,
		{ session_id: interrupted, kind: 'research', tool_call_id: 'research-2', input },
		writeFile
	);

	await restartSidecar();
	await page.goto(`/session/${finished}`);
	await expect(page.getByTestId('research-complete-badge')).toBeVisible({ timeout: 20_000 });
	await expect(page.getByText('The earlier research arrived after the restart')).toBeVisible();
	await page.goto(`/session/${interrupted}`);
	await expect(page.getByTestId('research-complete-badge')).toBeVisible({ timeout: 30_000 });
	await expect(page.getByText('The re-run research arrived')).toBeVisible();
	await page.reload();
	await expect(page.getByTestId('research-complete-badge')).toBeVisible();
	await expect(page.getByTestId('dispatch-settled')).toHaveText(/Research agent\s*finished/);
});
