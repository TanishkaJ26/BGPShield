import type { MetadataRoute } from 'next';
import { siteUrl } from '../lib/site';

// A static export has no server, so this file is rendered once at build time.
export const dynamic = 'force-static';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', allow: '/' },
    ...(siteUrl ? { sitemap: `${siteUrl}/sitemap.xml` } : {}),
  };
}
