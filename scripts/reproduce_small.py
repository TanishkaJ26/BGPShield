"""Thin wrapper so `make reproduce-small` keeps working.

The reproduction itself lives in `hijax.reproduce` and is normally run as `hijax reproduce`,
which needs neither `make` nor `uv` on the machine. This file exists so the Makefile target
still works where `make` is available, and so there is exactly one implementation behind both
entry points rather than two that can drift.
"""

from __future__ import annotations

import sys

from hijax.cli import app


def main() -> None:
    app(["reproduce", *sys.argv[1:]])


if __name__ == "__main__":
    main()
