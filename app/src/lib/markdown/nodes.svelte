<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import SafeLink from './safe-link.svelte';
	import Nodes from './nodes.svelte';
	import type { RootContent, Element } from 'hast';

	import { toHtml } from 'hast-util-to-html';
	import CodeBlock from './code-block.svelte';
	import MermaidBlock from './mermaid-block.svelte';
	import { texSource, tableMarkdown, alertContent } from './block-text';
	import CopyButton from './copy-button.svelte';
	let { nodes }: { nodes: RootContent[] } = $props();

	function classes(node: Element): string[] {
		return (node.properties.className as string[] | undefined) ?? [];
	}
	function attributes(node: Element) {
		const { className, ...rest } = node.properties;
		return {
			...rest,
			class: Array.isArray(className) ? className.join(' ') : className
		} as HTMLAttributes<HTMLElement>;
	}
</script>

{#each nodes as node, i (i)}
	{#if node.type === 'text'}{node.value}
	{:else if node.type === 'element'}
		{#if node.tagName === 'pre' && node.children[0]?.type === 'element' && node.children[0].tagName === 'code'}
			{@const code = node.children[0]}
			{@const language =
				classes(code)
					.find((c) => c.startsWith('language-'))
					?.slice(9) ?? ''}
			{@const source = code.children
				.map((n) => (n.type === 'text' ? n.value : ''))
				.join('')
				.replace(/\n$/, '')}
			{#if language === 'mermaid'}<MermaidBlock {source} />{:else}<CodeBlock
					{source}
					{language}
					meta={String(code.properties.metastring ?? '')}
				/>{/if}
		{:else if classes(node).includes('katex-display')}
			<div class="relative my-4 overflow-x-auto rounded-lg p-2">
				<CopyButton text={texSource(node)} label="Copy TeX" />{@html toHtml(node)}
			</div>
		{:else if classes(node).includes('katex')}
			{@html toHtml(node)}
		{:else if node.tagName === 'a'}
			<SafeLink href={String(node.properties.href)}><Nodes nodes={node.children} /></SafeLink>
		{:else if node.tagName === 'table'}
			<div class="my-4 overflow-x-auto rounded-lg border border-border">
				<div class="flex justify-end">
					<CopyButton text={tableMarkdown(node)} label="Copy table" />
				</div>
				<table><Nodes nodes={node.children} /></table>
			</div>
		{:else if node.tagName === 'blockquote' && alertContent(node)}
			{@const alert = alertContent(node)!}
			<aside
				class="my-4 rounded-lg border border-border bg-muted/30 px-4 py-2"
				aria-label={alert.kind}
			>
				<strong>{alert.kind}</strong><Nodes nodes={alert.children} />
			</aside>
		{:else if node.tagName === 'input'}<input
				type="checkbox"
				disabled
				checked={Boolean(node.properties.checked)}
			/>
		{:else if node.tagName === 'source'}<svelte:element this={node.tagName} {...attributes(node)} />
		{:else if node.tagName === 'br'}<br />
		{:else if node.tagName === 'hr'}<hr />
		{:else}
			<svelte:element this={node.tagName} {...attributes(node)}>
				<Nodes nodes={node.children} />
			</svelte:element>
		{/if}
	{/if}
{/each}
