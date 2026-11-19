import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkBreaks from 'remark-breaks';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import { harden } from 'rehype-harden';
import rehypeKatex from 'rehype-katex';
import { cjk } from '@streamdown/cjk';
import remend from 'remend';
import { visit } from 'unist-util-visit';
import type { Root } from 'hast';
import { transformMathDelimiters } from './math-delims';

function codeMetadata() {
	return (tree: Root) => {
		visit(tree, 'element', (node) => {
			if (node.tagName === 'code' && node.data?.meta) node.properties.metastring = node.data.meta;
		});
	};
}

const processor = unified()
	.use(remarkParse)
	.use(cjk.remarkPluginsBefore)
	.use(remarkGfm)
	.use(cjk.remarkPluginsAfter)
	.use(remarkBreaks)
	.use(remarkMath, { singleDollarTextMath: true })
	.use(remarkRehype, { allowDangerousHtml: true })
	.use(codeMetadata)
	.use(rehypeRaw)
	.use(rehypeSanitize, {
		...defaultSchema,
		protocols: {
			...defaultSchema.protocols,
			href: [...(defaultSchema.protocols?.href ?? []), 'tel']
		},
		attributes: {
			...defaultSchema.attributes,
			code: [...(defaultSchema.attributes?.code ?? []), 'metastring']
		}
	})
	.use(harden, {
		allowedLinkPrefixes: ['*'],
		allowedImagePrefixes: [],
		allowedProtocols: ['*'],
		allowDataImages: true
	})
	.use(rehypeKatex);

export function parseMarkdown(source: string, streaming = true): Root {
	const transformed = transformMathDelimiters(source);
	const content = streaming ? remend(transformed, { htmlTags: false }) : transformed;
	return processor.runSync(processor.parse(content)) as Root;
}
