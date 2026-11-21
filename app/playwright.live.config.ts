import { defineConfig } from '@playwright/test';
import config from './playwright.config';

export default defineConfig({
	...config,
	testDir: './verify-live',
	outputDir: './verify-live-output',
	retries: 0,
	timeout: 300_000,
	expect: { timeout: 120_000 }
});
