import Link from 'next/link';

import Counter from '../components/Counter';
import Kinetic from '../components/Kinetic';
import Reveal from '../components/Reveal';
import RouteStory from '../components/RouteStory';
import { AdoptionPayload, RegionalPayload, SummaryPayload, thousands } from '../lib/data';
import { readExport } from '../lib/load';

export default async function Overview() {
  const summary = await readExport<SummaryPayload>('summary.json');
  const adoption = await readExport<AdoptionPayload>('aspa_adoption.json');
  const regional = await readExport<RegionalPayload>('regional.json');

  const global = summary?.adoption?.['global'];
  const coverage = summary?.path_coverage;
  const transit = summary?.largest_transit_publishing;
  const peak = adoption?.by_day?.length ? Math.max(...adoption.by_day.map((p) => p.aspas)) : 0;

  const ticker = [
    global ? `${thousands(global.routed_networks)} routed networks` : null,
    global ? `${thousands(global.publishers)} publish an ASPA record` : null,
    adoption ? `${thousands(adoption.snapshots)} weekly RPKI snapshots` : null,
    peak ? `${thousands(peak)} records at peak` : null,
    'six collectors · five cities · none in India',
    'passive data only · nothing is probed',
    'every number reproducible with bgpshield reproduce',
  ].filter(Boolean) as string[];

  return (
    <>
      <section className="hero">
        <div className="shell">
          <p className="eyebrow">RPKI &amp; ASPA · measured, not modelled</p>
          <Kinetic
            as="h1"
            className="display"
            text="Nobody vouched for this route."
            accent="vouched"
            startDelay={120}
          />
          <div className="hero-foot">
            <p className="lede" style={{ margin: 0 }}>
              BGP moves every packet on the internet along paths that no one has to justify.
              Two mechanisms are meant to change that. Scroll to follow a single route and see
              how far they have actually got.
            </p>
            <span className="scroll-hint">
              <i aria-hidden="true" /> scroll
            </span>
          </div>
        </div>
      </section>

      {ticker.length ? (
        <div className="ticker" aria-hidden="true">
          <div className="ticker-track">
            {[...ticker, ...ticker].map((item, index) => (
              <span key={`${item}-${index}`}>{item}</span>
            ))}
          </div>
        </div>
      ) : null}

      {coverage ? (
        <RouteStory shares={coverage} />
      ) : (
        <section className="band">
          <div className="shell">
            <p className="missing">
              No summary has been exported yet. Run <code>bgpshield export</code> after ingesting and
              validating a date.
            </p>
          </div>
        </section>
      )}

      {global && coverage ? (
        <section className="band">
          <div className="shell">
            <Reveal>
              <p className="eyebrow">The three numbers</p>
              <h2 className="display" style={{ maxWidth: '14ch' }}>
                Presence is not <em>protection</em>.
              </h2>
            </Reveal>
            <Reveal delay={120}>
              <div className="figure" style={{ marginTop: '3rem' }}>
                <div>
                  <div className="v route">
                    <Counter value={global.share_of_routed * 100} decimals={2} suffix="%" />
                  </div>
                  <div className="l">
                    of routed networks publish an ASPA record — {thousands(global.publishers)} of{' '}
                    {thousands(global.routed_networks)}
                  </div>
                </div>
                <div>
                  <div className="v">
                    <Counter value={coverage['any'] * 100} decimals={1} suffix="%" />
                  </div>
                  <div className="l">of routes touch a publisher somewhere on the path</div>
                </div>
                <div>
                  <div className="v vouched">
                    <Counter value={coverage['adjacent_pair'] * 100} decimals={1} suffix="%" />
                  </div>
                  <div className="l">contain a hop with publishers on both sides</div>
                </div>
                <div>
                  <div className="v gap">
                    <Counter value={coverage['all_hops'] * 100} decimals={2} suffix="%" />
                  </div>
                  <div className="l">are vouched for end to end</div>
                </div>
              </div>
            </Reveal>
            <Reveal delay={200}>
              <div className="note">
                <strong>Quoting the second number alone overstates it by about sevenfold.</strong>
                An ASPA record can only settle a hop when the networks on both sides of it
                publish. Adoption is scattered, and scattered adoption composes badly: value
                appears only where two publishers happen to land beside each other.
              </div>
            </Reveal>
          </div>
        </section>
      ) : null}

      {transit && regional ? (
        <section className="band">
          <div className="shell">
            <Reveal>
              <p className="eyebrow">Where it is missing most</p>
              <h2 className="display" style={{ maxWidth: '16ch' }}>
                The biggest networks in {transit.country} publish <em>nothing</em>.
              </h2>
              <p className="lede" style={{ marginTop: '1.6rem' }}>
                Of the {transit.examined} largest by customer cone,{' '}
                {transit.publishing === 0 ? 'none' : transit.publishing}{' '}
                {transit.publishing === 1 ? 'publishes' : 'publish'}. A record from a large
                transit network protects everything in its cone; one from the edge covers a
                single hop. Adoption is happening where it helps least.
              </p>
              <p style={{ marginTop: '1.4rem' }}>
                <Link
                  href="/region/"
                  data-cursor="link"
                  className="mono"
                  style={{
                    fontSize: '0.78rem',
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    borderBottom: '1px solid currentColor',
                  }}
                >
                  Follow the rail →
                </Link>
              </p>
            </Reveal>
          </div>
        </section>
      ) : null}

      {adoption?.by_day?.length ? (
        <section className="band">
          <div className="shell">
            <Reveal>
              <p className="eyebrow">Growth</p>
              <h2 className="display">
                From one record to <em>{thousands(peak)}</em>.
              </h2>
              <p className="meta" style={{ marginTop: '1rem' }}>
                {thousands(adoption.snapshots)} weekly snapshots, latest {adoption.latest_snapshot}
                . Every ASPA record published worldwide, from the first day any existed.
              </p>
            </Reveal>
            <Reveal delay={140}>
              <Growth points={adoption.by_day} />
            </Reveal>
          </div>
        </section>
      ) : null}

      {summary?.caveats?.length ? (
        <section className="band">
          <div className="shell">
            <Reveal>
              <div className="note">
                <strong>Limits that apply to every number on this site</strong>
                <ul>
                  {summary.caveats.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            </Reveal>
          </div>
        </section>
      ) : null}
    </>
  );
}

/** The growth curve, drawn as a single stroke. The paper figures come from `bgpshield report`. */
function Growth({ points }: { points: { snapshot_date: string; aspas: number }[] }) {
  const sorted = [...points].sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date));
  const max = Math.max(...sorted.map((p) => p.aspas), 1);
  const width = 1200;
  const height = 320;
  const line = sorted
    .map((p, i) => {
      const x = (i / Math.max(sorted.length - 1, 1)) * width;
      const y = height - (p.aspas / max) * height * 0.9;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <figure style={{ margin: '2.6rem 0 0' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="320"
        preserveAspectRatio="none"
        role="img"
        aria-label={`ASPA records published over time, rising to ${max.toLocaleString('en-US')}`}
        style={{ overflow: 'visible' }}
      >
        <line x1="0" y1={height} x2={width} y2={height} stroke="var(--ink)" strokeWidth="1" />
        <path
          d={line}
          fill="none"
          stroke="var(--route)"
          strokeWidth="3"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          className="growth-line"
        />
      </svg>
      <figcaption className="meta" style={{ marginTop: '0.8rem' }}>
        {sorted[0].snapshot_date} to {sorted[sorted.length - 1].snapshot_date}. The vertical
        axis starts at zero.
      </figcaption>
    </figure>
  );
}
