'use client';

import { useEffect, useMemo, useState } from 'react';
import { NetworksPayload, NetworkRow, loadJson, thousands } from '../../lib/data';

const PAGE_SIZE = 100;

export default function Networks() {
  const [payload, setPayload] = useState<NetworksPayload | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState('');
  const [publishersOnly, setPublishersOnly] = useState(false);
  const [shown, setShown] = useState(PAGE_SIZE);

  useEffect(() => {
    loadJson<NetworksPayload>('networks.json').then((p) => {
      setPayload(p);
      setLoaded(true);
    });
  }, []);

  const matches = useMemo(() => {
    if (!payload) return [];
    const needle = query.trim().toLowerCase().replace(/^as/, '');
    return payload.rows.filter((row) => {
      if (publishersOnly && !row.publishes_aspa) return false;
      if (!needle) return true;
      return (
        String(row.asn).includes(needle) ||
        (row.country ?? '').toLowerCase().includes(needle) ||
        (row.rir ?? '').toLowerCase().includes(needle)
      );
    });
  }, [payload, query, publishersOnly]);

  if (!loaded) return <p className="meta">Loading measurements…</p>;
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

      <input
        type="search"
        placeholder="AS9498, IN, apnic…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setShown(PAGE_SIZE);
        }}
        aria-label="Search networks"
      />
      <p className="meta">
        <label>
          <input
            type="checkbox"
            checked={publishersOnly}
            onChange={(event) => setPublishersOnly(event.target.checked)}
          />{' '}
          only networks that publish an ASPA record
        </label>
        {' · '}
        {thousands(matches.length)} of {thousands(payload.rows.length)} shown
      </p>

      <div className="caution">
        <strong>This is not the whole routing table.</strong>
        {payload.selection} A network that is absent here is not necessarily absent from the
        internet.
      </div>

      <table>
        <thead>
          <tr>
            <th>AS</th>
            <th>Country</th>
            <th className="num">Cone</th>
            <th className="num">Rank</th>
            <th>ASPA</th>
            <th className="num">Valid</th>
            <th className="num">Invalid</th>
            <th className="num">Not found</th>
          </tr>
        </thead>
        <tbody>
          {matches.slice(0, shown).map((row) => (
            <Row key={row.asn} row={row} />
          ))}
        </tbody>
      </table>

      {shown < matches.length ? (
        <p style={{ marginTop: 16 }}>
          <button onClick={() => setShown((n) => n + PAGE_SIZE)}>
            Show {Math.min(PAGE_SIZE, matches.length - shown)} more
          </button>
        </p>
      ) : null}

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

function Row({ row }: { row: NetworkRow }) {
  return (
    <tr>
      <td className="num">AS{row.asn}</td>
      <td>{row.country ?? '—'}</td>
      <td className="num">{thousands(row.cone_size)}</td>
      <td className="num">{thousands(row.rank)}</td>
      <td>
        {row.publishes_aspa ? (
          <span className="yes">
            yes{row.providers_listed ? ` (${row.providers_listed})` : ''}
          </span>
        ) : (
          <span className="no">no</span>
        )}
      </td>
      <td className="num">{thousands(row.routes_valid)}</td>
      <td className="num">{thousands(row.routes_invalid)}</td>
      <td className="num">{thousands(row.routes_not_found)}</td>
    </tr>
  );
}
