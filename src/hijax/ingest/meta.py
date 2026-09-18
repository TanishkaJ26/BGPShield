"""Registry metadata: which country and which RIR an AS number is registered in.

Plain English. Each of the five Regional Internet Registries publishes a daily text file
listing every address block and AS number it has handed out, in a shared layout called the
RIR statistics exchange format. The country in that file is where the resource was
*registered*, which is not necessarily where the network actually operates. The plan says
so in Section 8 and lists it as a threat to validity in Section 15, and any figure built
from this must repeat the caveat.

Phase 1 only needs the AS number to country and RIR mapping, so that is all this module
parses. The CAIDA relationship, organisation and customer-cone datasets arrive in Phase 2.
"""

from __future__ import annotations

import bz2
import gzip
import json
import lzma
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import requests

from hijax import net
from hijax.config import Config
from hijax.models import ASN_MAX

#: Statuses that mean the AS number is actually delegated to somebody. ``reserved`` and
#: ``available`` rows describe unissued space and are skipped. ARIN writes ``assigned``
#: where the others write ``allocated``; both were seen in the Phase 0 samples.
DELEGATED_STATUSES = frozenset({"allocated", "assigned"})

ASN_REGISTRY_SCHEMA: dict[str, pl.DataType] = {
    "asn": pl.Int64(),
    "country": pl.Utf8(),
    "rir": pl.Utf8(),
    "status": pl.Utf8(),
}


@dataclass(frozen=True, slots=True)
class AsnBlock:
    """One ``asn`` row: ``count`` consecutive AS numbers starting at ``first``."""

    first: int
    count: int
    country: str
    rir: str
    status: str


class DelegatedFormatError(ValueError):
    """A delegated-stats file did not match the format verified in Phase 0."""


def parse_delegated(lines: Iterable[str]) -> list[AsnBlock]:
    """Pull the AS-number rows out of one delegated-extended file.

    Record layout, from the format specification and confirmed against all five real files
    in Phase 0: ``registry|cc|type|start|value|date|status|opaque-id``. Comment lines start
    with ``#``; the first data line is a version line; per-type totals carry the literal
    ``summary`` in the sixth field. All three are skipped.
    """
    blocks: list[AsnBlock] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 7 or parts[5] == "summary":
            continue
        registry, country, kind, start, value, _date, status = parts[:7]
        if kind != "asn":
            continue
        if status not in DELEGATED_STATUSES:
            continue
        try:
            first, count = int(start), int(value)
        except ValueError as exc:
            raise DelegatedFormatError(f"bad asn row: {line!r}") from exc
        if count < 1 or first < 0 or first + count - 1 > ASN_MAX:
            raise DelegatedFormatError(f"asn row out of range: {line!r}")
        blocks.append(
            AsnBlock(
                first=first,
                count=count,
                country=country.upper(),
                rir=registry.lower(),
                status=status,
            )
        )
    return blocks


def expand(blocks: Iterable[AsnBlock]) -> Iterator[tuple[int, str, str, str]]:
    """Turn ``count`` consecutive AS numbers into one row each."""
    for block in blocks:
        for offset in range(block.count):
            yield block.first + offset, block.country, block.rir, block.status


def registry_frame(blocks: Iterable[AsnBlock]) -> pl.DataFrame:
    """Build the ``asn_registry`` lookup table: one row per delegated AS number."""
    rows = list(expand(blocks))
    return pl.DataFrame(
        {
            "asn": [r[0] for r in rows],
            "country": [r[1] for r in rows],
            "rir": [r[2] for r in rows],
            "status": [r[3] for r in rows],
        },
        schema=ASN_REGISTRY_SCHEMA,
    ).unique(subset=["asn"], keep="first", maintain_order=True)


def open_text(path: Path) -> Iterator[str]:
    """Read a delegated file, handling the compression each RIR happens to use."""
    if path.suffix == ".bz2":
        with bz2.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    elif path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    elif path.suffix == ".xz":
        with lzma.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            yield from handle
    else:
        with path.open(encoding="utf-8", errors="replace") as handle:
            yield from handle


