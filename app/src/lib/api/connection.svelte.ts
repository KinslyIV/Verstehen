import { invoke, isTauri } from '@tauri-apps/api/core';

export interface SidecarConnection {
	base: string;
	token?: string;
}

/** Desktop sidecar startup as the shell shows it; requests share each connection lookup. */
export class SidecarState {
	status = $state<'pending' | 'ready' | 'failed'>('ready');
	failure = $state<string | null>(null);
	private connection: Promise<SidecarConnection> | undefined;

	connect(): Promise<SidecarConnection> {
		if (!isTauri()) return Promise.resolve({ base: '' });
		return (this.connection ??= this.lookUp());
	}

	private async lookUp(): Promise<SidecarConnection> {
		if (this.status !== 'failed') this.status = 'pending';
		try {
			const value = await invoke<{ port: number; token: string }>('sidecar_connection');
			this.status = 'ready';
			this.failure = null;
			return { base: `http://127.0.0.1:${value.port}`, token: value.token };
		} catch (cause) {
			this.connection = undefined;
			const error = cause instanceof Error ? cause : new Error(String(cause));
			this.status = 'failed';
			this.failure = error.message;
			throw error;
		}
	}
}

export const sidecar = new SidecarState();
export const connectSidecar = () => sidecar.connect();
