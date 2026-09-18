/**
 * Static page. The full methodology lives in docs/methodology.md in the repository; this is
 * the short version a reader needs before trusting any number on the other pages.
 */
export default function Methodology() {
  return (
    <>
      <h2>How these numbers were produced</h2>
      <p>
        Everything here comes from passive, public data. This project never sends traffic to
        any network: it reads routing-table dumps that public collectors have already recorded,
        and RPKI snapshots that the RIRs already publish.
      </p>

      <h3>Where the data comes from</h3>
      <table>
        <tbody>
          <tr>
            <td>Routing tables</td>
            <td>
              MRT dumps from RouteViews and RIPE RIS, for collectors in Amsterdam, Oregon,
              Singapore, Tokyo and Sydney.
            </td>
          </tr>
          <tr>
            <td>RPKI</td>
            <td>
              Daily validator output archived by the RIPE NCC, covering all five trust anchors,
              weekly from 2023-10-11 — the first day any ASPA record existed.
            </td>
          </tr>
          <tr>
            <td>Topology</td>
            <td>
              CAIDA AS-relationships, AS Rank customer cones, and AS-to-organisation data. These
              are <strong>inferred</strong>, not ground truth.
            </td>
          </tr>
        </tbody>
      </table>

      <h3>Things that would mislead you if left unsaid</h3>
      <div className="caution">
        <ul>
          <li>
            <strong>Country means country of registration.</strong> It is where an AS number was
            registered, not where the network operates. Large operators register numbers in
            several countries.
          </li>
          <li>
            <strong>No collector is in India.</strong> The regional results are assembled from
            how Indian networks appear from outside, which is not the same as watching from
            inside the country.
          </li>
          <li>
            <strong>Relationships are inferred.</strong> Provider, customer and peer links come
            from CAIDA&rsquo;s inference over public data. When a published ASPA record
            disagrees with them, the record is not automatically the thing that is wrong — Phase
            4 found roughly one in five Invalid routes is better explained by an incomplete
            record.
          </li>
          <li>
            <strong>A counterfactual is not a prediction.</strong> &ldquo;ASPA would have
            blocked this&rdquo; is a statement about a hypothetical adoption pattern, not
            today&rsquo;s. Today only about 5% of routes contain two adjacent publishers.
          </li>
          <li>
            <strong>Leak detection is imprecise.</strong> Measured precision was 46%, dominated
            by networks whose inferred relationships mislabel ordinary transit as a leak.
          </li>
        </ul>
      </div>

      <h3>Path direction</h3>
      <p>
        AS paths arrive from a collector with the nearest network first. Everything in this
        project stores and reports them <strong>origin first</strong>, matching the way the ASPA
        draft indexes a path, so the origin is always element one.
      </p>

      <h3>Reproducing it</h3>
      <p>
        Clone the repository, run <code>make install</code>, then <code>make
        reproduce-small</code>. It ingests one RPKI snapshot, one month of topology data and one
        collector&rsquo;s routing table for a single date, validates and detects over them, and
        compares the counts against the fixtures committed in the repository. Archive files for
        a past date do not change, so the numbers should match exactly.
      </p>
      <p className="meta">
        Full details, including every decision and why it was made, are in{' '}
        <code>docs/methodology.md</code>, <code>docs/decisions.md</code> and{' '}
        <code>docs/data-sources.md</code>.
      </p>
    </>
  );
}
