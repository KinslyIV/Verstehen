import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
	testDir: './verify',
	testMatch: '**/*.flow.ts',
	outputDir: './verify-output',
	preserveOutput: 'always',
	use: { ...devices['Desktop Chrome'], headless: true, trace: 'on' },
	reporter: 'list'
});
