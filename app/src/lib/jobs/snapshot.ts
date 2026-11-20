import { getImage } from '#lib/api/client.js';

function dataUri(blob: Blob): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(reader.result as string);
		reader.onerror = () => reject(reader.error);
		reader.readAsDataURL(blob);
	});
}

/** The learner photo a figure annotates, as a data URI (the store keeps PNG or JPEG). */
export async function loadSnapshot(sha256: string, signal: AbortSignal): Promise<string> {
	try {
		return await dataUri(await getImage(sha256, 'png', signal));
	} catch (error) {
		if (signal.aborted) throw error;
		return dataUri(await getImage(sha256, 'jpeg', signal));
	}
}
