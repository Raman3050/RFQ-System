import { useSyncExternalStore } from 'react';

import { serverNow } from './serverTime';

/**
 * One shared 1-second ticker for every countdown on the page (instead of one timer
 * per component). Returns server-corrected "now" in ms.
 */
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setInterval> | null = null;
let current = serverNow();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!timer) {
    current = serverNow();
    timer = setInterval(() => {
      current = serverNow();
      listeners.forEach((l) => l());
    }, 1000);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  };
}

export function useNow(): number {
  return useSyncExternalStore(subscribe, () => current);
}
