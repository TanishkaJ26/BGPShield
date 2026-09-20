"""Serve the built dashboard with caching turned off.

Python's `http.server` sends no cache directives, so a browser is free to apply heuristic
caching and hold on to `index.html` between builds. That bites exactly when the site has just
been rebuilt: the stale HTML points at a stylesheet chunk whose content hash no longer exists,
the request 404s, and the page renders as raw unstyled markup. It looks like the build broke
when nothing is wrong at all.

This sends `no-store` on everything, so a reload always fetches the current build.

It also refuses to serve a build made for GitHub Pages. Pages serves a project site from
`/<repository name>`, so that build asks for `/BGPShield/_next/...`, which does not exist at
the root of a local server. The stylesheet 404s and the page renders as raw unstyled markup
with a page-high SVG, which looks like a catastrophe and is only a base path.
"""

from __future__ import annotations

import argparse
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "web" / "out"

#: The built page links its stylesheet with an absolute path. A local build starts it at
#: `/_next/`; a Pages build prefixes the repository name.
_STYLESHEET = re.compile(r'<link[^>]+href="(/[^"]*\.css)"')


def base_path_of(index_html: Path) -> str | None:
    """The base path a build was made for, or ``None`` for a root build.

    Returns the prefix in front of ``/_next/``, so a Pages build gives ``/BGPShield`` and a
    local one gives ``None``.
    """
    try:
        html = index_html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _STYLESHEET.search(html)
    if match is None:
        return None
    href = match.group(1)
    prefix, sep, _ = href.partition("/_next/")
    return prefix if sep and prefix else None


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        # One line per request is noise when the page pulls in fonts and chunks.
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not (SITE / "index.html").exists():
        print(f"no build at {SITE}\nrun:  bgpshield export  then  cd web && npm run build")
        sys.exit(1)

    # Serving a Pages build at the root gives a page with no stylesheet, which reads as a
    # broken site rather than a wrong build. Say which it is, and how to fix it, instead.
    base = base_path_of(SITE / "index.html")
    if base is not None:
        print(f"the build in {SITE} was made for GitHub Pages, under {base}/")
        print("served at the root its stylesheet would 404 and the page would look broken.")
        print("rebuild for local viewing:  cd web && npm run build")
        print(f"or browse the Pages build at http://localhost:{args.port}{base}/")
        sys.exit(1)

    handler = partial(NoCacheHandler, directory=str(SITE))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"BGPShield dashboard -> http://localhost:{args.port}")
    print("caching is disabled, so a plain reload always shows the current build")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.shutdown()


if __name__ == "__main__":
    main()
