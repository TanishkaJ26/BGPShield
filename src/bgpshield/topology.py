"""Structural types for the AS relationship graph.

These are the shapes the validators, the detectors and the counterfactual expect of a
relationship source, declared in one place so no module has to import the ingestion package
just to describe what it needs. ``bgpshield.ingest.meta.RelationshipLookup`` satisfies all of
them, and a test can satisfy them with a few lines.

The direction convention is the confusable part and is repeated wherever it appears:
``rel(x, y)`` answers **"what is y to x?"**, returning ``c2p`` when y is x's provider, ``p2c``
when y is x's customer, ``p2p`` when they are peers, and ``None`` when nothing was inferred.
"""

from __future__ import annotations

from typing import Protocol


class RelSource(Protocol):
    """Can say how two networks are related, from the first one's point of view."""

    def rel(self, x: int, y: int) -> str | None: ...


class TopologySource(RelSource, Protocol):
    """Also knows a network's providers, which the scenarios and RQ2 need."""

    def providers(self, asn: int) -> set[int]: ...


class SiblingSource(Protocol):
    """Can say whether two AS numbers belong to the same organisation."""

    def are_siblings(self, x: int, y: int) -> bool: ...
