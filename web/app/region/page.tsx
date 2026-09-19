import { RegionalPayload, percent, thousands } from '../../lib/data';
import { readExport } from '../../lib/load';

export default async function Region() {
  const payload = await readExport<RegionalPayload>('regional.json');

  if (!payload) {
    return (
      <p className="missing">
        No regional comparison has been exported yet. Run <code>hijax export</code> after
        ingesting routes and topology metadata.
      </p>
    );
  }

  const ranked = payload.largest_transit;
  const publishing = ranked.filter((row) => row.publishes_aspa);
  const firstPublisher = ranked.find((row) => row.publishes_aspa);
  const largest = ranked[0];

  return (
    <>
      <h2>{payload.country} and the APNIC region against the world</h2>
      <p className="meta">
        Snapshot {payload.snapshot_date}, topology data from {payload.metadata_month}.
      </p>

      <table>
        <thead>
          <tr>
            <th>Region</th>
            <th className="num">Routed networks</th>
            <th className="num">Publishing ASPA</th>
            <th className="num">Share</th>
          </tr>
        </thead>
        <tbody>
          {payload.regions.map((row) => (
            <tr key={row.region}>
              <td>{row.region}</td>
              <td className="num">{thousands(row.routed_networks)}</td>
              <td className="num">{thousands(row.publishers_that_route)}</td>
              <td className="num">{percent(row.share_of_routed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="meta">
        The denominator is networks seen <em>originating a route</em>. A network that announces
        nothing cannot meaningfully publish a record about its providers, and counting the tens
        of thousands of dormant allocations would deflate every share for no reason.
      </p>

      <h2>The finding that matters is not the share</h2>
      <p>
        Of the {ranked.length} largest networks registered in {payload.country} by customer
        cone, <strong>{publishing.length}</strong>{' '}
        {publishing.length === 1 ? 'publishes' : 'publish'} an ASPA record.
        {largest && firstPublisher ? (
          <>
            {' '}
            The largest one that does is <strong>AS{firstPublisher.asn}</strong>, with a customer
            cone of {thousands(firstPublisher.cone_size)} and a global rank of{' '}
            {thousands(firstPublisher.rank)} — while the largest network in the country,
            AS{largest.asn}, has a cone of {thousands(largest.cone_size)} and ranks{' '}
            {thousands(largest.rank)} in the world.
          </>
        ) : null}
      </p>
      <p>
        That is the opposite of the deployment order that would help. ASPA validation needs{' '}
        <em>adjacent</em> publishers to settle a hop, so a record published by a large transit
        network covers every hop into and out of it, and therefore protects everything behind
        it. A record published by a network at the edge covers one hop.
      </p>

      <table>
        <thead>
          <tr>
            <th className="num">#</th>
            <th>AS</th>
            <th className="num">Customer cone</th>
            <th className="num">Global rank</th>
            <th>Publishes ASPA</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((row, index) => (
            <tr key={row.asn}>
              <td className="num">{index + 1}</td>
              <td className="num">AS{row.asn}</td>
              <td className="num">{thousands(row.cone_size)}</td>
              <td className="num">{thousands(row.rank)}</td>
              <td>
                {row.publishes_aspa ? (
                  <span className="yes">yes</span>
                ) : (
                  <span className="no">no</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="caution">
        <strong>Two limits travel with every number on this page</strong>
        <ul>
          {payload.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </div>
    </>
  );
}
