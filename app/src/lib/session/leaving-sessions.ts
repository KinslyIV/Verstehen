const leaving = new Set<string>();

/** Sessions being deleted or already deleted: their notifications must not refetch them. */
export const isLeaving = (id: string): boolean => leaving.has(id);
export const markLeaving = (id: string): void => void leaving.add(id);
export const unmarkLeaving = (id: string): void => void leaving.delete(id);
