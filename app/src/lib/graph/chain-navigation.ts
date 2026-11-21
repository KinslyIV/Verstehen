import { navigateTreeRows } from './tree-navigation.js';

const ROW = '[data-chain-nav-row]';

/** Tags a row so the table's keyboard handler can find it: `parts` is its identity, `expanded` its disclosure. */
export function chainRowAttributes(parts: string[], depth: number, expanded?: boolean) {
	return {
		'data-chain-nav-row': JSON.stringify(parts),
		'data-chain-nav-depth': depth,
		'data-chain-nav-expanded': expanded,
		tabindex: -1
	};
}

/** Arrow keys walk the table's visible rows and Space toggles the active row's checkbox. */
export function attachChainNavigation(
	root: HTMLElement,
	search: () => HTMLInputElement | undefined
) {
	let active: string | null = null;
	let pendingEnter: string | null = null;
	const rows = () =>
		[...root.querySelectorAll<HTMLElement>(ROW)].map((element) => ({
			element,
			key: element.dataset.chainNavRow!,
			depth: Number(element.dataset.chainNavDepth),
			expanded:
				element.dataset.chainNavExpanded === undefined
					? undefined
					: element.dataset.chainNavExpanded === 'true'
		}));
	const highlight = (key: string | null, focus = false) => {
		root
			.querySelectorAll('[data-chain-nav-active]')
			.forEach((row) => row.removeAttribute('data-chain-nav-active'));
		const row = rows().find((candidate) => candidate.key === key)?.element;
		active = row ? key : null;
		if (!row) return;
		row.dataset.chainNavActive = 'true';
		if (focus) {
			row.focus({ preventScroll: true });
			row.scrollIntoView({ block: 'nearest' });
		}
	};
	const onPointerDown = (event: PointerEvent) => {
		const row = event.target instanceof Element ? event.target.closest<HTMLElement>(ROW) : null;
		if (row) highlight(row.dataset.chainNavRow!);
	};
	const onKeyDown = (event: KeyboardEvent) => {
		if (
			event.defaultPrevented ||
			event.isComposing ||
			event.metaKey ||
			event.ctrlKey ||
			event.altKey ||
			event.shiftKey ||
			!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' '].includes(event.key)
		)
			return;
		const target = event.target instanceof Element ? event.target : null;
		if (target && !root.contains(target) && target !== document.body) return;
		const fromSearch = target === search();
		if (
			fromSearch
				? event.key !== 'ArrowDown'
				: target?.closest('input:not([type="checkbox"]),textarea')
		)
			return;
		if (event.key === ' ') {
			if (
				target?.closest('button,a[href]') &&
				(!target.closest(ROW) || target.closest('[data-chain-statement]'))
			)
				return;
			const row = rows().find((candidate) => candidate.key === active);
			const checkbox = row?.element.querySelector<HTMLInputElement>('input[type="checkbox"]');
			if (!row || !checkbox || checkbox.disabled) return;
			event.preventDefault();
			checkbox.click();
			highlight(row.key, true);
			return;
		}
		const result = navigateTreeRows(rows(), fromSearch ? null : active, event.key);
		if (!result.key) return;
		event.preventDefault();
		highlight(result.key, true);
		if (!result.toggle) return;
		pendingEnter = result.enter ? result.key : null;
		rows()
			.find((candidate) => candidate.key === result.toggle)
			?.element.querySelector<HTMLButtonElement>('button[aria-expanded]')
			?.click();
		queueMicrotask(() => {
			if (pendingEnter === null) return;
			const all = rows();
			const index = all.findIndex((candidate) => candidate.key === pendingEnter);
			const child = all[index + 1];
			if (child && child.depth > all[index]!.depth) highlight(child.key, true);
			pendingEnter = null;
		});
	};
	document.addEventListener('keydown', onKeyDown);
	root.addEventListener('pointerdown', onPointerDown);
	return {
		focusRow(parts: string[]) {
			highlight(JSON.stringify(parts), true);
		},
		destroy() {
			document.removeEventListener('keydown', onKeyDown);
			root.removeEventListener('pointerdown', onPointerDown);
		}
	};
}
