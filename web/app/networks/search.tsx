'use client';

import { useCallback, useMemo, useState } from 'react';
import { NetworkRow, basePath, thousands } from '../../lib/data';

const PAGE_SIZE = 100;

/**
 * The searchable table.
 *
 * The page around this is rendered at build time, and the first {@link PAGE_SIZE} rows come in
 * as props, so the built HTML holds real measurements and works with no JavaScript at all. The
 * full table is about a megabyte, which is not worth inlining into every page load, so it is
 * fetched once and only when somebody actually searches.
 */
export default function NetworkSearch({
  initialRows,
  total,
}: {
  initialRows: NetworkRow[];
  total: number;
}) {
  const [query, setQuery] = useState('');
  const [publishersOnly, setPublishersOnly] = useState(false);
  const [allRows, setAllRows] = useState<NetworkRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [shown, setShown] = useState(PAGE_SIZE);

  const ensureLoaded = useCallback(async () => {
    if (allRows || loading) return;
    setLoading(true);
    try {
      const response = await fetch(`${basePath}/data/networks.json`);
      if (!response.ok) throw new Error(String(response.status));
      const payload = (await response.json()) as { rows: NetworkRow[] };
      setAllRows(payload.rows);
    } catch {
      // Say so rather than quietly filtering the first hundred rows and presenting that as
      // the whole answer.
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [allRows, loading]);

  const source = allRows ?? initialRows;
  const searching = query.trim() !== '' || publishersOnly;

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase().replace(/^as/, '');
    return source.filter((row) => {
      if (publishersOnly && !row.publishes_aspa) return false;
      if (!needle) return true;
      return (
        String(row.asn).includes(needle) ||
        (row.country ?? '').toLowerCase().includes(needle) ||
        (row.rir ?? '').toLowerCase().includes(needle)
      );
    });
  }, [source, query, publishersOnly]);

  return (
    <>
      <input
        type="search"
        placeholder="AS9498, IN, apnic…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setShown(PAGE_SIZE);
          void ensureLoaded();
        }}
        aria-label="Search networks"
      />
      <p className="meta">
        <label>
          <input
            type="checkbox"
            checked={publishersOnly}
            onChange={(event) => {
              setPublishersOnly(event.target.checked);
              setShown(PAGE_SIZE);
              void ensureLoaded();
            }}
          />{' '}
          only networks that publish an ASPA record
        </label>
        {' · '}
        {loading
          ? 'loading the full table…'
          : searching
            ? `${thousands(matches.length)} matching`
            : `showing the largest ${thousands(Math.min(shown, matches.length))} of ${thousands(total)}`}
      </p>

      {failed ? (
        <p className="missing">
          The full table could not be loaded, so only the networks already on this page are
          being searched.
        </p>
      ) : null}

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
            <tr key={row.asn}>
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
    </>
  );
}
