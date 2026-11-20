export function isTypingSurface(target: HTMLElement | null): boolean {
	return (
		!!target &&
		((target instanceof HTMLInputElement && target.type !== 'range') ||
			target instanceof HTMLTextAreaElement ||
			target.isContentEditable)
	);
}

export function questionShortcut(
	event: KeyboardEvent,
	rows: number,
	index: number | null,
	quiz: boolean,
	canSubmit: boolean
) {
	if (event.defaultPrevented || event.isComposing || event.altKey) return;
	const target = event.target as HTMLElement | null;
	const typing = isTypingSurface(target);
	const modded = event.ctrlKey || event.metaKey;
	const activationControl = target?.closest('a, button:not([data-question-row])');
	if (
		event.key === 'Enter' &&
		canSubmit &&
		(!event.shiftKey || modded) &&
		(!typing || modded) &&
		!activationControl &&
		!target?.closest('[role="dialog"]')
	) {
		return { type: 'submit' } as const;
	}
	if (!rows || modded) return;
	if (event.key === 'Tab' && !event.shiftKey) {
		return {
			type: target?.closest('[data-question-row]') ? 'thinking' : 'focus',
			index: index ?? 0
		} as const;
	}
	if (typing) return;
	switch (event.key) {
		case 'ArrowDown':
			return { type: 'walk', index: Math.min((index ?? -1) + 1, rows - 1) } as const;
		case 'ArrowUp':
			return { type: 'walk', index: Math.max((index ?? rows) - 1, 0) } as const;
		case ' ':
			if (index !== null && !activationControl) return { type: 'pick', index } as const;
			return;
		case 'ArrowLeft':
		case 'ArrowRight':
			if (quiz) return { type: 'confidence', step: event.key === 'ArrowRight' ? 1 : -1 } as const;
	}
}

export function escAbortTarget({
	overlay,
	pending,
	busy
}: {
	overlay: boolean;
	pending: boolean;
	busy: boolean;
}): 'question' | 'turn' | null {
	if (overlay) return null;
	if (pending) return 'question';
	return busy ? 'turn' : null;
}

export function hasOpenOverlay(): boolean {
	return !!document.querySelector(
		'[data-slot="dialog-content"]:not([data-state="closed"]), [data-popover-content][data-state="open"], [data-context-menu-content][data-state="open"], [data-mermaid-focus]'
	);
}
