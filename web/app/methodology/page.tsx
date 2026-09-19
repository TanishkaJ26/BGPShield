import type { Metadata } from 'next';
import Kinetic from '../../components/Kinetic';
import Reveal from '../../components/Reveal';

export const metadata: Metadata = {
  title: 'Method',
  description: 'Data sources, limits and the reproduction command behind every number on this site.',
};

const SOURCES: [string, string][] = [
  ['Routing tables', 'MRT dumps from RouteViews and RIPE RIS, for collectors in Amsterdam, Oregon, Singapore, Tokyo and Sydney.'],
  ['RPKI', 'Daily validator output archived by the RIPE NCC, all five trust anchors, weekly from 2023-10-11 — the first day any ASPA record existed.'],
  ['Topology', 'CAIDA AS-relationships, AS Rank customer cones, and AS-to-organisation data. These are inferred, not ground truth.'],
];

const LIMITS: [string, string][] = [
  ['Country means country of registration', 'It is where an AS number was registered, not where the network operates. Large operators register numbers in several countries.'],
  ['No collector is in India', 'The regional results are assembled from how Indian networks appear from outside, which is not the same as watching from inside the country.'],
  ['Relationships are inferred', 'Provider, customer and peer links come from CAIDA’s inference over public data. When a published ASPA record disagrees with them, the record is not automatically the thing that is wrong.'],
  ['A counterfactual is not a prediction', '“ASPA would have blocked this” is a statement about a hypothetical adoption pattern, not today’s. Today only about 5% of routes contain two adjacent publishers.'],
  ['Leak detection is imprecise', 'Measured precision was 46%, dominated by networks whose inferred relationships mislabel ordinary transit as a leak.'],
];

export default function Methodology() {
  return (
    <>
      <section className="hero" style={{ minHeight: '70svh' }}>
        <div className="shell">
          <p className="eyebrow">Method</p>
          <Kinetic as="h1" className="display" text="The caveats are the method." accent="caveats" startDelay={120} />
          <div className="hero-foot">
            <p className="lede" style={{ margin: 0 }}>
              Everything here comes from public data that was already recorded. This project never
              sends traffic to any network.
            </p>
          </div>
        </div>
      </section>

      <section className="band" style={{ paddingTop: 0 }}>
        <div className="shell">
          <Reveal>
            <div className="table-wrap">
              <table>
                <tbody>
                  {SOURCES.map(([name, detail]) => (
                    <tr key={name}>
                      <td className="asn" style={{ width: '11rem', verticalAlign: 'top' }}>{name}</td>
                      <td>{detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="band">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">Things that would mislead you if left unsaid</p>
          </Reveal>
          {LIMITS.map(([title, detail], index) => (
            <Reveal key={title} delay={index * 60}>
              <div className="note" style={{ margin: '1.4rem 0' }}>
                <strong>{title}</strong>
                {detail}
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="band">
        <div className="shell">
          <Reveal>
            <p className="eyebrow">Path direction</p>
            <p>
              AS paths arrive from a collector with the nearest network first. Everything in this
              project stores and reports them <strong>origin first</strong>, matching the way the
              ASPA draft indexes a path, so the origin is always element one.
            </p>
          </Reveal>
          <Reveal delay={100}>
            <p className="eyebrow" style={{ marginTop: '2.6rem' }}>Reproducing it</p>
            <p>
              Clone the repository, activate the environment, then run <code>bgpshield reproduce</code>.
              It ingests one RPKI snapshot, one month of topology data and one collector’s routing
              table for a single date, validates and detects over them, and compares twelve counts
              and five normalization drop rates against fixtures committed in the repository.
              Archive files for a past date do not change, so the numbers should match exactly.
            </p>
            <p className="meta" style={{ marginTop: '1rem' }}>
              Full details are in <code>docs/methodology.md</code>, <code>docs/decisions.md</code>{' '}
              and <code>docs/data-sources.md</code>.
            </p>
          </Reveal>
        </div>
      </section>
    </>
  );
}
