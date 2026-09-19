/**
 * Static export, so the dashboard can be served from GitHub Pages with no server at all
 * (plan Section 11, Phase 7).
 *
 * GitHub Pages serves a project site from /<repo>, so the base path has to be set at build
 * time. Vercel and a local preview serve from the root, so it defaults to empty:
 *
 *   NEXT_PUBLIC_BASE_PATH=/BGPShield npm run build
 */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? '';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  reactStrictMode: true,
  poweredByHeader: false,
  basePath,
  // Pages is a plain file server with no redirect rules, so every route needs its own
  // directory and index.html.
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
