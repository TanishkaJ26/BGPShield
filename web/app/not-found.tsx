import Link from 'next/link';

/**
 * The 404 page. Next writes it to `out/404.html`, which GitHub Pages serves for any path it
 * has no file for, so a mistyped or outdated link lands here rather than on the host's page.
 */
export default function NotFound() {
  return (
    <section className="band" style={{ paddingTop: 160, minHeight: '70svh' }}>
      <div className="shell">
        <p className="eyebrow">404</p>
        <h1 className="display" style={{ maxWidth: '14ch' }}>
          No route to <em>this</em> page.
        </h1>
        <p className="lede" style={{ marginTop: '1.4rem' }}>
          Nothing is published at this address. The measurements live on the pages below.
        </p>
        <p style={{ marginTop: '1.6rem' }}>
          <Link
            href="/"
            data-cursor="link"
            className="mono"
            style={{
              fontSize: '0.78rem',
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              borderBottom: '1px solid currentColor',
            }}
          >
            Back to the route →
          </Link>
        </p>
      </div>
    </section>
  );
}
