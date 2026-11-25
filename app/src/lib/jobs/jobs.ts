import type { Entry, JobRecord } from '#lib/api/client.js';
import { asObject } from '#lib/questions/question-input.js';

export type JobKind = JobRecord['kind'];

export const JOB_KINDS: readonly JobKind[] = ['research', 'demo', 'visual', 'pdf'];

export const dispatchLabel: Record<JobKind, string> = {
	research: 'Research agent',
	demo: 'Demo agent',
	visual: 'Figure agent',
	pdf: 'PDF reader'
};

export const workerLabel: Record<JobKind, string> = {
	research: 'Researcher',
	demo: 'Demo builder',
	visual: 'Figure maker',
	pdf: 'PDF reader'
};

export function isJobKind(value: unknown): value is JobKind {
	return JOB_KINDS.includes(value as JobKind);
}

/** LearnHarness's `planCostLabel` for unpriced runs: the plan name, else a dash. */
export function jobCostLabel(job: JobRecord): string {
	return job.usage?.account_kind === 'chatgpt' ? 'ChatGPT' : '—';
}

export function totalCostLabel(jobs: JobRecord[]): string {
	return [...new Set(jobs.map(jobCostLabel).filter((label) => label !== '—'))].join(' + ') || '—';
}

/** Whole seconds since the job began; times without a zone are UTC. */
export function elapsedSeconds(job: JobRecord, now: number): number {
	const created = job.created_at ?? '';
	const started = Date.parse(/(?:Z|[+-]\d\d:?\d\d)$/.test(created) ? created : `${created}Z`);
	return Math.max(0, Math.round((now - started) / 1000));
}

export function formatElapsed(seconds: number): string {
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
	return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
}

export type Source = { title: string; url: string };
export type ResearchResult = { brief: string; sources: Source[] };
export type PdfResult = {
	path: string;
	question: string;
	brief: string;
	pages_read: number[];
	pages_consulted: number[];
};
export type VisualResult = {
	svg: string;
	notes?: string | null;
	image?: { path: string; snapshot_id: string } | null;
};
export type DemoResult = { title: string; html: string; notes?: string | null };

export type MarkerCard =
	| { type: 'research'; failed: boolean; result: ResearchResult }
	| { type: 'pdf'; failed: boolean; result: PdfResult }
	| { type: 'visual'; result: VisualResult }
	| { type: 'demo'; result: DemoResult }
	| { type: 'aborted'; kind: string }
	| { type: 'failure'; failure: string }
	| { type: 'unreadable' };

function researchResult(value: Record<string, unknown>): ResearchResult | undefined {
	if (typeof value.brief !== 'string') return;
	const sources = Array.isArray(value.sources) ? value.sources.map(asObject) : [];
	return {
		brief: value.brief,
		sources: sources.flatMap((source) =>
			typeof source?.title === 'string' && typeof source.url === 'string'
				? [{ title: source.title, url: source.url }]
				: []
		)
	};
}

function pdfResult(value: Record<string, unknown>): PdfResult | undefined {
	if (typeof value.brief !== 'string') return;
	const read = Array.isArray(value.pages_read) ? (value.pages_read as number[]) : [];
	return {
		path: typeof value.path === 'string' ? value.path : '',
		question: typeof value.question === 'string' ? value.question : '',
		brief: value.brief,
		pages_read: read,
		pages_consulted: Array.isArray(value.pages_consulted)
			? (value.pages_consulted as number[])
			: read
	};
}

/** Presentation model of a job marker; undefined for markers that are not job deliveries. */
export function markerCard(entry: Entry): MarkerCard | undefined {
	if (entry.kind !== 'marker') return;
	const details = asObject(entry.details);
	if (entry.marker_type === 'subagent-abort') {
		if (typeof details?.failure === 'string') return { type: 'failure', failure: details.failure };
		return { type: 'aborted', kind: typeof details?.kind === 'string' ? details.kind : 'job' };
	}
	if (entry.marker_type !== 'subagent-steer') return;
	const result = asObject(details?.result);
	const kind = details?.kind;
	if (!result || !isJobKind(kind)) return { type: 'unreadable' };
	if (kind === 'research') {
		const parsed = researchResult(result);
		if (!parsed) return { type: 'unreadable' };
		const failed =
			parsed.sources.length === 0 && parsed.brief.toLowerCase().startsWith('research failed:');
		return { type: 'research', failed, result: parsed };
	}
	if (kind === 'pdf') {
		const parsed = pdfResult(result);
		if (!parsed) return { type: 'unreadable' };
		return {
			type: 'pdf',
			failed: parsed.brief.toLowerCase().startsWith('pdf failed:'),
			result: parsed
		};
	}
	if (kind === 'visual')
		return typeof result.svg === 'string'
			? { type: 'visual', result: result as unknown as VisualResult }
			: { type: 'unreadable' };
	return typeof result.html === 'string' && typeof result.title === 'string'
		? { type: 'demo', result: result as unknown as DemoResult }
		: { type: 'unreadable' };
}

export function isWebSourceUrl(url: string): boolean {
	try {
		const parsed = new URL(url);
		return ['http:', 'https:'].includes(parsed.protocol) && parsed.hostname !== '';
	} catch {
		return false;
	}
}

