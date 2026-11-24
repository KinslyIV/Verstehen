const MARGIN = 8;
const GAP = 12;

/** Below the node, flipped above near the bottom edge, clamped horizontally. */
export function placeNodeCard(
	anchor: { x: number; y: number },
	card: { width: number; height: number },
	container: { width: number; height: number }
): { left: number; top: number } {
	const left = Math.min(
		Math.max(anchor.x - card.width / 2, MARGIN),
		Math.max(container.width - card.width - MARGIN, MARGIN)
	);
	let top = anchor.y + GAP;
	if (top + card.height > container.height - MARGIN)
		top = Math.max(anchor.y - GAP - card.height, MARGIN);
	return { left, top };
}

/** At the pointer, pulled back inside the container when it would overflow the right or bottom edge. */
export function placeContextMenu(
	anchor: { x: number; y: number },
	menu: { width: number; height: number },
	container: { width: number; height: number }
): { left: number; top: number } {
	return {
		left: Math.max(Math.min(anchor.x, container.width - menu.width - MARGIN), MARGIN),
		top: Math.max(Math.min(anchor.y, container.height - menu.height - MARGIN), MARGIN)
	};
}
