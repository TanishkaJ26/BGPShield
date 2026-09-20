'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { repoUrl } from '../lib/site';

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
        <a
          className="nav-git"
          href={repoUrl}
          target="_blank"
          rel="noreferrer noopener"
          aria-label="Source code on GitHub"
          title="Every number here is reproducible from the source"
          data-cursor="link"
        >
          {/* The GitHub mark, inlined so the pill needs no network request and no icon
              dependency. It inherits `currentColor`, so it brightens with the same
              transition as the section links beside it.

              width and height are set as attributes as well as in CSS: an inline SVG has no
              intrinsic size, so if the stylesheet ever fails to load it would otherwise
              expand to fill the page. The CSS still wins when it is present. */}
          <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"
            />
          </svg>
        </a>
      </div>
      <div className={`curtain ${phase === 'idle' ? '' : phase}`} aria-hidden="true" />
    </>
  );
}
