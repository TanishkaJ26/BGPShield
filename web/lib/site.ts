/**
 * Where the site is published, for the few places that need an absolute URL.
 *
 * `NEXT_PUBLIC_SITE_URL` is set by the deploy workflow to the GitHub Pages address, including
 * the project path. Locally it is unset, and everything that needs it degrades: the sitemap is
 * empty, social previews carry no absolute image, and nothing else changes.
 */

/** The published origin plus base path, with no trailing slash, or null when unknown. */
export const siteUrl: string | null = (() => {
  const raw = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (!raw) return null;
  try {
    return new URL(raw).toString().replace(/\/$/, '');
  } catch {
    return null;
  }
})();

/** Every page in the site, as the paths the static export writes (trailing slash on). */
export const PAGES = ['/', '/networks/', '/incidents/', '/region/', '/methodology/'] as const;

/**
 * Where the source lives. Every number on this site is reproducible from that repository,
 * which is the whole argument of the project, so the link belongs in the navigation rather
 * than buried in a footer.
 */
export const repoUrl = 'https://github.com/TanishkaJ26/BGPShield';
