'use client';

import { useEffect, useRef } from 'react';

/**
 * Reveals its children once, when they first scroll into view.
 *
 * The content is rendered server-side and is already in the HTML; this only adds the
 * transition. Under `prefers-reduced-motion` the CSS shows everything immediately, and with
 * no JavaScript at all a fallback in `<noscript>` does the same, so the page never depends on
 * this to be readable.
 */
export default function Reveal({
  children,
  delay = 0,
  as: Tag = 'div',
}: {
  children: React.ReactNode;
  delay?: number;
  as?: 'div' | 'section' | 'li' | 'tr';
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.classList.add('shown');
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('shown');
          observer.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: '0px 0px -8% 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const Element = Tag as React.ElementType;
  return (
    <Element
      ref={ref}
      data-reveal=""
      style={{ '--reveal-delay': `${delay}ms` } as React.CSSProperties}
    >
      {children}
    </Element>
  );
}
