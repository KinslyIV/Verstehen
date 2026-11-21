import os from 'node:os';
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './verify',
	testMatch: '**/*.flow.ts',
	outputDir: './verify-output',
	workers: process.env.CI ? undefined : os.availableParallelism() <= 4 ? 1 : undefined,
	retries: process.env.CI ? 1 : 0,
	preserveOutput: 'always',
	use: { ...devices['Desktop Chrome'], channel: 'chromium', headless: true, trace: 'on' },
	reporter: 'list'
});