def cache_path(cfg: Config, rir: str) -> Path:
    return cfg.paths.raw / "delegated" / f"delegated-{rir}-extended-latest"


def fetch_delegated(
    cfg: Config, rir: str, *, session: requests.Session | None = None, force: bool = False
) -> Path:
    """Download one RIR's current delegated-extended file, or reuse the cached copy."""
    owned = session is None
    sess = session or net.build_session(cfg.project.user_agent)
    try:
        path = net.download(sess, cfg.meta.delegated[rir], cache_path(cfg, rir), force=force)
    finally:
        if owned:
            sess.close()
    if path is None:
        raise DelegatedFormatError(f"{rir}: the registry has no delegated-extended file")
    return path


def build_asn_registry(cfg: Config, *, force: bool = False) -> pl.DataFrame:
    """Fetch all five RIR files and combine them into one AS number lookup.

    Note the limitation, which any figure using this must state: these are the *current*
    files, so an AS number is labelled with the country it is registered in today, not the
    country it was registered in on an older snapshot date. Dated files exist for every RIR
    and their URL patterns are recorded in ``docs/data-sources.md``; wiring them up belongs
    with the rest of the metadata ingestion in Phase 2.
    """
    frames: list[pl.DataFrame] = []
    session = net.build_session(cfg.project.user_agent)
    try:
        for rir in sorted(cfg.meta.delegated):
            path = fetch_delegated(cfg, rir, session=session, force=force)
            frames.append(registry_frame(parse_delegated(open_text(path))))
    finally:
        session.close()
    combined = pl.concat(frames) if frames else pl.DataFrame(schema=ASN_REGISTRY_SCHEMA)
    return combined.unique(subset=["asn"], keep="first", maintain_order=True).sort("asn")


def registry_path(cfg: Config) -> Path:
    return cfg.paths.processed / "asn_registry" / "asn_registry.parquet"


def write_asn_registry(cfg: Config, *, force: bool = False) -> tuple[Path, int]:
    """Build the lookup and store it. Returns the path and the number of AS numbers."""
    frame = build_asn_registry(cfg, force=force)
    out = registry_path(cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out)
    return out, frame.height


def load_asn_registry(cfg: Config) -> pl.DataFrame:
    """Read the stored lookup, building it first if it is not there yet."""
    path = registry_path(cfg)
    if not path.exists():
        write_asn_registry(cfg)
    return pl.read_parquet(path)


# --------------------------------------------------------------------------------------
# CAIDA AS relationships (plan Section 8, row 5)
# --------------------------------------------------------------------------------------

#: Relationship as stored. ``p2c`` rows are directed: ``as_a`` is the provider of ``as_b``.
#: ``p2p`` rows are an unordered pair of peers.
AS_REL_SCHEMA: dict[str, pl.DataType] = {
    "month": pl.Utf8(),
    "as_a": pl.Int64(),
    "as_b": pl.Int64(),
    "rel": pl.Utf8(),
}


@dataclass(frozen=True, slots=True)
class AsRelation:
    """One inferred business relationship between two networks.

    Plain English. Networks connect in two common ways. One pays the other for access to
    the rest of the Internet, which is a customer-to-provider link. Or they swap traffic
    between their own customers for free, which is a peer link. CAIDA *infers* these from
    public routing data, so they carry errors; the plan lists that as a threat to validity
    (Section 15) and Phase 5 guards against it.
    """

    as_a: int
    as_b: int
    rel: str  # "p2c" means as_a is the provider of as_b; "p2p" means they are peers


def parse_as_rel(lines: Iterable[str]) -> list[AsRelation]:
    """Parse a CAIDA ``as-rel2`` file.

    Format, quoted from the dataset README and confirmed against the real 2026-08 file in
    Phase 0: ``<provider-as>|<customer-as>|-1`` and ``<peer-as>|<peer-as>|0|<source>``.
    Comment lines start with ``#``.
    """
    out: list[AsRelation] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            left, right, code = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError as exc:
            raise DelegatedFormatError(f"bad as-rel row: {line!r}") from exc
        if code == -1:
            out.append(AsRelation(left, right, "p2c"))
        elif code == 0:
            out.append(AsRelation(left, right, "p2p"))
        else:
            raise DelegatedFormatError(f"unknown relationship code {code} in {line!r}")
    return out