export type DemoBridgeState = { height: number | null; error: string | null };
export const INITIAL_DEMO_BRIDGE_STATE: DemoBridgeState = { height: null, error: null };
const MIN_HEIGHT = 80;
const MAX_HEIGHT = 2400;

/** Fold one postMessage from the demo frame into its size and error state. */
export function reduceDemoBridgeState(state: DemoBridgeState, data: unknown): DemoBridgeState {
	const message = asObject(data);
	if (!message) return state;
	if (message.type === 'demo-resize') {
		const value = message.height;
		if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return state;
		const height = Math.min(Math.max(Math.round(value), MIN_HEIGHT), MAX_HEIGHT);
		return height === state.height ? state : { ...state, height };
	}
	if (message.type === 'demo-error') {
		const text =
			typeof message.message === 'string' && message.message.trim()
				? message.message
				: 'unknown error';
		return text === state.error ? state : { ...state, error: text };
	}
	return state;
}

/** How far from the transcript viewport a demo frame stays loaded. */
export const DEMO_LOAD_MARGIN = '200% 0px';

/** Whether a demo card keeps its iframe mounted: near the viewport, or zoomed (never unloaded). */
export function demoFrameMounted(near: boolean, zoomed: boolean): boolean {
	return near || zoomed;
}

/** Whether a demo-frame message is the Escape key forwarded out of the sandboxed iframe. */
export function isDemoEscape(data: unknown): boolean {
	return asObject(data)?.type === 'demo-escape';
}

export const DEMO_BRIDGE_SCRIPT = `<script>(function(){
var send=function(m){try{parent.postMessage(m,"*")}catch(e){}};
var post=function(){
var b=document.body;
if(!b){send({type:"demo-resize",height:document.documentElement.scrollHeight});return}
var h=Math.max(b.scrollHeight,b.getBoundingClientRect().height);
var cs=getComputedStyle(b);
h+=(parseFloat(cs.marginTop)||0)+(parseFloat(cs.marginBottom)||0);
send({type:"demo-resize",height:Math.ceil(h)})
};
if(typeof ResizeObserver!=="undefined"){new ResizeObserver(post).observe(document.documentElement)}
window.addEventListener("resize",post);
window.addEventListener("load",post);
window.addEventListener("keydown",function(e){if(e.key==="Escape")send({type:"demo-escape"})});
window.addEventListener("error",function(e){send({type:"demo-error",message:e.message||String(e)})});
setTimeout(post,50);
setTimeout(post,400);
})();</script>`;

/** The document the frame runs: the demo with the resize and error bridge added. */
export function demoSrcDoc(html: string): string {
	if (/<\/body>/i.test(html))
		return html.replace(/<\/body>/i, () => `${DEMO_BRIDGE_SCRIPT}</body>`);
	return `${html}${DEMO_BRIDGE_SCRIPT}`;
}

/** The svg root's declared pixel width, the natural size the figure shows at. */
export function svgNaturalWidth(svg: string): number | null {
	const match = /<svg\b[^>]*?\bwidth\s*=\s*["']([^"']+)["'][^>]*>/i.exec(svg);
	const pixels = /^(\d+(?:\.\d+)?)(?:px)?$/i.exec(match?.[1]?.trim() ?? '');
	const width = pixels ? Number.parseFloat(pixels[1]!) : NaN;
	return Number.isFinite(width) && width > 0 ? width : null;
}

const SVG_TOKEN =
	/<!--[\s\S]*?(?:-->|$)|<!\[CDATA\[[\s\S]*?(?:\]\]>|$)|<\?[\s\S]*?(?:\?>|$)|<\/?[a-zA-Z](?:[^<>"']|"[^"]*"|'[^']*')*>|&nbsp;/g;

/** Display-only repairs: add the missing SVG namespace and replace `&nbsp;`. */
export function svgImageSource(svg: string): string {
	let foundRoot = false;
	return svg.replace(SVG_TOKEN, (token) => {
		if (token.startsWith('<!--') || token.startsWith('<![CDATA[') || token.startsWith('<?'))
			return token;
		if (!foundRoot && /^<svg(?=[\s/>])/i.test(token)) {
			foundRoot = true;
			const attributes = [
				...token.matchAll(/\s([^\s=/>]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?/g)
			];
			if (!attributes.some((attribute) => attribute[1] === 'xmlns'))
				token = token.replace(/^<svg/i, '$& xmlns="http://www.w3.org/2000/svg"');
		}
		return token.replace(/&nbsp;/g, '&#160;');
	});
}

export const LEARNER_IMAGE_HREF = 'learner-image';

/** Put the learner's photo into the annotation's `learner-image` image element. */
export function embedLearnerImage(svg: string, dataUri: string): string {
	return svg.replace(SVG_TOKEN, (token) => {
		if (!/^<image(?=[\s/>])/.test(token)) return token;
		return token.replace(
			/(\s+)([^\s=/>]+)(\s*=\s*)("[^"]*"|'[^']*')/g,
			(match, space: string, name: string, equals: string, value: string) =>
				(name === 'href' || name === 'xlink:href') && value.slice(1, -1) === LEARNER_IMAGE_HREF
					? `${space}${name}${equals}${value[0]}${dataUri}${value[0]}`
					: match
		);
	});
}

export function svgDataUri(svg: string): string {
	return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgImageSource(svg))}`;
}
