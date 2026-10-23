import { useEffect, useState } from "react";
import { currentToken } from "./api";

const cache = new Map<string, string>();

/**
 * Page images sit behind authentication, so a plain <img src> cannot fetch them.
 * We pull them with the bearer token and hand the browser an object URL.
 */
export function useProtectedImage(url: string | null): { src: string | null; error: string | null } {
  const [state, setState] = useState<{ src: string | null; error: string | null }>({ src: url ? cache.get(url) ?? null : null, error: null });

  useEffect(() => {
    let cancelled = false;
    if (!url) {
      setState({ src: null, error: null });
      return;
    }
    const cached = cache.get(url);
    if (cached) {
      setState({ src: cached, error: null });
      return;
    }
    setState({ src: null, error: null });
    const token = currentToken();
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((response) => {
        if (!response.ok) throw new Error(`Page image request failed (${response.status})`);
        return response.blob();
      })
      .then((blob) => {
        const objectUrl = URL.createObjectURL(blob);
        cache.set(url, objectUrl);
        if (!cancelled) setState({ src: objectUrl, error: null });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ src: null, error: error.message });
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
}
