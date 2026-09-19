"""BGPShield: measuring BGP route-security (RPKI ROV + ASPA) adoption and impact.

See ``implementation.md`` at the repo root for the plan and ``docs/`` for verified
data sources, pinned references and design decisions.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    #: The one version number, read from the installed package metadata so that
    #: ``pyproject.toml`` is the only place it is written down.
    __version__ = version("bgpshield")
except PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
