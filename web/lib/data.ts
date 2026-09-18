/**
 * Loading the exported measurement files.
 *
 * The JSON under public/data is written by `hijax export` from tables already on disk. It is
 * fetched at runtime rather than imported at build time: the per-network table is about a
 * megabyte, and inlining that into the JavaScript bundle would make every page carry it.
 */

/** Static assets sit under the base path too, which is not empty on GitHub Pages. */
export const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

export async function loadJson<T>(name: string): Promise<T | null> {
  try {
    const response = await fetch(`${basePath}/data/${name}`, { cache: 'no-store' });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    // A missing file means that measurement has not been exported yet. The page says so
    // rather than showing a zero, which would read as a result.
    return null;
  }
}

export type RegionRow = {
  region: string;
  networks: number;
  routed_networks: number;
  aspa_publishers: number;
  publishers_that_route: number;
  share_of_routed: number;
};

export type TransitRow = {
  asn: number;
  cone_size: number;
  rank: number | null;
  publishes_aspa: boolean;
};

export type RegionalPayload = {
  snapshot_date: string;
  metadata_month: string;
  country: string;
  regions: RegionRow[];
  largest_transit: TransitRow[];
  notes: string[];
};

export type NetworkRow = {
  asn: number;
  country: string | null;
  rir: string | null;
  cone_size: number | null;
  rank: number | null;
  publishes_aspa: boolean;
  providers_listed: number | null;
  routes_valid: number;
  routes_invalid: number;
  routes_not_found: number;
};

export type NetworksPayload = {
  snapshot_date: string;
  metadata_month: string;
  networks: number;
  selection: string;
  notes: string[];
  rows: NetworkRow[];
};

export type SummaryPayload = {
  adoption?: Record<
    string,
    { routed_networks: number; publishers: number; share_of_routed: number }
  >;
  largest_transit_publishing?: { country: string; examined: number; publishing: number };
  path_coverage?: Record<string, number>;
  caveats: string[];
};

export type AdoptionPayload = {
  snapshots: number;
  latest_snapshot: string | null;
  by_day: { snapshot_date: string; aspas: number; publishers?: number }[];
};

export const percent = (value: number, digits = 2) => `${(value * 100).toFixed(digits)}%`;
export const thousands = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : value.toLocaleString('en-US');
