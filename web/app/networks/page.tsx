import type { Metadata } from 'next';
import Kinetic from '../../components/Kinetic';
import Reveal from '../../components/Reveal';
import { NetworksPayload, thousands } from '../../lib/data';
import { readExport } from '../../lib/load';
import NetworkSearch from './search';

export const metadata: Metadata = {
  title: 'Networks',
  description: 'Origin-validation results and ASPA status for every network that publishes a record, plus the largest by customer cone.',
};

/** How many rows are baked into the HTML so the page means something without JavaScript. */
const PRERENDERED = 100;

export default async function Networks() {
  const payload = await readExport<NetworksPayload>('networks.json');

  if (!payload) {
    return (
      <section className="band" style={{ paddingTop: 160 }}>
        <div className="shell">
          <p className="missing">
            No network table has been exported yet. Run <code>bgpshield export</code> after
            validating a date.
          </p>
        </div>
      </section>
    );
  }

  const publishers = payload.rows.filter((row) => row.publishes_aspa).length;

  return (
    <>
      <section className="hero" style={{ minHeight: '70svh' }}>
        <div className="shell">
          <p className="eyebrow">Per-network results · {payload.snapshot_date}</p>
          <Kinetic as="h1" className="display" text="Look up any network." accent="any" startDelay={120} />
          <div className="hero-foot">
            <p className="lede" style={{ margin: 0 }}>
              Origin-validation results and ASPA status for {thousands(payload.rows.length)}{' '}
              networks, {thousands(publishers)} of which publish a record. Search by AS number,
              country or registry.
            </p>
          </div>
        </div>
      </section>

      <section className="band" style={{ paddingTop: 0 }}>
        <div className="shell">
          <Reveal>
            <NetworkSearch initialRows={payload.rows.slice(0, PRERENDERED)} total={payload.rows.length} />
          </Reveal>
          <div className="note">
            <strong>This is not the whole routing table.</strong>
            {payload.selection} A network absent here is not necessarily absent from the internet.
            <ul>
              {payload.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
              <li>
                <strong>Invalid</strong> does not mean an attack. Roughly one in five Invalid routes
                is better explained by an incomplete published record than by anything wrong with
                the routing.
              </li>
            </ul>
          </div>
        </div>
      </section>
    </>
  );
}
