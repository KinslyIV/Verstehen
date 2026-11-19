import { playwright } from '@vitest/browser-playwright';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			adapter: adapter({ fallback: 'index.html' })
		})
	],
	server: {
		proxy: { '/api': `http://127.0.0.1:${process.env.VERSTEHEN_PORT ?? '8765'}` }
	},
	preview: {
		proxy: { '/api': `http://127.0.0.1:${process.env.VERSTEHEN_PORT ?? '8765'}` }
	},
	test: {
		passWithNoTests: true,
		expect: { requireAssertions: true },
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'client',
					include: ['src/**/*.svelte.{test,spec}.ts'],
					setupFiles: ['vitest-browser-svelte'],
					browser: {
						enabled: true,
						provider: playwright({ launchOptions: { channel: 'chromium' } }),
						instances: [{ browser: 'chromium' }],
						headless: true,
						screenshotDirectory: '.svelte-kit/vitest',
						commands: {
							async setColorScheme({ page }, colorScheme: 'dark' | 'light') {
								await page.emulateMedia({ colorScheme });
							}
						},
						viewport: { width: 1280, height: 800 }
					}
				}
			},
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
