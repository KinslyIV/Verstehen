import type { OrganizationAction, SourceOrganization } from '#lib/api/client.js';
import {
	DRAG_TYPE,
	canMoveFolder,
	dropMove,
	parseDragPayload,
	type DraggedEntry
} from './source-organization.js';

/** The drag state of one source tree and the handlers that make a row or area a drop target. */
export class SourceDrop {
	dragged = $state<DraggedEntry>();
	/** The folder a drop would land in, null for outside every folder, undefined for none. */
	target = $state<string | null>();

	constructor(
		private organization: () => SourceOrganization | undefined,
		private move: (action: OrganizationAction) => Promise<unknown>
	) {}

	/** Follows the drag a row starts or ends. */
	drag(item: DraggedEntry | undefined): void {
		this.dragged = item;
		if (!item) this.target = undefined;
	}

	/** WebKit hides custom drag types from dragover, so a drag we started counts too. */
	private draggingOurs(transfer: DataTransfer): boolean {
		return this.dragged !== undefined || transfer.types.includes(DRAG_TYPE);
	}

	/** Event handlers that drop into `parentId` (null: outside every folder). */
	props(parentId: string | null) {
		return {
			ondragover: (event: DragEvent) => {
				const organization = this.organization();
				if (!organization || !event.dataTransfer || !this.draggingOurs(event.dataTransfer)) return;
				event.preventDefault();
				event.stopPropagation();
				const valid =
					this.dragged?.kind !== 'folder' || canMoveFolder(organization, this.dragged.id, parentId);
				event.dataTransfer.dropEffect = valid ? 'move' : 'none';
				this.target = valid ? parentId : undefined;
			},
			ondragleave: (event: DragEvent) => {
				if (
					event.currentTarget instanceof Node &&
					event.currentTarget.contains(event.relatedTarget as Node | null)
				)
					return;
				event.stopPropagation();
				if (this.target === parentId) this.target = undefined;
			},
			ondrop: (event: DragEvent) => {
				const organization = this.organization();
				const raw = event.dataTransfer?.getData(DRAG_TYPE);
				const item = raw ? parseDragPayload(raw) : this.dragged;
				if (!organization || !item) return;
				event.preventDefault();
				event.stopPropagation();
				this.drag(undefined);
				const action = item && dropMove(organization, item, parentId);
				if (action) void this.move(action).catch(() => {});
			}
		};
	}
}
