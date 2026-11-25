const WHEEL_LINE_PX = 16;

function canScroll(element: HTMLElement, deltaY: number): boolean {
	if (!/^(auto|scroll)$/.test(getComputedStyle(element).overflowY)) return false;
	if (element.scrollHeight - element.clientHeight < 2) return false;
	return deltaY < 0
		? element.scrollTop > 0
		: element.scrollTop < element.scrollHeight - element.clientHeight - 0.5;
}

/** Attachment: a wheel over the floating dock scrolls the transcript unless something inside can scroll. */
export function forwardDockWheel(transcript: () => HTMLElement | null) {
	return (dock: HTMLElement) => {
		function onWheel(event: WheelEvent) {
			const target = transcript();
			if (!target || event.deltaY === 0) return;
			for (
				let node = event.target as HTMLElement | null;
				node && node !== dock;
				node = node.parentElement
			)
				if (canScroll(node, event.deltaY)) return;
			event.preventDefault();
			const unit =
				event.deltaMode === 1 ? WHEEL_LINE_PX : event.deltaMode === 2 ? target.clientHeight : 1;
			target.scrollTop += event.deltaY * unit;
		}
		dock.addEventListener('wheel', onWheel, { passive: false });
		return () => dock.removeEventListener('wheel', onWheel);
	};
}
