"use client";

import * as React from "react";

export type AsyncState<T> =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "success"; data: T };

/**
 * Run `fn` whenever `key` changes (null = idle). Aborts stale requests. Loading is derived from the key, so no
 * synchronous setState happens inside the effect.
 */
export function useAsync<T>(key: string | null, fn: (signal: AbortSignal) => Promise<T>): AsyncState<T> & { retry: () => void } {
  const [nonce, setNonce] = React.useState(0);
  const [result, setResult] = React.useState<{ key: string; state: AsyncState<T> } | null>(null);
  const fnRef = React.useRef(fn);
  React.useEffect(() => {
    fnRef.current = fn;
  });
  const fullKey = key == null ? null : `${key}#${nonce}`;

  React.useEffect(() => {
    if (fullKey == null) return;
    const ctrl = new AbortController();
    fnRef.current(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setResult({ key: fullKey, state: { status: "success", data } }),
      (error: Error) =>
        !ctrl.signal.aborted && error.name !== "AbortError" && setResult({ key: fullKey, state: { status: "error", error } }),
    );
    return () => ctrl.abort();
  }, [fullKey]);

  const retry = React.useCallback(() => setNonce((n) => n + 1), []);
  const state: AsyncState<T> = result && result.key === fullKey ? result.state : { status: "loading" };
  return { ...state, retry };
}
