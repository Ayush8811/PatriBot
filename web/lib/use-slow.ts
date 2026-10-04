"use client";

import * as React from "react";

/** After this long, a pending API call is probably a cold start of the free API host. */
export const SLOW_AFTER_MS = 4000;

/**
 * True once the operation identified by `key` (null = nothing pending) has been pending for `ms`. Used to swap a
 * plain skeleton for a "Waking up the server…" message while the sleeping API host starts (30–60 s).
 */
export function useSlow(key: string | null, ms = SLOW_AFTER_MS): boolean {
  const [slowKey, setSlowKey] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (key == null) return;
    const t = setTimeout(() => setSlowKey(key), ms);
    return () => clearTimeout(t);
  }, [key, ms]);
  return key != null && slowKey === key;
}
