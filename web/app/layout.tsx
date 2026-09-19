import type { Metadata } from 'next';
import { Bricolage_Grotesque, IBM_Plex_Mono, Instrument_Sans } from 'next/font/google';
import Cursor from '../components/Cursor';
import Nav from '../components/Nav';
import { SummaryPayload } from '../lib/data';
import { readExport } from '../lib/load';
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

export const metadata: Metadata = {
  title: 'Hijax — nobody vouched for this route',
  description:
    'Follow one BGP route hop by hop and see how much of the internet has actually been vouched for. Measurements of RPKI and ASPA adoption, correctness and effect.',
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
              figure is reproducible from the repository with <code>hijax reproduce</code>, which
              re-derives one date and checks seventeen values against committed fixtures.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
