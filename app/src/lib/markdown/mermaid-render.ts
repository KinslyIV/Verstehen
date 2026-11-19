import mermaid from 'mermaid';

let queue: Promise<unknown> = Promise.resolve();

export function renderMermaid(chart: string, dark: boolean): Promise<string> {
	const result = queue.then(async () => {
		mermaid.initialize({
			startOnLoad: false,
			securityLevel: 'strict',
			suppressErrorRendering: true,
			fontFamily: 'ui-sans-serif, system-ui, sans-serif',
			fontSize: 16,
			theme: dark ? 'dark' : 'default'
		});
		const { svg } = await mermaid.render(`verstehen-mermaid-${crypto.randomUUID()}`, chart);
		return svg;
	});
	queue = result.catch(() => undefined);
	return result;
}
