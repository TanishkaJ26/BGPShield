import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';

export const metadata: Metadata = {
  title: 'Hijax — BGP route-security measurements',
  description:
    'Measurements of RPKI origin validation and ASPA adoption, their correctness, and what they would actually block.',
};

const pages = [
  { href: '/', label: 'Overview' },
  { href: '/networks/', label: 'Networks' },
  { href: '/incidents/', label: 'Incidents' },
  { href: '/region/', label: 'Region' },
  { href: '/methodology/', label: 'Methodology' },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <div className="shell">
            <h1>Hijax</h1>
            <p>
              A measurement study of RPKI origin validation and ASPA: how far they have spread,
              whether the published records are correct, and what they would actually have
              blocked.
            </p>
            <nav>
              <ul>
                {pages.map((page) => (
                  <li key={page.href}>
                    <Link href={page.href}>{page.label}</Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </header>
        <main className="shell">{children}</main>
      </body>
    </html>
  );
}