def as_rel_frame(relations: Iterable[AsRelation], month: str) -> pl.DataFrame:
    rels = list(relations)
    return pl.DataFrame(
        {
            "month": [month] * len(rels),
            "as_a": [r.as_a for r in rels],
            "as_b": [r.as_b for r in rels],
            "rel": [r.rel for r in rels],
        },
        schema=AS_REL_SCHEMA,
    )


class RelationshipLookup:
    """Answer "what is AS y to AS x?" for the relationship graph of one month.

    The direction matters and is easy to get backwards, so the return value is written from
    ``x``'s point of view, exactly as plan Section 9 asks:

    * ``c2p`` means y is x's provider, so the route is travelling **up**
    * ``p2c`` means y is x's customer, so the route is travelling **down**
    * ``p2p`` means they are peers, so the route is travelling **across**
    * ``None`` means CAIDA inferred nothing about this pair
    """

    __slots__ = ("_peers", "_providers")

    def __init__(self, relations: Iterable[AsRelation]) -> None:
        self._providers: dict[int, set[int]] = {}
        self._peers: dict[int, set[int]] = {}
        for rel in relations:
            if rel.rel == "p2c":
                self._providers.setdefault(rel.as_b, set()).add(rel.as_a)
            else:
                self._peers.setdefault(rel.as_a, set()).add(rel.as_b)
                self._peers.setdefault(rel.as_b, set()).add(rel.as_a)

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> RelationshipLookup:
        return cls(
            AsRelation(int(a), int(b), str(r))
            for a, b, r in zip(frame["as_a"], frame["as_b"], frame["rel"], strict=True)
        )

    def providers(self, asn: int) -> set[int]:
        """The networks ``asn`` buys transit from."""
        return self._providers.get(asn, set())

    def peers(self, asn: int) -> set[int]:
        return self._peers.get(asn, set())

    def customers(self, asn: int) -> set[int]:
        """Built on demand; only Phase 5 needs it, and only for a handful of ASes."""
        return {customer for customer, provs in self._providers.items() if asn in provs}

    def rel(self, x: int, y: int) -> str | None:
        """What y is to x. See the class docstring for the direction convention."""
        if y in self._providers.get(x, ()):
            return "c2p"
        if x in self._providers.get(y, ()):
            return "p2c"
        if y in self._peers.get(x, ()):
            return "p2p"
        return None


# --------------------------------------------------------------------------------------
# CAIDA AS-to-organisation (plan Section 8, row 8)
# --------------------------------------------------------------------------------------

AS_ORG_SCHEMA: dict[str, pl.DataType] = {
    "asn": pl.Int64(),
    "org_id": pl.Utf8(),
    "org_name": pl.Utf8(),
    "org_country": pl.Utf8(),
}


