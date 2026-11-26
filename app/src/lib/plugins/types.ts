export type Cleanup = () => void | Promise<void>;
export type PluginSession = 'teaching' | 'practice';

export interface ViewRegistration {
	id: string;
	name: string;
	mount(container: HTMLElement, signal: AbortSignal): void | Cleanup | Promise<void | Cleanup>;
}

export type ActionContext =
	| { placement: 'sidebar'; surface: 'sidebar' }
	| { placement: 'graph'; surface: 'graph' }
	| {
			placement: 'top-bar';
			surface: 'session';
			sessionId: string;
			kind: PluginSession;
	  }
	| { placement: 'top-bar'; surface: 'plugin-view'; pluginId: string; viewId: string };

export interface ActionRegistration {
	id: string;
	name: string;
	/** Trusted SVG markup. */
	icon?: string;
	disabled?: boolean | ((context: ActionContext) => boolean);
	run(context: ActionContext): void | Promise<void>;
}

export type PlacementLocation = 'sidebar' | 'graph' | 'top-bar';

export interface PlacementRegistration {
	id: string;
	actionId: string;
	location: PlacementLocation;
	sessions?: PluginSession[];
	views?: string[];
}

export interface SettingsRowBase {
	key: string;
	label: string;
	description?: string;
	disabled?: boolean;
}

export type SettingsRow =
	| (SettingsRowBase & {
			type: 'toggle';
			value: boolean;
			onChange(value: boolean): void | Promise<void>;
			validate?(value: boolean): string | undefined;
	  })
	| (SettingsRowBase & {
			type: 'text';
			value: string;
			onChange(value: string): void | Promise<void>;
			validate?(value: string): string | undefined;
	  })
	| (SettingsRowBase & {
			type: 'dropdown';
			value: string;
			options: { value: string; label: string }[];
			onChange(value: string): void | Promise<void>;
			validate?(value: string): string | undefined;
	  })
	| (SettingsRowBase & {
			type: 'number' | 'slider';
			value: number;
			min?: number;
			max?: number;
			step?: number;
			onChange(value: number): void | Promise<void>;
			validate?(value: number): string | undefined;
	  });

export interface SettingsMountRegistration {
	mount(container: HTMLElement, signal: AbortSignal): void | Cleanup | Promise<void | Cleanup>;
}

export type SettingsRegistration = SettingsRowsProps | SettingsMountRegistration;

export interface WidgetHandle<Props> {
	update(next: Partial<Props>): void;
	dispose(): void;
}

export interface WidgetOptions {
	signal: AbortSignal;
}

export interface ButtonColorState {
	background?: string;
	text?: string;
	border?: string;
}

export interface ButtonColors extends ButtonColorState {
	hover?: ButtonColorState;
	active?: ButtonColorState;
	focusVisible?: ButtonColorState & { ring?: string };
	disabled?: ButtonColorState;
}

export interface ButtonProps {
	label: string;
	/** Trusted SVG markup. */
	icon?: string;
	iconOnly?: boolean;
	onClick(): void | Promise<void>;
	disabled?: boolean;
	variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link' | 'custom';
	/** CSS colors; applied only when `variant` is `custom`. */
	colors?: ButtonColors;
	size?: 'default' | 'xs' | 'sm' | 'lg' | 'icon' | 'icon-xs' | 'icon-sm' | 'icon-lg';
	title?: string;
}

export interface BadgeProps {
	text: string;
	/** A CSS color for the text and a tint behind it. */
	color?: string;
}

export interface MarkdownProps {
	text: string;
}

export interface SettingsRowsProps {
	rows: SettingsRow[];
}

export type UiContent =
	| HTMLElement
	| ((container: HTMLElement, signal: AbortSignal) => void | Cleanup | Promise<void | Cleanup>);

export interface DialogProps {
	/** The accessible name; headings belong to the content. */
	title: string;
	content: UiContent;
	onClose?(): void | Promise<void>;
}

export interface MenuItem {
	key: string;
	label: string;
	onSelect(): void | Promise<void>;
	disabled?: boolean;
}

export interface MenuProps {
	items: MenuItem[];
	label?: string;
	preferredSide?: 'up' | 'down';
	onClose?(): void | Promise<void>;
}

export interface PluginUi {
	mountButton(
		container: HTMLElement,
		props: ButtonProps,
		options: WidgetOptions
	): WidgetHandle<ButtonProps>;
	mountBadge(
		container: HTMLElement,
		props: BadgeProps,
		options: WidgetOptions
	): WidgetHandle<BadgeProps>;
	mountMarkdown(
		container: HTMLElement,
		props: MarkdownProps,
		options: WidgetOptions
	): WidgetHandle<MarkdownProps>;
	mountSettingsRows(
		container: HTMLElement,
		props: SettingsRowsProps,
		options: WidgetOptions
	): WidgetHandle<SettingsRowsProps>;
	openDialog(props: DialogProps, options: WidgetOptions): WidgetHandle<DialogProps>;
	openMenu(anchor: HTMLElement, props: MenuProps, options: WidgetOptions): WidgetHandle<MenuProps>;
}

export interface PluginAppControls {
	pathname(): string;
	openSession(id: string): void;
	openHome(): void;
	openView(id: string): void;
	openSettings(): void;
}

export type AppEventName = 'turn-settled';

/** What a plugin's `activate(ctx)` receives. */
export interface PluginFrontendContext {
	readonly id: string;
	/** Aborts when the plugin is disabled. */
	readonly signal: AbortSignal;
	readonly backend: Record<string, (input?: unknown) => Promise<unknown>>;
	readonly app: PluginAppControls;
	readonly ui: PluginUi;
	registerView(view: ViewRegistration): () => void;
	registerAction(action: ActionRegistration): () => void;
	placeAction(placement: PlacementRegistration): () => void;
	registerSettings(settings: SettingsRowsProps): WidgetHandle<SettingsRowsProps>;
	registerSettings(settings: SettingsMountRegistration): () => void;
	registerSettings(settings: SettingsRegistration): WidgetHandle<SettingsRowsProps> | (() => void);
	refreshActions(): void;
	onNotification(topic: string, listener: (data: unknown) => void): () => void;
	onResync(listener: () => void): () => void;
	onAppEvent(event: AppEventName, listener: (sessionId: string) => void): () => void;
	cleanup(fn: Cleanup): void;
}

export interface PluginModule {
	activate?(ctx: PluginFrontendContext): void | Cleanup | Promise<void | Cleanup>;
}
