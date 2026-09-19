"""Serve the built dashboard with caching turned off.

Python's `http.server` sends no cache directives, so a browser is free to apply heuristic
caching and hold on to `index.html` between builds. That bites exactly when the site has just
been rebuilt: the stale HTML points at a stylesheet chunk whose content hash no longer exists,
the request 404s, and the page renders as raw unstyled markup. It looks like the build broke
when nothing is wrong at all.

This sends `no-store` on everything, so a reload always fetches the current build.
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "web" / "out"


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
