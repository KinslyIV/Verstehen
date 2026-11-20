import type { FileAccess } from '#lib/api/client.js';

export const openFileAccess: FileAccess = { restricted: false, folders: [] };

export function isFileAccessFolder(folder: string): boolean {
	return (
		!folder.includes('\0') &&
		(folder === '~' ||
			folder.startsWith('~/') ||
			folder.startsWith('/') ||
			/^[A-Za-z]:[\\/]/.test(folder) ||
			folder.startsWith('\\\\'))
	);
}

export function composeFileRestriction(policy: FileAccess, restricted: boolean): FileAccess {
	return { ...policy, restricted };
}

export function composeAddFolder(policy: FileAccess, input: string): FileAccess {
	const folder = input.trim();
	const folders = policy.folders ?? [];
	if (!isFileAccessFolder(folder) || folders.includes(folder)) return policy;
	return { ...policy, folders: [...folders, folder] };
}

export function composeRemoveFolder(policy: FileAccess, folder: string): FileAccess {
	return { ...policy, folders: (policy.folders ?? []).filter((existing) => existing !== folder) };
}
