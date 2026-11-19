import { invoke, isTauri } from '@tauri-apps/api/core';

let token: string | undefined;
let connection: Promise<string> | undefined;

export function setToken(value: string | undefined): void {
	token = value;
}

function baseUrl(): Promise<string> {
	if (!isTauri()) return Promise.resolve('');
	return (connection ??= invoke<{ port: number; token: string }>('sidecar_connection').then(
		(value) => {
			setToken(value.token);
			return `http://127.0.0.1:${value.port}`;
		}
	));
}

export async function health(): Promise<{ status: string }> {
	const base = await baseUrl();
	const response = await fetch(`${base}/api/health`, {
		headers: token ? { 'x-verstehen-token': token } : {}
	});
	if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	return response.json();
}
