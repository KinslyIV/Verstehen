import { execFile } from 'node:child_process';
import { resolve } from 'node:path';
import { promisify } from 'node:util';
import { chromium, type APIRequestContext, type Page } from '@playwright/test';
import type { Entry } from '../src/lib/api/client';
import { expect } from './fixtures';
import { createSession } from './compaction';

const runFile = promisify(execFile);

const assessment: Entry[] = [
	{
		kind: 'assistant',
		stop_reason: 'stop',
		parts: [
			{
				type: 'tool_call',
				tool_call_id: 'assessment',
				tool_name: 'probe_done',
				arguments: {
					assessment: { strands: [{ strand: 'Slope', assessment: 'Understands two points.' }] }
				}
			}
		]
	},
	{
		kind: 'tool_result',
		is_error: false,
		tool_call_id: 'assessment',
		tool_name: 'probe_done',
		text: 'Assessment recorded.',
		details: { ok: true }
	},
	{ kind: 'marker', marker_type: 'probe-handoff', content: '', display: true }
];

/** A session already past the probe, so the next message is taught. */
export async function seedTeaching(
	request: APIRequestContext,
	appendEntries: (sessionId: string, entries: Entry[]) => Promise<void>,
	title: string
): Promise<string> {
	const id = await createSession(request, title);
	await appendEntries(id, assessment);
	return id;
}

export async function useDemoBrowser(request: APIRequestContext) {
	const settings = await (await request.get('/api/settings')).json();
	delete settings.file_access_error;
	const saved = await request.put('/api/settings', {
		data: { ...settings, demo_browser: chromium.executablePath() }
	});
	expect(saved.ok()).toBe(true);
}

export async function openJobsTab(page: Page) {
	await page.getByRole('button', { name: 'Toggle right panel' }).click();
	await page.getByRole('tab', { name: 'Jobs' }).click();
}

const writeJob = `
import asyncio
import json
import sys
from pathlib import Path
from verstehen.store.database import open_database
from verstehen.store.jobs import JobDelivery, JobPatch, JobsStore

async def main():
    spec = json.loads(Path(sys.argv[2]).read_text())
    async with open_database(Path(sys.argv[1]) / "verstehen.db") as database:
        store = JobsStore(database)
        job = await store.create(spec["session_id"], spec["kind"], spec["tool_call_id"], spec["input"])
        if "result" in spec:
            await store.update(job.id, JobPatch(
                status="done", activity="done", result=spec["result"],
                delivery=JobDelivery(kind="result", status="pending")))

asyncio.run(main())
`;

/** Save a job as an interrupted process left it: finished with its result undelivered, or still running. */
export async function seedJob(
	dataDirectory: string,
	spec: {
		session_id: string;
		kind: string;
		tool_call_id: string;
		input: object;
		result?: object;
	},
	writeFile: (path: string, data: string) => Promise<void>
) {
	const file = resolve(dataDirectory, 'job.json');
	await writeFile(file, JSON.stringify(spec));
	await runFile(resolve('../backend/.venv/bin/python'), ['-c', writeJob, dataDirectory, file], {
		env: { ...process.env, VERSTEHEN_DATA_DIR: dataDirectory }
	});
}

/** The dispatching call and its acknowledgement, as a teacher turn leaves them. */
export function dispatchEntries(toolName: string, toolCallId: string, input: object): Entry[] {
	return [
		{ kind: 'user', text: 'Explain secant slopes' },
		{
			kind: 'assistant',
			stop_reason: 'stop',
			parts: [
				{ type: 'tool_call', tool_call_id: toolCallId, tool_name: toolName, arguments: input }
			]
		},
		{
			kind: 'tool_result',
			is_error: false,
			tool_call_id: toolCallId,
			tool_name: toolName,
			text: 'Dispatched. This call is fire-and-forget.',
			details: null
		}
	];
}
