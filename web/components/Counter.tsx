'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * A number that scrambles through digits and settles on its value when scrolled into view.
 *
 * The true value is in the HTML from the first render, and the animation only ever replaces
 * it while visibly in motion, so the page never shows a wrong number standing still.
 */
export default function Counter({
  value,
  decimals = 0,
  suffix = '',
  duration = 1300,
}: {
  value: number;
  decimals?: number;
  suffix?: string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState<string | null>(null);

  const format = useCallback(
    (n: number) =>
      n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
    [decimals]
  );

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        const started = performance.now();
        const tick = (now: number) => {
          const p = Math.min((now - started) / duration, 1);
          const eased = 1 - Math.pow(1 - p, 4);
          // Early on, most digits are noise; they settle from the left as progress rises.
          const target = format(value * eased);
          const noisy = target
            .split('')
            .map((ch, i) =>
              /\d/.test(ch) && Math.random() > eased + i / (target.length * 2)
                ? String(Math.floor(Math.random() * 10))
                : ch
            )
            .join('');
          setShown(p < 1 ? noisy : null);
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      },
      { threshold: 0.5 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [value, duration, format]);

  return (
    <span ref={ref} className="mono-num">
      {shown ?? format(value)}
      {suffix}
    </span>
  );
}
