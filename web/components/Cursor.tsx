'use client';

import { useEffect, useRef } from 'react';

/**
 * A custom cursor: a dot that tracks the pointer and a ring that lags behind it.
 *
 * Elements opt in with `data-cursor="link"` (the ring grows) or `data-cursor="hop"` (the ring
 * grows further, turns green and shows a label). It renders nothing on touch devices and under
 * reduced motion, and it never affects what the page means: the dot is decoration on top of a
 * document that already works with the ordinary cursor.
 */
export default function Cursor() {
  const dot = useRef<HTMLDivElement>(null);
  const ring = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!fine || reduced || !dot.current || !ring.current) return;

    document.body.classList.add('has-cursor');
    let x = window.innerWidth / 2;
    let y = window.innerHeight / 2;
    let rx = x;
    let ry = y;
    let raf = 0;

    const move = (event: MouseEvent) => {
      x = event.clientX;
      y = event.clientY;
    };
    const tick = () => {
      rx += (x - rx) * 0.18;
      ry += (y - ry) * 0.18;
      dot.current!.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      ring.current!.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
      raf = requestAnimationFrame(tick);
    };

    const over = (event: MouseEvent) => {
      const target = (event.target as HTMLElement).closest<HTMLElement>('[data-cursor], a, button');
      const kind = target?.dataset.cursor ?? (target ? 'link' : '');
      document.body.classList.toggle('cursor-link', kind === 'link');
      document.body.classList.toggle('cursor-hop', kind === 'hop');
      ring.current!.dataset.label = target?.dataset.cursorLabel ?? '';
    };

    window.addEventListener('mousemove', move, { passive: true });
    document.addEventListener('mouseover', over);
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', move);
      document.removeEventListener('mouseover', over);
      document.body.classList.remove('has-cursor', 'cursor-link', 'cursor-hop');
    };
  }, []);

  return (
    <>
      <div ref={ring} className="cursor-ring" aria-hidden="true" />
      <div ref={dot} className="cursor" aria-hidden="true" />
    </>
  );
}
