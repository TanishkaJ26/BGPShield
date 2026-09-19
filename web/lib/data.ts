/**
 * Shared types and formatting for the exported measurements.
 *
 * The JSON under public/data is written by `bgpshield export` from tables already on disk, and is
 * read at build time by `lib/load.ts`. The only thing still fetched in the browser is the full
 * network table, and only when somebody searches, so `basePath` lives here for that one case.
 */

/** Static assets sit under the base path too, which is not empty on GitHub Pages. */
export const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

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
  /** Which ASPA snapshot describes this routing date. They are weekly, routes are daily. */
  aspa_snapshot_date?: string | null;
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
  aspa_snapshot_date?: string | null;
  metadata_month: string;
  networks: number;
  selection: string;
  notes: string[];
  rows: NetworkRow[];
};

export type SummaryPayload = {
  snapshot_date?: string;
  aspa_snapshot_date?: string | null;
  /** Vantage points that fed this export. The write-up uses six; a daily refresh uses one. */
  collectors?: string[];
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
