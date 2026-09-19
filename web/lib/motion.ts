'use client';

import { useSyncExternalStore } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(QUERY);
  media.addEventListener('change', onChange);
  return () => media.removeEventListener('change', onChange);
}

/**
 * Whether the reader has asked for reduced motion.
 *
 * Read as an external store rather than set from an effect: the server renders `false`, the
 * client re-renders with the real answer during hydration, and a change to the OS setting
 * while the page is open is picked up without a reload.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false
  );
}
