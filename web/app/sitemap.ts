import type { MetadataRoute } from 'next';
import { SummaryPayload } from '../lib/data';
import { readExport } from '../lib/load';
import { PAGES, siteUrl } from '../lib/site';

// A static export has no server, so this file is rendered once at build time.
export const dynamic = 'force-static';

/**
 * One entry per page. A sitemap has to carry absolute URLs, so when the published address is
 * not known (a local build) it is left empty rather than filled with guesses.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  if (!siteUrl) return [];
  const summary = await readExport<SummaryPayload>('summary.json');
  const snapshot = summary?.snapshot_date ? new Date(summary.snapshot_date) : new Date();
  const lastModified = Number.isNaN(snapshot.getTime()) ? new Date() : snapshot;

  return PAGES.map((path) => ({
    url: `${siteUrl}${path}`,
    lastModified,
    changeFrequency: 'daily',
    priority: path === '/' ? 1 : 0.7,
  }));
}
