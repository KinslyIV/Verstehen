/** A request to focus the sidebar's search field, answered once the field exists. */
class SidebarSearch {
	wanted = $state(false);

	focus(): void {
		this.wanted = true;
	}
}

export const sidebarSearch = new SidebarSearch();
