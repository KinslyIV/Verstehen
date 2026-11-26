import { getContext, setContext } from 'svelte';

const deferredRowKey = Symbol('deferred row');
export const getRowDeferred = () => getContext<(() => boolean) | undefined>(deferredRowKey);
export const setRowDeferred = (deferred: () => boolean) => setContext(deferredRowKey, deferred);
