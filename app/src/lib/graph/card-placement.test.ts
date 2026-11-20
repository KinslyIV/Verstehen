import { describe, expect, it } from 'vitest';
import { placeNodeCard } from './card-placement.js';

const card = { width: 320, height: 160 };
const container = { width: 1000, height: 700 };

describe('node card placement', () => {
	it('sits below the node and centered on it', () => {
		expect(placeNodeCard({ x: 500, y: 200 }, card, container)).toEqual({ left: 340, top: 212 });
	});

	it('flips above the node near the bottom edge', () => {
		expect(placeNodeCard({ x: 500, y: 600 }, card, container)).toEqual({ left: 340, top: 428 });
	});

	it('clamps to the container horizontally', () => {
		expect(placeNodeCard({ x: 10, y: 200 }, card, container).left).toBe(8);
		expect(placeNodeCard({ x: 990, y: 200 }, card, container).left).toBe(1000 - 320 - 8);
	});

	it('never leaves the top edge when the card is taller than the space above', () => {
		expect(placeNodeCard({ x: 500, y: 100 }, { width: 320, height: 800 }, container).top).toBe(8);
	});
});
