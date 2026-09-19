'use client';

import { useEffect, useRef } from 'react';

/**
 * Splits a headline into words and lets each one rise into place, staggered.
 *
 * The words are real text in the HTML from the start — this only wraps them so the CSS can
 * move them. Under reduced motion the CSS leaves them where they are.
 */
export default function Kinetic({
  text,
  accent,
  as: Tag = 'h1',
  className = '',
  startDelay = 0,
}: {
  text: string;
  /** A word (or phrase) inside `text` to render in the accent colour. */
  accent?: string;
  as?: 'h1' | 'h2' | 'h3' | 'p';
  className?: string;
  startDelay?: number;
}) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const timer = window.setTimeout(() => el.classList.add('on'), startDelay);
    return () => window.clearTimeout(timer);
  }, [startDelay]);

  const words = text.split(' ');
  const accentWords = new Set(accent ? accent.split(' ') : []);
  const Element = Tag as React.ElementType;

  return (
    <Element ref={ref} className={`kinetic ${className}`.trim()}>
      {words.map((word, index) => (
        <span className="w" key={`${word}-${index}`}>
          <span style={{ '--i': index } as React.CSSProperties}>
            {accentWords.has(word.replace(/[.,]/g, '')) ? <em>{word}</em> : word}
          </span>
          {index < words.length - 1 ? ' ' : ''}
        </span>
      ))}
    </Element>
  );
}
