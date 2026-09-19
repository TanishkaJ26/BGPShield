'use client';

import { useEffect, useRef, useState } from 'react';
import { TransitRow, thousands } from '../lib/data';

/**
 * A horizontal rail driven by vertical scroll: the largest networks in a country, as cards
 * that slide past while the page holds still. The one that publishes is green.
 *
 * Cards are ordinary flex items in the HTML; this only translates the track. Under reduced
 * motion the track scrolls sideways by hand.
 */
export default function Rail({
  rows,
  country,
  children,
}: {
  rows: TransitRow[];
  country: string;
  children?: React.ReactNode;
}) {
  const section = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [shift, setShift] = useState(0);

  useEffect(() => {
    const el = section.current;
    const t = track.current;
    if (!el || !t) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    let raf = 0;
    const update = () => {
      const rect = el.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      const p = Math.min(Math.max(-rect.top / Math.max(total, 1), 0), 1);
      const max = Math.max(t.scrollWidth - window.innerWidth, 0);
      setShift(-p * max);
      raf = 0;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const peak = Math.max(...rows.map((row) => row.cone_size), 1);

  return (
    <section className="rail" ref={section} aria-label={`Largest networks registered in ${country}`}>
      <div className="rail-stage">
        <div className="shell">{children}</div>
        <div className="rail-track" ref={track} style={{ transform: `translate3d(${shift}px,0,0)` }}>
          {rows.map((row, index) => (
            <article
              key={row.asn}
              className={`card ${row.publishes_aspa ? 'vouched' : ''}`}
              data-cursor="link"
            >
              <div className="rank">
                #{index + 1} in {country} · global #{thousands(row.rank)}
              </div>
              <div>
                <div className="asn">AS{row.asn}</div>
                <div className="cone">customer cone {thousands(row.cone_size)}</div>
              </div>
              <span className="badge">{row.publishes_aspa ? 'publishes ASPA' : 'no record'}</span>
              <div className="bar" aria-hidden="true">
                <i style={{ '--w': `${Math.max((row.cone_size / peak) * 100, 1)}%` } as React.CSSProperties} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
