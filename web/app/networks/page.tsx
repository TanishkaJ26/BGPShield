import { NetworksPayload } from '../../lib/data';
import { readExport } from '../../lib/load';
import NetworkSearch from './search';

/** How many rows are baked into the HTML so the page means something without JavaScript. */
const PRERENDERED = 100;

export default async function Networks() {
  const payload = await readExport<NetworksPayload>('networks.json');

  if (!payload) {
    return (
      <p className="missing">
        No network table has been exported yet. Run <code>hijax export</code> after validating a
        date.
      </p>
    );
  }

  return (
    <>
      <h2>Networks</h2>
      <p>
        Each network&rsquo;s origin-validation results and whether it publishes an ASPA record,
        for {payload.snapshot_date}. Search by AS number, country or registry.
      </p>

      <div className="caution">
        <strong>This is not the whole routing table.</strong>
        {payload.selection} A network that is absent here is not necessarily absent from the
        internet.
      </div>

      <NetworkSearch
        initialRows={payload.rows.slice(0, PRERENDERED)}
        total={payload.rows.length}
      />

      <div className="caution">
        <strong>Reading these columns</strong>
        <ul>
          {payload.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
          <li>
            <strong>Invalid</strong> does not mean an attack. Phase 4 found that roughly one in
            five Invalid routes is better explained by an incomplete published record than by
            anything wrong with the routing.
          </li>
        </ul>
      </div>
    </>
  );
}
