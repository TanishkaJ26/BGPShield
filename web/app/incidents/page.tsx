import type { Metadata } from 'next';
import Counter from '../../components/Counter';
import Kinetic from '../../components/Kinetic';
import Reveal from '../../components/Reveal';
import { thousands } from '../../lib/data';
import { readExport } from '../../lib/load';

export const metadata: Metadata = {
  title: 'Incidents',
  description: 'Seven documented routing incidents, and what a path-based leak detector could and could not judge about each.',
};

type IncidentRow = {
  id: string;
  kind: string;
  outcome: string;
  routes_examined: number;
  paths_with_culprit: number;
  candidates_found: number;
  culprit_flagged: number;
  note: string;
  description: string;
  culprit_asn: number | null;
  sources: string[];
};
type IncidentsPayload = {
  collectors: string[];
  summary: Record<string, number | null>;
  incidents: IncidentRow[];
  notes: string[];
};

/** Initialisms that appear in the curated ids and should not be title-cased. */
const UPPER = new Set(['dqe', 'rpki', 'bgp', 'dns', 'aws', 'isp']);

/** "2017-08-25-google-japan-leak" -> "Google Japan Leak". The curated entries carry a
 *  description rather than a title, and the date is shown separately. */
function nameFrom(id: string): string {
  return id
    .replace(/^\d{4}-\d{2}-\d{2}-/, '')
    .split('-')
    .map((word) =>
      UPPER.has(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)
    )
    .join(' ');
}

const OUTCOMES: Record<string, { label: string; tone: string; meaning: string }> = {
  detected: { label: 'detected', tone: 'detected', meaning: 'The detector named the culprit inside the incident window.' },
  missed: { label: 'missed', tone: 'missed', meaning: 'The leak was visible in the data and the detector did not find it.' },
  not_applicable: { label: 'not applicable', tone: 'other', meaning: 'Not a route leak, so a path-based detector could never have found it.' },
  not_visible: { label: 'not visible', tone: 'other', meaning: 'These collectors never saw this leak. That is a fact about where the vantage points are, not about the detector.' },
  culprit_absent: { label: 'culprit absent', tone: 'other', meaning: 'The culprit network never appeared at these collectors during the window.' },
  no_data: { label: 'no data', tone: 'other', meaning: 'The archive held nothing for that window.' },
};

export default async function Incidents() {
  const payload = await readExport<IncidentsPayload>('incidents.json');

  if (!payload) {
    return (
      <section className="band" style={{ paddingTop: 160 }}>
        <div className="shell">
          <p className="missing">
            No incident results have been exported yet. Run <code>bgpshield incidents</code> and then{' '}
            <code>bgpshield export</code>.
          </p>
        </div>
      </section>
    );
  }

  const s = payload.summary;

  return (
    <>
      <section className="hero" style={{ minHeight: '80svh' }}>
        <div className="shell">
          <p className="eyebrow">RQ3 · seven real incidents</p>
          <Kinetic
            as="h1"
            className="display"
            text="Most incidents cannot be judged at all."
            accent="judged"
            startDelay={120}
          />
          <div className="hero-foot">
            <p className="lede" style={{ margin: 0 }}>
              Each entry is a documented routing incident, every field taken from a primary
              post-mortem. The detector was pointed at the archive window for each one, from the{' '}
              {payload.collectors.join(' and ')} collector{payload.collectors.length === 1 ? '' : 's'}.
            </p>
          </div>
        </div>
      </section>

      <section className="band" style={{ paddingTop: 0 }}>
        <div className="shell">
          <Reveal>
            <div className="figure">
              <div>
                <div className="v"><Counter value={(s.curated_incidents as number) ?? 0} /></div>
                <div className="l">curated incidents</div>
              </div>
              <div>
                <div className="v gap"><Counter value={(s.judged as number) ?? 0} /></div>
                <div className="l">this detector could be judged on</div>
              </div>
              <div>
                <div className="v vouched">
                  <Counter value={(s.detected as number) ?? 0} /> / {thousands(s.judged as number)}
                </div>
                <div className="l">detected</div>
              </div>
            </div>
          </Reveal>
          <Reveal delay={120}>
            <div className="note">
              <strong>Two of two is a count, not a recall estimate.</strong>
              Of {thousands(s.curated_incidents as number)} well-documented incidents, only{' '}
              {thousands(s.judged as number)} could be judged: {thousands(s.not_applicable as number)}{' '}
              were not route leaks at all, and {thousands(s.not_visible as number)} were never
              visible from these vantage points. That ratio is itself the result.
            </div>
          </Reveal>
        </div>
      </section>

      <section className="band">
        <div className="shell">
          <div className="tl">
            {payload.incidents.map((incident, index) => {
              const outcome = OUTCOMES[incident.outcome] ?? { label: incident.outcome, tone: 'other', meaning: '' };
              const date = incident.id.slice(0, 10);
              return (
                <Reveal key={incident.id} delay={index * 50}>
                  <article className="tl-row" data-cursor="link">
                    <div className="tl-date">{date}</div>
                    <div>
                      <h3 className="tl-title">{nameFrom(incident.id)}</h3>
                      <div className="tl-body">
                        <span className="mono" style={{ fontSize: '0.74rem', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>
                          {incident.kind.replace(/_/g, ' ')}
                          {incident.culprit_asn ? ` · AS${incident.culprit_asn}` : ''}
                        </span>
                        {incident.description ? (
                          <p style={{ margin: '0.5rem 0 0' }}>{incident.description}</p>
                        ) : null}
                        <p className="meta" style={{ margin: '0.5rem 0 0' }}>{outcome.meaning}</p>
                        {incident.routes_examined ? (
                          <dl className="tl-kv">
                            <div><b>{thousands(incident.routes_examined)}</b> announcements examined</div>
                            <div><b>{thousands(incident.paths_with_culprit)}</b> distinct paths with the culprit</div>
                            <div><b>{thousands(incident.candidates_found)}</b> leak sightings on them</div>
                            <div><b>{thousands(incident.culprit_flagged)}</b> naming an expected culprit</div>
                          </dl>
                        ) : null}
                        {incident.note ? <p className="meta" style={{ marginTop: '0.6rem' }}>{incident.note}</p> : null}
                        {incident.sources?.length ? (
                          <p className="mono" style={{ margin: '0.7rem 0 0', display: 'flex', flexWrap: 'wrap', gap: '0.9rem' }}>
                            {incident.sources.map((href, n) => (
                              <a
                                key={href}
                                href={href}
                                rel="noreferrer noopener"
                                target="_blank"
                                style={{ fontSize: '0.7rem', letterSpacing: '0.14em', textTransform: 'uppercase', borderBottom: '1px solid currentColor' }}
                              >
                                source {incident.sources.length > 1 ? n + 1 : ''} ↗
                              </a>
                            ))}
                          </p>
                        ) : null}
                      </div>
                    </div>
                    <span className={`verdict v-${outcome.tone}`}>{outcome.label}</span>
                  </article>
                </Reveal>
              );
            })}
          </div>

          <Reveal>
            <div className="note">
              <strong>How to read these outcomes</strong>
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
