/** Coordinates the desktop/tablet Settings modal overlay. */
class SettingsOverlay {
	open = $state(false);
	section = $state<string>('appearance');
	plugin = $state<string | null>(null);

	show(section = 'appearance', plugin: string | null = null): void {
		this.section = section.toLowerCase();
		this.plugin = plugin;
		this.open = true;
	}

	close(): void {
		this.open = false;
		this.plugin = null;
	}
}

export const settingsOverlay = new SettingsOverlay();
