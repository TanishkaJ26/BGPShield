"""Simple hijack candidates (plan Section 10.5).

## What this is, and what it deliberately is not

A prefix hijack is a network announcing address space it does not hold. Telling a hijack from
a legitimate change of provider, a new anycast site or a customer moving between upstreams
needs context this project does not collect, so the plan is explicit: this is **context for
RQ3, not a main contribution**, and it should not be over-engineered. Everything here is a
*candidate*, and the word hijack never appears in an output column.

Three signals, all from routing data alone:

* **origin change**: a prefix appears with an origin that was not seen in the baseline period.
* **more specific**: a longer prefix inside a baseline prefix, announced by a different
  network.
* **multiple origins**: the same prefix announced by two or more networks at once, usually
  written MOAS. Often entirely legitimate, for instance anycast or a shared block.

The plan asks that each candidate be tagged with its origin-validation state, because a
candidate that is also RPKI-Invalid is far more interesting than one that is not.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from bgpshield.topology import SiblingSource


class CandidateType(StrEnum):
    ORIGIN_CHANGE = "origin_change"
    MORE_SPECIFIC = "more_specific"
    MULTIPLE_ORIGINS = "moas"


@dataclass(frozen=True, slots=True)
class HijackCandidate:
    """One prefix and origin worth a second look. Never a conclusion."""

    prefix: str
    origin_asn: int
    candidate_type: CandidateType
    baseline_origins: tuple[int, ...] = ()
    covering_prefix: str | None = None
    """For a more-specific candidate, the baseline prefix it sits inside."""
    rov_state: str | None = None


class _NoSiblings:
    def are_siblings(self, x: int, y: int) -> bool:
        return False


def _related(origin: int, others: Iterable[int], siblings: SiblingSource) -> bool:
    """True when the origin is one of the others, or a sibling of one.

    Two AS numbers of the same organisation announcing each other's space is routine, so it
    must not be reported (plan Section 10.5).
    """
    return any(origin == other or siblings.are_siblings(origin, other) for other in others)


def find_candidates(
    current: Mapping[str, set[int]],
    baseline: Mapping[str, set[int]],
    *,
    siblings: SiblingSource | None = None,
    rov_states: Mapping[tuple[str, int], str] | None = None,
) -> list[HijackCandidate]:
    """Compare today's prefix-to-origin map against a baseline period.

    ``baseline`` is what plan Section 10.5 describes as the origins seen over the previous 30
    days. A prefix absent from the baseline entirely produces nothing: it is new, not
    hijacked, and there is nothing to compare it with.
    """
    sib = siblings or _NoSiblings()
    states = rov_states or {}
    out: list[HijackCandidate] = []

    baseline_networks = _index_networks(baseline)

    for prefix, origins in sorted(current.items()):
        known = baseline.get(prefix)

        if len(origins) > 1:
            for origin in sorted(origins):
                if _related(origin, origins - {origin}, sib):
                    continue
                out.append(
                    HijackCandidate(
                        prefix=prefix,
                        origin_asn=origin,
                        candidate_type=CandidateType.MULTIPLE_ORIGINS,
                        baseline_origins=tuple(sorted(known or ())),
                        rov_state=states.get((prefix, origin)),
                    )
                )

        if known:
            for origin in sorted(origins):
                if not _related(origin, known, sib):
                    out.append(
                        HijackCandidate(
                            prefix=prefix,
                            origin_asn=origin,
                            candidate_type=CandidateType.ORIGIN_CHANGE,
                            baseline_origins=tuple(sorted(known)),
                            rov_state=states.get((prefix, origin)),
                        )
                    )
            continue

        covering = _find_covering(prefix, baseline_networks)
        if covering is None:
            continue
        covering_prefix, covering_origins = covering
        for origin in sorted(origins):
            if not _related(origin, covering_origins, sib):
                out.append(
                    HijackCandidate(
                        prefix=prefix,
                        origin_asn=origin,
                        candidate_type=CandidateType.MORE_SPECIFIC,
                        baseline_origins=tuple(sorted(covering_origins)),
                        covering_prefix=covering_prefix,
                        rov_state=states.get((prefix, origin)),
                    )
                )

    return out


def _index_networks(
    baseline: Mapping[str, set[int]],
) -> list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, str, set[int]]]:
    out = []
    for prefix, origins in baseline.items():
        try:
            network = ipaddress.ip_network(prefix, strict=False)
        except ValueError:
            continue
        out.append((network, prefix, origins))
    return out


def _find_covering(
    prefix: str,
    networks: list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, str, set[int]]],
) -> tuple[str, set[int]] | None:
    """The most specific baseline prefix that contains this one, if any."""
    try:
        target = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return None
    best: tuple[int, str, set[int]] | None = None
    for network, text, origins in networks:
        if network.version != target.version:
            continue
        if network.prefixlen >= target.prefixlen:
            continue
        if target.subnet_of(network) and (  # type: ignore[arg-type]
            best is None or network.prefixlen > best[0]
        ):
            best = (network.prefixlen, text, origins)
    return (best[1], best[2]) if best else None
