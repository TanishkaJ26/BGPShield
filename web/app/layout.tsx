import type { Metadata, Viewport } from 'next';
import { Bricolage_Grotesque, IBM_Plex_Mono, Instrument_Sans } from 'next/font/google';
import Cursor from '../components/Cursor';
import Nav from '../components/Nav';
import { SummaryPayload } from '../lib/data';
import { readExport } from '../lib/load';
import { siteUrl } from '../lib/site';
import './globals.css';

/**
 * Fonts are self-hosted by `next/font` at build time rather than fetched at runtime, so the
 * static export makes no third-party requests and an archived copy still looks like itself.
 */
const display = Bricolage_Grotesque({
  subsets: ['latin'],
  axes: ['opsz', 'wdth'],
  variable: '--font-display',
  display: 'swap',
});
const body = Instrument_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});
const mono = IBM_Plex_Mono({
  weight: ['400', '500'],
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

const TITLE = 'BGPShield — nobody vouched for this route';
const DESCRIPTION =
  'Follow one BGP route hop by hop and see how much of the internet has actually been vouched for. Measurements of RPKI and ASPA adoption, correctness and effect.';

export const metadata: Metadata = {
  // Absolute URLs (Open Graph, the sitemap) need the published address, which only the
  // deploy knows. Locally it is unset and Next falls back to relative links.
  ...(siteUrl ? { metadataBase: new URL(siteUrl) } : {}),
  title: { default: TITLE, template: '%s · BGPShield' },
  description: DESCRIPTION,
  applicationName: 'BGPShield',
  keywords: ['BGP', 'RPKI', 'ASPA', 'route origin validation', 'route leak', 'internet measurement'],
  openGraph: { type: 'website', siteName: 'BGPShield', title: TITLE, description: DESCRIPTION, locale: 'en_US' },
  twitter: { card: 'summary', title: TITLE, description: DESCRIPTION },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#06070b',
  colorScheme: 'dark',
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // The chip in the navbar names the snapshot every page describes, and the footer names the
  // collectors behind it. Both are read once at build time. A daily refresh runs from one
  // collector; the write-up uses six; a reader must always be able to tell which this is.
  const summary = await readExport<SummaryPayload>('summary.json');
  const collectors = summary?.collectors ?? [];

  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        {/*
          Without JavaScript nothing ever adds the `on` and `shown` classes, so every headline
          and every revealed block would sit at `opacity: 0` for ever - the site's own README
          promises the opposite, and a page that is printed, archived or read by a crawler is
          exactly where the numbers have to survive. These rules are the visibility half of the
          reduced-motion block in globals.css, and apply only when scripting is off.
        */}
        <noscript>
          <style>{`
            .kinetic .w > span { transform: none; opacity: 1; }
            [data-reveal] { opacity: 1; transform: none; }
            .story { height: auto; }
            .story-stage { position: static; height: auto; overflow: visible; }
            .story-copy { min-height: 0; }
            .story-step { position: static; opacity: 1; transform: none; margin-bottom: 2rem; }
            .rail { height: auto; }
            .rail-stage { position: static; height: auto; overflow: auto; }
            .cursor, .cursor-ring { display: none; }
          `}</style>
        </noscript>
        <Cursor />
        <header className="site-head">
          <Nav snapshot={summary?.snapshot_date ?? null} />
        </header>

        <main>{children}</main>

        <footer className="site-foot">
          <div className="shell">
            {collectors.length ? (
              <p className="meta" style={{ marginBottom: '0.8rem' }}>
                <span className="mono" style={{ textTransform: 'uppercase', letterSpacing: '0.14em', fontSize: '0.66rem', color: 'var(--route)' }}>
                  Scope of this page
                </span>
                <br />
                Routing snapshot {summary?.snapshot_date}, measured from{' '}
                <strong>{collectors.length} collector{collectors.length === 1 ? '' : 's'}</strong>{' '}
                ({collectors.join(', ')}). The written study uses six; a daily refresh uses one, so
                the two are not directly comparable and are never presented as such.
              </p>
            ) : null}
            <p className="meta">
              Passive measurement only — this project never sends traffic to any network. Every
              figure is reproducible from the repository with <code>bgpshield reproduce</code>, which
              re-derives one date and checks seventeen values against committed fixtures.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
