'use client';

import { useEffect, useState } from 'react';
import { loadJson, thousands } from '../../lib/data';

type IncidentRow = {
  id: string;
  kind: string;
  outcome: string;
  routes_examined: number;
  paths_with_culprit: number;
  candidates_found: number;
  culprit_flagged: number;
  note: string;
  title: string;
  culprit_asn: number | null;
  source: string;
};

type IncidentsPayload = {
  collectors: string[];
  summary: Record<string, number | null>;
  incidents: IncidentRow[];
  notes: string[];
};

/** What each outcome means, in words rather than a status code. */
const OUTCOMES: Record<string, { label: string; tone: string; meaning: string }> = {
  detected: {
    label: 'detected',
    tone: 'yes',
    meaning: 'The detector named the culprit in the incident window.',
  },
  missed: {
    label: 'missed',
    tone: 'no',
    meaning: 'The leak was visible in the data and the detector did not find it.',
  },
  not_applicable: {
    label: 'not applicable',
    tone: '',
    meaning: 'Not a route leak, so a path-based detector could never have found it.',
  },
  not_visible: {
    label: 'not visible',
    tone: '',
    meaning: 'The collectors used never saw this leak. That is about vantage points, not the detector.',
  },
  culprit_absent: {
    label: 'culprit absent',
    tone: '',
    meaning: 'The culprit network never appeared at these collectors during the window.',
  },
  no_data: {
    label: 'no data',
    tone: '',
    meaning: 'The archive had nothing for that window.',
  },
};

export default function Incidents() {
  const [payload, setPayload] = useState<IncidentsPayload | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    loadJson<IncidentsPayload>('incidents.json').then((p) => {
      setPayload(p);
      setLoaded(true);
    });
  }, []);

  if (!loaded) return <p className="meta">Loading measurements…</p>;
  if (!payload) {
    return (
      <p className="missing">
        No incident results have been exported yet. Run <code>hijax incidents</code> and then{' '}
        <code>hijax export</code>.
      </p>
    );
  }

  const s = payload.summary;

  return (
    <>
      <h2>Real incidents, and whether the detector found them</h2>
      <p>
        Each entry is a documented routing incident, with every field taken from a primary
        post-mortem. The detector was pointed at the archive window for each one, using the{' '}
        {payload.collectors.join(' and ')} collector
        {payload.collectors.length === 1 ? '' : 's'}.
      </p>

      <div className="headline">
        <div className="stat">
          <div className="value">{thousands(s.curated_incidents as number)}</div>
          <div className="label">curated incidents</div>
        </div>
        <div className="stat">
          <div className="value">{thousands(s.judged as number)}</div>
          <div className="label">that this detector could be judged on</div>
        </div>
        <div className="stat">
          <div className="value">
            {thousands(s.detected as number)} / {thousands(s.judged as number)}
          </div>
          <div className="label">detected</div>
        </div>
      </div>

      <div className="caution">
        <strong>Two of two is a count, not a recall estimate.</strong>
        Of {thousands(s.curated_incidents as number)} well-documented incidents, only{' '}
        {thousands(s.judged as number)} could be judged: {thousands(s.not_applicable as number)}{' '}
        were not route leaks at all, and {thousands(s.not_visible as number)} were never visible
        from these vantage points. The detector found both leaks it was in a position to see.
        That ratio is itself the result — most publicly documented BGP incidents are either not
        route leaks, or invisible from any given vantage point.
      </div>

      {payload.incidents.map((incident) => {
        const outcome = OUTCOMES[incident.outcome] ?? {
          label: incident.outcome,
          tone: '',
          meaning: '',
        };
        return (
          <section key={incident.id} style={{ marginTop: 28 }}>
            <h3>
              {incident.title || incident.id}{' '}
              <span className={outcome.tone}>— {outcome.label}</span>
            </h3>
            <p className="meta">
              {incident.kind.replace(/_/g, ' ')}
              {incident.culprit_asn ? ` · AS${incident.culprit_asn}` : ''}
              {incident.source ? (
                <>
                  {' · '}
                  <a href={incident.source} rel="noreferrer noopener" target="_blank">
                    source
                  </a>
                </>
              ) : null}
            </p>
            <p>{outcome.meaning}</p>
            {incident.routes_examined ? (
              <table>
                <tbody>
                  <tr>
                    <td>Announcements examined</td>
                    <td className="num">{thousands(incident.routes_examined)}</td>
                  </tr>
                  <tr>
                    <td>Distinct paths containing the culprit</td>
                    <td className="num">{thousands(incident.paths_with_culprit)}</td>
                  </tr>
                  <tr>
                    <td>Leak sightings on those paths</td>
                    <td className="num">{thousands(incident.candidates_found)}</td>
                  </tr>
                  <tr>
                    <td>Sightings naming an expected culprit</td>
                    <td className="num">{thousands(incident.culprit_flagged)}</td>
                  </tr>
                </tbody>
              </table>
            ) : null}
            {incident.note ? <p className="meta">{incident.note}</p> : null}
          </section>
        );
      })}

      <div className="caution">
        <strong>How to read these outcomes</strong>
        <ul>
          {payload.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </div>
    </>
  );
}
