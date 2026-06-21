import type { Snapshot } from "../types";

/**
 * Load the dataset. Prefers the static snapshot.json (the cheap, CDN-friendly
 * path); falls back to the dynamic /api/snapshot endpoint.
 */
export async function loadSnapshot(): Promise<Snapshot> {
  const sources = ["snapshot.json", "api/snapshot"];
  let lastErr: unknown;
  for (const url of sources) {
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (res.ok) return (await res.json()) as Snapshot;
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(`Could not load data from snapshot.json or /api/snapshot (${lastErr})`);
}
