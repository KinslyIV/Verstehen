import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './verify',
	testMatch: '**/*.flow.ts',
	outputDir: './verify-output',
	retries: process.env.CI ? 1 : 0,
	preserveOutput: 'always',
	use: { ...devices['Desktop Chrome'], channel: 'chromium', headless: true, trace: 'on' },
	reporter: 'list'
});
