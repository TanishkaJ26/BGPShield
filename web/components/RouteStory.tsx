'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * The signature section: one BGP route, followed hop by hop as the reader scrolls.
 *
 * The section is tall and its stage is sticky, so scrolling through it does not move the
 * page — it moves the *route*. A dotted base path runs origin → transit → transit →
 * collector; a blue line draws along it with scroll; nodes light as it reaches them. At each
 * hop the number changes to the real measurement for that position. Then the one hop with
 * publishers on both sides turns green — and finally the whole path does, at the rate that
 * actually happens.
 *
 * Every step's text is in the HTML. Under reduced motion the steps stack as plain sections.
 */
type Step = {
  key: string;
  num: string;
  label: string;
  caption: string;
  tone: '' | 'vouched' | 'gap';
  litUpTo: number; // nodes lit, 0..4
  vouchSegment: boolean;
  vouchAll: boolean;
};

const NODES = [
  { x: 60, label: 'origin' },
  { x: 380, label: 'transit' },
  { x: 700, label: 'transit' },
  { x: 1020, label: 'collector' },
];
const PATH = 'M60,150 C180,40 260,260 380,150 S600,40 700,150 S920,260 1020,150';
const PATH_LENGTH = 1130; // measured once at mount and corrected

export default function RouteStory({ shares }: { shares: Record<string, number> }) {
  const pct = (key: string, digits = 1) => `${((shares[key] ?? 0) * 100).toFixed(digits)}%`;

  const steps: Step[] = [
    {
      key: 'any',
      num: pct('any'),
      label: 'A route leaves its origin.',
      caption:
        'of routes touch an ASPA publisher somewhere along the way. That is the number most often quoted, and it is the least useful one here.',
      tone: '',
      litUpTo: 1,
      vouchSegment: false,
      vouchAll: false,
    },
    {
      key: 'transit',
      num: pct('transit'),
      label: 'It crosses transit networks.',
      caption:
        'have a publisher somewhere in transit. Presence, still — a record on one side of a hop settles nothing about that hop.',
      tone: '',
      litUpTo: 3,
      vouchSegment: false,
      vouchAll: false,
    },
    {
      key: 'adjacent_pair',
      num: pct('adjacent_pair'),
      label: 'Two neighbours both vouch.',
      caption:
        'of routes contain a hop where the networks on both sides publish. This is the first point at which ASPA can actually judge anything.',
      tone: 'vouched',
      litUpTo: 4,
      vouchSegment: true,
      vouchAll: false,
    },
    {
      key: 'all_hops',
      num: pct('all_hops', 2),
      label: 'Every hop, end to end.',
      caption:
        'of routes are covered the whole way. That is the internet as ASPA was designed to see it, and it is almost nowhere yet.',
      tone: 'gap',
      litUpTo: 4,
      vouchSegment: true,
      vouchAll: true,
    },
  ];

  const section = useRef<HTMLElement>(null);
  const drawn = useRef<SVGPathElement>(null);
  const [progress, setProgress] = useState(0);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const el = section.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setReduced(true);
      setProgress(1);
      return;
    }
    if (drawn.current) {
      const real = drawn.current.getTotalLength();
      drawn.current.style.strokeDasharray = `${real}`;
      drawn.current.dataset.len = String(real);
    }
    let raf = 0;
    const update = () => {
      const rect = el.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      const p = Math.min(Math.max(-rect.top / Math.max(total, 1), 0), 1);
      setProgress(p);
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

  // Which step is showing, and how far the line has drawn. The line reaches the last node a
  // little before the last step so the "end to end" moment lands on a finished route.
  const stepIndex = Math.min(Math.floor(progress * steps.length), steps.length - 1);
  const current = steps[stepIndex];
  const drawProgress = Math.min(progress / 0.72, 1);
  const length = Number(drawn.current?.dataset.len ?? PATH_LENGTH);

  return (
    <section className="story" ref={section} aria-label="One route, hop by hop">
      <div className="story-stage">
        <div className="shell story-head">
          <p className="eyebrow">Follow one route</p>
        </div>

        <div className="shell" style={{ display: 'grid', alignContent: 'center', gap: '2rem' }}>
          <div className="story-copy">
            {steps.map((step, index) => (
              <div
                key={step.key}
                className={`story-step ${step.tone} ${reduced || index === stepIndex ? 'on' : ''}`}
                aria-hidden={!reduced && index !== stepIndex}
              >
                <div className="story-num">{step.num}</div>
                <p className="story-cap">
                  <strong>{step.label}</strong> {step.caption}
                </p>
              </div>
            ))}
          </div>

          <svg className="story-svg" viewBox="0 0 1080 300" preserveAspectRatio="xMidYMid meet">
            <path className="base" d={PATH} />
            <path
              className="drawn"
              ref={drawn}
              d={PATH}
              style={{
                strokeDasharray: length,
                strokeDashoffset: length * (1 - drawProgress),
              }}
            />
            {/* The one hop both sides vouch for, then the whole route. */}
            <path
              className={`vouch ${current.vouchSegment && !current.vouchAll ? 'on' : ''}`}
              d="M380,150 S600,40 700,150"
            />
            <path className={`vouch ${current.vouchAll ? 'on' : ''}`} d={PATH} />
            {NODES.map((node, index) => {
              const lit = index < current.litUpTo && drawProgress >= index / 3 - 0.02;
              const vouched =
                current.vouchAll ||
                (current.vouchSegment && (index === 1 || index === 2));
              return (
                <g
                  key={node.label + index}
                  data-cursor="hop"
                  data-cursor-label={vouched ? 'vouched' : lit ? 'seen' : 'unverified'}
                >
                  <circle
                    className={`node-halo ${vouched ? 'on' : ''}`}
                    cx={node.x}
                    cy="150"
                    r="12"
                  />
                  <circle
                    className={`node ${vouched ? 'vouched' : lit ? 'lit' : ''}`}
                    cx={node.x}
                    cy="150"
                    r="9"
                  />
                  <text className="node-label" x={node.x} y="200" textAnchor="middle">
                    {node.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="shell story-progress" aria-hidden="true">
          {steps.map((step, index) => {
            const local = Math.min(Math.max(progress * steps.length - index, 0), 1);
            return <i key={step.key} style={{ '--p': local } as React.CSSProperties} />;
          })}
        </div>
      </div>
    </section>
  );
}
