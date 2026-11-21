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
