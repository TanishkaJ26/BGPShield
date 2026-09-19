import Counter from '../../components/Counter';
import Kinetic from '../../components/Kinetic';
import Rail from '../../components/Rail';
import Reveal from '../../components/Reveal';
import { RegionalPayload, thousands } from '../../lib/data';
import { readExport } from '../../lib/load';

export default async function Region() {
  const payload = await readExport<RegionalPayload>('regional.json');

  if (!payload) {
    return (
      <section className="band" style={{ paddingTop: 160 }}>
        <div className="shell">
          <p className="missing">
            No regional comparison has been exported yet. Run <code>hijax export</code> after
            ingesting routes and topology metadata.
          </p>
        </div>
      </section>
    );
  }

  const ranked = payload.largest_transit;
  const publishing = ranked.filter((row) => row.publishes_aspa);
  const first = ranked.find((row) => row.publishes_aspa);
  const largest = ranked[0];

  return (
    <>
      <section className="hero" style={{ minHeight: '80svh' }}>
        <div className="shell">
          <p className="eyebrow">RQ4 · {payload.country} against its region and the world</p>
          <Kinetic
            as="h1"
            className="display"
            text="Ahead of its region. Behind the world."
            accent="Behind"
            startDelay={120}
          />
          <p className="meta" style={{ marginTop: '1.4rem' }}>
            Snapshot {payload.snapshot_date}, topology from {payload.metadata_month}
            {payload.aspa_snapshot_date && payload.aspa_snapshot_date !== payload.snapshot_date
              ? `, ASPA records from ${payload.aspa_snapshot_date}`
              : ''}
            .
          </p>
        </div>
      </section>

      <section className="band" style={{ paddingTop: 0 }}>
        <div className="shell">
          <Reveal>
            <div className="figure">
              {payload.regions.map((row) => (
                <div key={row.region}>
                  <div className={`v ${row.region === 'global' ? 'route' : ''}`}>
                    <Counter value={row.share_of_routed * 100} decimals={2} suffix="%" />
                  </div>
                  <div className="l">
                    <span className="mono" style={{ textTransform: 'uppercase', letterSpacing: '0.14em', fontSize: '0.66rem', display: 'block', marginBottom: '0.3rem', color: 'var(--ink)' }}>
                      {row.region}
                    </span>
                    {thousands(row.publishers_that_route)} publishing of{' '}
                    {thousands(row.routed_networks)} routed
                  </div>
                </div>
              ))}
            </div>
          </Reveal>
          <Reveal delay={120}>
            <p style={{ marginTop: '2rem' }}>
              The denominator is networks seen <strong>originating a route</strong>. A network
              that announces nothing cannot meaningfully publish a record about its providers,
              and counting the tens of thousands of dormant allocations would deflate every share
              for no reason.
            </p>
          </Reveal>
        </div>
      </section>

      <Rail rows={ranked} country={payload.country}>
        <p className="eyebrow">The finding that matters is not the share</p>
        <h2 className="display" style={{ maxWidth: '16ch' }}>
          The biggest networks publish <em>nothing</em>.
        </h2>
        <p className="lede" style={{ marginTop: '1.2rem' }}>
          {ranked.length} largest by customer cone, left to right.{' '}
          {publishing.length === 0 ? 'None publishes' : `${publishing.length} publish${publishing.length === 1 ? 'es' : ''}`}.
          {first && largest
            ? ` The largest that does is AS${first.asn}, cone ${thousands(first.cone_size)}, global rank ${thousands(first.rank)} — while AS${largest.asn} ranks ${thousands(largest.rank)} in the world.`
            : ''}
        </p>
      </Rail>

      <section className="band">
        <div className="shell">
          <Reveal>
            <p>
              That is the opposite of the deployment order that would help. ASPA needs{' '}
              <strong>adjacent</strong> publishers to settle a hop, so a record from a large
              transit network covers every hop into and out of it and protects everything behind
              it. A record from a network at the edge covers one hop.
            </p>
            <div className="note">
              <strong>Two limits travel with every number on this page</strong>
              <ul>
                {payload.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          </Reveal>
        </div>
      </section>
    </>
  );
}
