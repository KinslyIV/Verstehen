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
		expect: { requireAssertions: true },
		attachmentsDir: '.svelte-kit/vitest-artifacts',
		projects: [
			{
				extends: './vite.config.ts',
				optimizeDeps: {
					include: [
						'@lucide/svelte',
						'@lucide/svelte/icons/panel-left',
						'@lucide/svelte/icons/x',
						'bits-ui',
						'paneforge',
						'tailwind-variants',
						'shiki',
						'mermaid',
						'mode-watcher',
						'@streamdown/cjk',
						'unified',
						'remark-parse',
						'remark-gfm',
						'remark-math',
						'remark-breaks',
						'remark-rehype',
						'rehype-raw',
						'rehype-sanitize',
						'rehype-harden',
						'rehype-katex',
						'remend',
						'mdast-util-from-markdown',
						'mdast-util-math',
						'micromark-extension-math',
						'hast-util-to-html',
						'hast-util-to-text',
						'unist-util-visit',
						'cn'
					]
				},
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
