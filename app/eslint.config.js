import boundaries from 'eslint-plugin-boundaries';
import prettier from 'eslint-config-prettier';
import path from 'node:path';
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig, includeIgnoreFile } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';

const gitignorePath = path.resolve(import.meta.dirname, '.gitignore');

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	prettier,
	svelte.configs.prettier,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off'
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser
			}
		}
	},
	{
		files: ['src/lib/components/ui/button/button.svelte'],
		rules: { 'svelte/no-navigation-without-resolve': 'off' }
	},
	{
		files: ['src/**/*.{ts,js,svelte}'],
		plugins: { boundaries },
		settings: {
			'boundaries/root-path': import.meta.dirname,
			'boundaries/files': [{ pattern: 'src/lib/utils.ts', category: 'utils' }],
			'import/resolver': { typescript: { project: './tsconfig.json' } },
			'boundaries/elements': [
				{ type: 'api', pattern: 'src/lib/api' },
				{ type: 'ui', pattern: 'src/lib/components/ui' },
				{ type: 'lib', pattern: 'src/lib' },
				{ type: 'routes', pattern: 'src/routes' }
			]
		},
		rules: {
			'boundaries/dependencies': [
				'error',
				{
					default: 'allow',
					checkUnknownLocals: true,
					policies: [
						{
							from: { element: { type: ['ui', 'lib', 'routes'] } },
							disallow: { to: { element: { type: 'api' }, file: { path: '**/*.d.ts' } } },
							message:
								'Move generated API type imports into src/lib/api/; expose app types from the API client.'
						},
						{
							from: { element: { type: 'ui' } },
							disallow: { to: { module: { origin: 'local' } } },
							message:
								'Move app-specific code out of src/lib/components/ui/; import only UI files, #lib/utils, or npm packages.'
						},
						{
							from: { element: { type: 'ui' } },
							allow: { to: [{ element: { type: 'ui' } }, { file: { categories: 'utils' } }] }
						},
						{
							from: { element: { type: ['api', 'ui', 'lib'] } },
							disallow: { to: { element: { type: 'routes' } } },
							message: 'Move shared code into src/lib/; src/lib/ must never import src/routes/.'
						}
					]
				}
			]
		}
	},
	{
		files: ['src/**/*.{ts,js,svelte}'],
		ignores: ['src/lib/api/**'],
		rules: {
			'no-restricted-imports': [
				'error',
				{
					paths: [
						{
							name: '@tauri-apps/api/core',
							importNames: ['invoke'],
							message: 'Move connection commands into src/lib/api/.'
						}
					]
				}
			],
			'no-restricted-globals': [
				'error',
				{
					name: 'fetch',
					message: 'Move HTTP requests into src/lib/api/.'
				}
			],
			'no-restricted-syntax': [
				'error',
				{
					selector:
						"MemberExpression[property.name='fetch'], MemberExpression[computed=true][property.value='fetch']",
					message: 'Move HTTP requests into src/lib/api/.'
				}
			]
		}
	}
);
