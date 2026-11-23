// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {}
	/** 'remote' makes a browser build talk to a paired server; set by PUBLIC_VERSTEHEN_CLIENT. */
	const __VERSTEHEN_CLIENT__: string;
	/** Comma-separated extra server hosts /pair accepts; set by PUBLIC_VERSTEHEN_EXTRA_HOSTS. */
	const __VERSTEHEN_EXTRA_HOSTS__: string;
}
export {};
