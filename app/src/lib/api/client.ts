let token: string | undefined;

export function setToken(value: string | undefined): void {
	token = value;
}

export async function health(): Promise<{ status: string }> {
	const response = await fetch('/api/health', {
		headers: token ? { 'x-verstehen-token': token } : {}
	});
	if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
	return response.json();
}
