import { AdoptionPayload, SummaryPayload, percent, thousands } from '../lib/data';
import { readExport } from '../lib/load';

/** Labels for the path-coverage positions, in the order that tells the story. */
const COVERAGE_ORDER: [string, string][] = [
  ['any', 'A publisher anywhere on the path'],
  ['transit', 'A publisher somewhere in transit'],
  ['neighbour', "The collector's own peer publishes"],
  ['origin', 'The origin publishes'],
  ['adjacent_pair', 'Two publishers next to each other'],
  ['all_hops', 'Every hop covered'],
];

export default async function Overview() {
  const summary = await readExport<SummaryPayload>('summary.json');
  const adoption = await readExport<AdoptionPayload>('aspa_adoption.json');

  const global = summary?.adoption?.['global'];
  const coverage = summary?.path_coverage;
  const transit = summary?.largest_transit_publishing;

  return (
    <>
      <h2>What this measures</h2>
      <p>
        Two mechanisms are meant to make BGP routing harder to abuse. <strong>RPKI origin
        validation</strong> checks that the network announcing a block of addresses is allowed
        to. <strong>ASPA</strong> goes further and checks that the path a route travelled makes
        sense, by having each network publish who its providers are. This site reports how far
        each has actually spread, whether what has been published is correct, and what it would
        have blocked.
      </p>

      {global ? (
        <div className="headline">
          <div className="stat">
            <div className="value">{percent(global.share_of_routed)}</div>
            <div className="label">
              of routed networks publish an ASPA record ({thousands(global.publishers)} of{' '}
              {thousands(global.routed_networks)})
            </div>
          </div>
          {coverage ? (
            <>
              <div className="stat">
                <div className="value">{percent(coverage['any'], 1)}</div>
                <div className="label">of routes touch a publisher somewhere</div>
              </div>
              <div className="stat">
                <div className="value">{percent(coverage['adjacent_pair'], 1)}</div>
                <div className="label">
                  contain two <em>adjacent</em> publishers — the first point at which ASPA can
                  judge a hop
                </div>
              </div>
            </>
          ) : null}
        </div>
      ) : (
        <p className="missing">
          No summary has been exported yet. Run <code>hijax export</code> after ingesting and
          validating a date.
        </p>
      )}

      <div className="caution">
        <strong>The two numbers above must be read together.</strong>
        An ASPA record can only settle a hop when the networks on <em>both</em> sides of it
        publish. So &ldquo;touches a publisher&rdquo; counts routes where the mechanism is
        present but usually cannot yet reach a verdict, and quoting it alone overstates what is
        deployable today by roughly seven times.
      </div>

      {coverage ? (
        <>
          <h2>What adoption actually buys</h2>
          <table>
            <thead>
              <tr>
                <th>Where the publishers sit</th>
                <th className="num">Share of routes</th>
                <th style={{ width: '38%' }} />
              </tr>
            </thead>
            <tbody>
              {COVERAGE_ORDER.filter(([key]) => key in coverage).map(([key, label]) => (
                <tr key={key}>
                  <td>{label}</td>
                  <td className="num">{percent(coverage[key], 2)}</td>
                  <td>
                    <div
                      className="bar"
                      style={{
                        width: `${Math.max(coverage[key] * 100 * 2, 0.4)}%`,
                        opacity: key === 'adjacent_pair' || key === 'all_hops' ? 1 : 0.45,
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="meta">
            The gap between the first row and the fifth is the whole story of partial
            deployment: adoption is scattered, and scattered adoption composes badly, because
            value appears only where two publishers happen to land next to each other.
          </p>
        </>
      ) : null}

      {transit ? (
        <>
          <h2>Where adoption is missing most</h2>
          <p>
            Of the {transit.examined} largest transit networks registered in {transit.country} by
            customer cone, <strong>{transit.publishing}</strong>{' '}
            {transit.publishing === 1 ? 'publishes' : 'publish'} an ASPA record. A record from a
            large transit network covers every hop into and out of it, and so protects everything
            in its customer cone; a record from a network at the edge covers one hop. See the{' '}
            <a href="region/">Region</a> page.
          </p>
        </>
      ) : null}

      {adoption?.by_day?.length ? (
        <>
          <h2>Adoption over time</h2>
          <p className="meta">
            {thousands(adoption.snapshots)} snapshots, latest {adoption.latest_snapshot}. ASPA
            records published worldwide, from the first day the data exists.
          </p>
          <Sparkline points={adoption.by_day} />
        </>
      ) : null}

      {summary?.caveats?.length ? (
        <div className="caution">
          <strong>Limits that apply to every number on this site</strong>
          <ul>
            {summary.caveats.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

/** A plain inline chart. The figures in the paper are generated separately by `hijax report`. */
function Sparkline({ points }: { points: { snapshot_date: string; aspas: number }[] }) {
  const sorted = [...points].sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date));
  const max = Math.max(...sorted.map((p) => p.aspas), 1);
  const width = 720;
  const height = 180;
  const path = sorted
    .map((p, i) => {
      const x = (i / Math.max(sorted.length - 1, 1)) * width;
      const y = height - (p.aspas / max) * height;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <figure style={{ margin: '12px 0' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height="180"
        role="img"
        aria-label={`ASPA records published over time, rising to ${max.toLocaleString('en-US')}`}
      >
        <path d={path} fill="none" stroke="var(--primary)" strokeWidth="2" />
      </svg>
      <figcaption className="meta">
        {sorted[0].snapshot_date} to {sorted[sorted.length - 1].snapshot_date}. Peak{' '}
        {max.toLocaleString('en-US')} records. The vertical axis starts at zero.
      </figcaption>
    </figure>
  );
}