def parse_as2org_jsonl(lines: Iterable[str]) -> pl.DataFrame:
    """Parse the JSON Lines form of CAIDA's AS-to-organisation dataset.

    Two record types share the file, told apart by ``type``. Verified against the real
    2026-09 file in Phase 0:

    * ``{"type": "Organization", "organizationId": ..., "name": ..., "country": ...}``
    * ``{"type": "ASN", "asn": "1", "organizationId": ..., "name": ...}``

    This matters because two AS numbers owned by the same organisation are *siblings*, and
    a route passing between siblings is not a leak (plan Section 10.4).
    """
    orgs: dict[str, tuple[str, str]] = {}
    members: list[tuple[int, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        record = json.loads(line)
        kind = record.get("type")
        if kind == "Organization":
            orgs[str(record["organizationId"])] = (
                str(record.get("name", "")),
                str(record.get("country", "")),
            )
        elif kind == "ASN":
            members.append((int(record["asn"]), str(record["organizationId"])))
    return pl.DataFrame(
        {
            "asn": [asn for asn, _ in members],
            "org_id": [org for _, org in members],
            "org_name": [orgs.get(org, ("", ""))[0] for _, org in members],
            "org_country": [orgs.get(org, ("", ""))[1] for _, org in members],
        },
        schema=AS_ORG_SCHEMA,
    )


class SiblingLookup:
    """Are two AS numbers run by the same organisation?"""

    __slots__ = ("_org",)

    def __init__(self, frame: pl.DataFrame) -> None:
        self._org: dict[int, str] = {
            int(asn): str(org) for asn, org in zip(frame["asn"], frame["org_id"], strict=True)
        }

    def org_of(self, asn: int) -> str | None:
        return self._org.get(asn)

    def are_siblings(self, x: int, y: int) -> bool:
        left, right = self._org.get(x), self._org.get(y)
        return left is not None and left == right


def parse_as2org_text(lines: Iterable[str]) -> pl.DataFrame:
    """Parse the pipe-delimited form of CAIDA's AS-to-organisation dataset.

    The JSON Lines form only exists for some releases, so older months have to be read from
    the original text format. Two record types share the file, separated by ``# format:``
    header lines, exactly as the dataset README describes and as verified in Phase 0:

        # format:org_id|changed|org_name|country|source
        # format:aut|changed|aut_name|org_id|opaque_id|source

    Which section is being read is decided by the most recent header, because the org and AS
    records are otherwise indistinguishable by field count alone.
    """
    orgs: dict[str, tuple[str, str]] = {}
    members: list[tuple[int, str]] = []
    reading_asns = False

    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("#"):
            compact = line.replace(" ", "").lower()
            if compact.startswith("#format:aut|"):
                reading_asns = True
            elif compact.startswith("#format:org_id|"):
                reading_asns = False
            continue
        if not line.strip():
            continue
        parts = line.split("|")
        if reading_asns:
            if len(parts) < 4:
                continue
            try:
                members.append((int(parts[0]), parts[3]))
            except ValueError:
                continue
        else:
            if len(parts) < 4:
                continue
            orgs[parts[0]] = (parts[2], parts[3])

    return pl.DataFrame(
        {
            "asn": [asn for asn, _ in members],
            "org_id": [org for _, org in members],
            "org_name": [orgs.get(org, ("", ""))[0] for _, org in members],
            "org_country": [orgs.get(org, ("", ""))[1] for _, org in members],
        },
        schema=AS_ORG_SCHEMA,
    )


def parse_as2org(path: Path) -> pl.DataFrame:
    """Parse either form of the AS-to-organisation dataset, chosen by file name."""
    if ".jsonl" in path.name:
        return parse_as2org_jsonl(open_text(path))
    return parse_as2org_text(open_text(path))


def _months_back(month: str, count: int) -> list[str]:
    """``month`` and the ``count`` months before it, newest first."""
    year, mon = (int(part) for part in month.split("-"))
    out = []
    for _ in range(count + 1):
        out.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            year, mon = year - 1, 12
    return out


def fetch_as2org(
    cfg: Config, month: str, *, session: requests.Session | None = None, force: bool = False
) -> tuple[Path, str]:
    """Fetch the newest AS-to-organisation file dated on or before ``month``.

    Two things make this more than a single download. The dataset was quarterly until 2024
    and only became monthly afterwards, so the exact month often does not exist; plan
    Section 5 says to use the latest file dated on or before the target. And the JSON Lines
    form was only published for some releases, so the original pipe-delimited text has to be
    accepted as a fallback.

    Returns the cached path and the month actually used, so a caller can report the
    substitution rather than silently pretending it got what it asked for.
    """
    owned = session is None
    sess = session or net.build_session(cfg.project.user_agent)
    try:
        for candidate in _months_back(month, 12):
            stamp = month_first_day(candidate)
            for pattern in (
                cfg.meta.caida_as2org_pattern,
                cfg.meta.caida_as2org_pattern.replace(".jsonl.", ".txt."),
            ):
                name = pattern.format(yyyymmdd=stamp)
                found = net.download(
                    sess,
                    f"{cfg.meta.caida_as2org_base}/{name}",
                    cfg.paths.raw / "caida" / name,
                    force=force,
                )
                if found is not None:
                    return found, candidate
    finally:
        if owned:
            sess.close()
    raise DelegatedFormatError(
        f"no CAIDA as2org file found for {month} or the twelve months before it"
    )


# --------------------------------------------------------------------------------------
# CAIDA AS Rank: customer cone and rank (plan Section 8, row 6)
# --------------------------------------------------------------------------------------

AS_RANK_SCHEMA: dict[str, pl.DataType] = {
    "asn": pl.Int64(),
    "rank": pl.Int64(),
    "cone_asns": pl.Int64(),
    "cone_prefixes": pl.Int64(),
}

_ASRANK_QUERY = """
query($first: Int!, $offset: Int!) {
  asns(first: $first, offset: $offset) {
    totalCount
    pageInfo { first hasNextPage }
    edges { node { asn rank cone { numberAsns numberPrefixes } } }
  }
}
"""


def asrank_page(
    cfg: Config, session: requests.Session, offset: int, page_size: int
) -> tuple[list[dict[str, Any]], bool, int]:
    """Fetch one page of the AS Rank list, newest-first by rank.

    Plain English: the *customer cone* of a network is the set of networks reachable
    through it as customers, so it is a size measure that reflects transit importance
    rather than address count. The plan uses it to pick the "top N" networks in the
    counterfactual scenarios (Section 10.6).
    """
    response = session.post(
        cfg.meta.asrank_graphql,
        json={"query": _ASRANK_QUERY, "variables": {"first": page_size, "offset": offset}},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    if "errors" in payload:
        raise DelegatedFormatError(f"AS Rank API returned errors: {payload['errors']}")
    block = payload["data"]["asns"]
    nodes = [edge["node"] for edge in block["edges"]]
    return nodes, bool(block["pageInfo"]["hasNextPage"]), int(block["totalCount"])


def fetch_asrank(
    cfg: Config, *, page_size: int = 1000, max_pages: int | None = None, pause: float = 0.5
) -> pl.DataFrame:
    """Walk the whole AS Rank list into a frame. Slow, so it is a monthly job."""
    session = net.build_session(cfg.project.user_agent)
    rows: list[dict[str, Any]] = []
    offset = 0
    pages = 0
    try:
        while True:
            nodes, has_next, _total = asrank_page(cfg, session, offset, page_size)
            rows.extend(nodes)
            pages += 1
            offset += page_size
            if not has_next or not nodes:
                break
            if max_pages is not None and pages >= max_pages:
                break
            time.sleep(pause)
    finally:
        session.close()
    return asrank_frame(rows)


def asrank_frame(nodes: Iterable[dict[str, Any]]) -> pl.DataFrame:
    items = list(nodes)
    return pl.DataFrame(
        {
            "asn": [int(n["asn"]) for n in items],
            "rank": [int(n["rank"]) if n.get("rank") is not None else None for n in items],
            "cone_asns": [int((n.get("cone") or {}).get("numberAsns") or 0) for n in items],
            "cone_prefixes": [int((n.get("cone") or {}).get("numberPrefixes") or 0) for n in items],
        },
        schema=AS_RANK_SCHEMA,
    )


# --------------------------------------------------------------------------------------
# as_meta: one row per AS number per month (plan Section 9)
# --------------------------------------------------------------------------------------

AS_META_SCHEMA: dict[str, pl.DataType] = {
    "month": pl.Utf8(),
    "asn": pl.Int64(),
    "country": pl.Utf8(),
    "rir": pl.Utf8(),
    "org_id": pl.Utf8(),
    "cone_size": pl.Int64(),
    "rank": pl.Int64(),
}


def build_as_meta(
    month: str,
    registry: pl.DataFrame,
    orgs: pl.DataFrame,
    ranks: pl.DataFrame,
) -> pl.DataFrame:
    """Join the three metadata sources into the ``as_meta`` table.

    ``country`` and ``rir`` come from the RIR delegated files, ``org_id`` from CAIDA's
    AS-to-organisation mapping, and ``cone_size`` and ``rank`` from CAIDA AS Rank. An AS
    present in one source but not another keeps nulls rather than being dropped, so counts
    built on this table still add up.
    """
    frame = (
        registry.select(["asn", "country", "rir"])
        .join(orgs.select(["asn", "org_id"]), on="asn", how="full", coalesce=True)
        .join(
            ranks.select(["asn", "cone_asns", "rank"]).rename({"cone_asns": "cone_size"}),
            on="asn",
            how="full",
            coalesce=True,
        )
        .with_columns(pl.lit(month).alias("month"))
    )
    return frame.select(list(AS_META_SCHEMA)).cast(AS_META_SCHEMA).sort("asn")  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Downloads and storage for the monthly metadata
# --------------------------------------------------------------------------------------


def month_first_day(month: str) -> str:
    """``"2026-08"`` becomes ``"20260801"``, which is how CAIDA names its monthly files."""
    year, mon = month.split("-")
    return f"{int(year):04d}{int(mon):02d}01"


def caida_paths(cfg: Config, month: str) -> tuple[str, Path, str, Path]:
    """URLs and cache paths for one month's relationship and organisation files."""
    stamp = month_first_day(month)
    rel_name = cfg.meta.caida_as_rel_pattern.format(yyyymmdd=stamp)
    org_name = cfg.meta.caida_as2org_pattern.format(yyyymmdd=stamp)
    return (
        f"{cfg.meta.caida_as_rel_base}/{rel_name}",
        cfg.paths.raw / "caida" / rel_name,
        f"{cfg.meta.caida_as2org_base}/{org_name}",
        cfg.paths.raw / "caida" / org_name,
    )


def table_path(cfg: Config, table: str, month: str) -> Path:
    return cfg.paths.processed / table / f"month={month}" / f"{table}.parquet"


@dataclass(slots=True)
class MetaResult:
    """What one month's metadata ingestion produced."""

    month: str
    relationships: int = 0
    organisations: int = 0
    ranked: int = 0
    as_meta_rows: int = 0
    skipped_asrank: bool = False
    as2org_month: str = ""
    """The month the organisation data actually came from, which may be earlier than asked
    for because the dataset was quarterly before 2024."""


def ingest_month(
    cfg: Config,
    month: str,
    *,
    force: bool = False,
    skip_asrank: bool = False,
    asrank_pages: int | None = None,
) -> MetaResult:
    """Build the ``as_rel`` and ``as_meta`` tables for one month.

    CAIDA publishes relationships and organisations monthly, dated the first of the month.
    Plan Section 5 says to use the newest file dated on or before the snapshot, and Section
    10.4 says leak detection should use the month *before* the snapshot so the relationships
    are not inferred from the very event being studied.
    """
    result = MetaResult(month=month)
    rel_url, rel_path, _org_url, _org_path = caida_paths(cfg, month)

    session = net.build_session(cfg.project.user_agent)
    try:
        if net.download(session, rel_url, rel_path, force=force) is None:
            raise DelegatedFormatError(f"CAIDA published no as-rel file for {month}")
        org_path, org_month = fetch_as2org(cfg, month, session=session, force=force)
    finally:
        session.close()

    result.as2org_month = org_month
    relations = parse_as_rel(open_text(rel_path))
    rel_out = table_path(cfg, "as_rel", month)
    rel_out.parent.mkdir(parents=True, exist_ok=True)
    as_rel_frame(relations, month).write_parquet(rel_out)
    result.relationships = len(relations)

    orgs = parse_as2org(org_path)
    result.organisations = orgs.height

    ranks_path = table_path(cfg, "as_rank", month)
    if skip_asrank:
        ranks = (
            pl.read_parquet(ranks_path)
            if ranks_path.exists()
            else pl.DataFrame(schema=AS_RANK_SCHEMA)
        )
        result.skipped_asrank = True
    elif ranks_path.exists() and not force:
        ranks = pl.read_parquet(ranks_path)
    else:
        ranks = fetch_asrank(cfg, max_pages=asrank_pages)
        ranks_path.parent.mkdir(parents=True, exist_ok=True)
        ranks.write_parquet(ranks_path)
    result.ranked = ranks.height

    registry = load_asn_registry(cfg)
    as_meta = build_as_meta(month, registry, orgs, ranks)
    meta_out = table_path(cfg, "as_meta", month)
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    as_meta.write_parquet(meta_out)
    result.as_meta_rows = as_meta.height
    return result
