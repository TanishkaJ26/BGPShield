'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

const PAGES = [
  { href: '/', label: 'Route' },
  { href: '/networks/', label: 'Networks' },
  { href: '/incidents/', label: 'Incidents' },
  { href: '/region/', label: 'Region' },
  { href: '/methodology/', label: 'Method' },
];

/**
 * The floating pill: wordmark, sections, and a chip naming the snapshot the site describes.
 *
 * A soft highlight slides between items — it follows the pointer while you hover and settles
 * back on the current page when you leave. Clicking a section drops an ink curtain over the
 * page, changes route behind it, and lifts it from the top. Plain links underneath, so with
 * no JavaScript, or under reduced motion, navigation is just navigation.
 */
export default function Nav({ snapshot }: { snapshot?: string | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const here = pathname.endsWith('/') ? pathname : `${pathname}/`;

  const list = useRef<HTMLUListElement>(null);
  const [glow, setGlow] = useState({ x: 0, w: 0, o: 0 });
  const [scrolled, setScrolled] = useState(false);
  const [phase, setPhase] = useState<'idle' | 'in' | 'out'>('idle');
  const pending = useRef<string | null>(null);

  const moveGlowTo = useCallback((el: HTMLElement | null) => {
    const ul = list.current;
    if (!el || !ul) {
      setGlow((g) => ({ ...g, o: 0 }));
      return;
    }
    const a = el.getBoundingClientRect();
    const b = ul.getBoundingClientRect();
    setGlow({ x: a.left - b.left + ul.scrollLeft, w: a.width, o: 1 });
  }, []);

  const settle = useCallback(() => {
    moveGlowTo(list.current?.querySelector<HTMLElement>('a[aria-current="page"]') ?? null);
  }, [moveGlowTo]);

  useEffect(() => {
    settle();
    window.addEventListener('resize', settle);
    return () => window.removeEventListener('resize', settle);
  }, [settle, here]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // The curtain came down for a navigation; the new route has rendered, so lift it.
  useEffect(() => {
    if (pending.current && here === pending.current) {
      pending.current = null;
      setPhase('out');
      const timer = window.setTimeout(() => setPhase('idle'), 650);
      return () => window.clearTimeout(timer);
    }
  }, [here]);

  const go = (href: string) => (event: React.MouseEvent<HTMLAnchorElement>) => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || event.metaKey || event.ctrlKey || event.shiftKey || here === href) return;
    event.preventDefault();
    pending.current = href;
    setPhase('in');
    window.setTimeout(() => router.push(href), 480);
  };

  return (
    <>
      <div className={`pill-nav ${scrolled ? 'scrolled' : ''}`}>
        <Link href="/" className="wordmark" data-cursor="link">
          <span className="dot" aria-hidden="true" />
          BGPShield
        </Link>
        <nav aria-label="Sections" onMouseLeave={settle}>
          <ul ref={list}>
            <li
              className="nav-glow"
              aria-hidden="true"
              style={
                {
                  '--x': `${glow.x}px`,
                  '--w': `${glow.w}px`,
                  '--o': glow.o,
                } as React.CSSProperties
              }
            />
            {PAGES.map((page) => (
              <li key={page.href}>
                <Link
                  href={page.href}
                  onClick={go(page.href)}
                  onMouseEnter={(event) => moveGlowTo(event.currentTarget)}
                  onFocus={(event) => moveGlowTo(event.currentTarget)}
                  aria-current={here === page.href ? 'page' : undefined}
                  data-cursor="link"
                >
                  {page.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {snapshot ? (
          <span className="nav-chip" title="The routing snapshot every number describes">
            {snapshot}
          </span>
        ) : null}
      </div>
      <div className={`curtain ${phase === 'idle' ? '' : phase}`} aria-hidden="true" />
    </>
  );
}
