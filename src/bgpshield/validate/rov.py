"""Route Origin Validation (plan Section 10.2), per RFC 6811.

## What this is, in plain English

Anyone can announce any block of addresses in BGP, and the protocol believes them. RPKI
fixes the first half of that: the holder of an address block signs a statement saying which
AS number is allowed to originate it, and up to what prefix length. A validator flattens
those statements into simple triples called VRPs, for Validated ROA Payloads.

Origin validation compares a route against them and returns one of three answers
(RFC 6811 Section 2):

* **Valid** means some VRP covers this prefix, names this origin, and allows a prefix this
  long.
* **Invalid** means VRPs cover the prefix but none of them permits this announcement. Either
  the wrong network is originating it, or it has been chopped into pieces finer than the
  holder allowed.
* **NotFound** means nobody signed anything about this address space. Most of the Internet
  still looks like this, so it is not a complaint.

"Covering" is the key relation: a VRP covers a route's prefix when the VRP's prefix contains
it, which includes the case where they are identical.

## A Windows detail worth knowing

The underlying radix tree is a C extension that calls the Windows socket library without
initialising it. Importing Python's ``socket`` module first does that initialisation, so it
is imported here even though this module never opens a socket. Without it the first insert
fails with a WSAStartup error. Recorded as D-012 in ``docs/decisions.md``.
"""

from __future__ import annotations

import socket  # noqa: F401  # initialises Winsock before py-radix is used; see the docstring
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl
import radix


class RovState(StrEnum):
    """The three outcomes of RFC 6811 Section 2."""

    VALID = "valid"
    INVALID = "invalid"
    NOT_FOUND = "not_found"


class RovReason(StrEnum):
    """Why a route came out Invalid. Plan Section 10.2 asks for this to be recorded."""

    NONE = ""
    WRONG_ORIGIN = "wrong_origin"
    """Covered, but no VRP names this origin."""
    TOO_SPECIFIC = "too_specific"
    """A VRP names this origin but the announcement is longer than its maxLength.
    RFC 9319 explains why loose maxLength values cause exactly this."""
    AS0 = "as0"
    """The route claims AS 0 as its origin, which is reserved and never valid (RFC 7607)."""
    UNKNOWN_ORIGIN = "unknown_origin"
    """The path ended in an AS_SET, so there is no single origin to check."""


@dataclass(frozen=True, slots=True)
class VrpEntry:
    """One Validated ROA Payload, minus the prefix that indexes it."""

    asn: int
    max_length: int
    ta: str | None = None


@dataclass(frozen=True, slots=True)
class RovResult:
    state: RovState
    reason: RovReason = RovReason.NONE
    covering: int = 0
    """How many VRPs covered the prefix, which distinguishes "nobody signed this" from
    "signed, but this announcement is not allowed"."""


class VrpIndex:
    """A prefix tree of VRPs, answering "which signed statements cover this route?".

    One tree holds both address families: the underlying library keeps IPv4 and IPv6
    separate, so an IPv6 lookup never matches an IPv4 entry. Verified in Phase 3.
    """

    __slots__ = ("_count", "_tree")

    def __init__(self) -> None:
        self._tree = radix.Radix()
        self._count = 0

    def __len__(self) -> int:
        return self._count

    def add(self, prefix: str, max_length: int, asn: int, ta: str | None = None) -> None:
        """Add one VRP. Several VRPs may share a prefix, so each node holds a list."""
        node = self._tree.add(prefix)
        entries: list[VrpEntry] = node.data.setdefault("vrps", [])
        entries.append(VrpEntry(asn=asn, max_length=max_length, ta=ta))
        self._count += 1

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> VrpIndex:
        """Build from the ``vrps`` table written by ``bgpshield ingest-rpki``."""
        index = cls()
        columns = ["prefix", "max_length", "asn"]
        has_ta = "ta" in frame.columns
        if has_ta:
            columns.append("ta")
        for row in frame.select(columns).iter_rows():
            index.add(str(row[0]), int(row[1]), int(row[2]), str(row[3]) if has_ta else None)
        return index

    def covering(self, prefix: str) -> list[VrpEntry]:
        """Every VRP whose prefix contains ``prefix``, including an exact match."""
        found: list[VrpEntry] = []
        for node in self._tree.search_covering(prefix):
            data: dict[str, Any] = node.data
            found.extend(data.get("vrps", ()))
        return found

    def validate(self, prefix: str, origin_asn: int | None) -> RovResult:
        """Validate one route's origin (RFC 6811 Section 2, plan Section 10.2).

        ``origin_asn`` is ``None`` when the AS_PATH ended in an AS_SET. There is then no
        single origin to check, so a covered prefix is Invalid and an uncovered one is
        NotFound, exactly as plan Section 10.2 step 5 specifies.
        """
        entries = self.covering(prefix)
        if not entries:
            return RovResult(RovState.NOT_FOUND)

        length = _prefix_length(prefix)

        if origin_asn is None:
            return RovResult(RovState.INVALID, RovReason.UNKNOWN_ORIGIN, len(entries))
        if origin_asn == 0:
            # AS 0 is reserved and must never appear as an origin (RFC 7607 Section 4).
            return RovResult(RovState.INVALID, RovReason.AS0, len(entries))

        origin_matched = False
        for entry in entries:
            if entry.asn != origin_asn or entry.asn == 0:
                continue
            origin_matched = True
            if length <= entry.max_length:
                return RovResult(RovState.VALID, RovReason.NONE, len(entries))

        reason = RovReason.TOO_SPECIFIC if origin_matched else RovReason.WRONG_ORIGIN
        return RovResult(RovState.INVALID, reason, len(entries))


def _prefix_length(prefix: str) -> int:
    _, _, length = prefix.partition("/")
    return int(length)


def validate_many(index: VrpIndex, routes: Iterable[tuple[str, int | None]]) -> list[RovResult]:
    """Validate a batch of ``(prefix, origin_asn)`` pairs."""
    return [index.validate(prefix, origin) for prefix, origin in routes]
