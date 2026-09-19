"""Turn one day of published RPKI data into the ``vrps`` and ``aspas`` tables.

What this does, in plain English. Networks publish signed records in the RPKI saying which
AS may originate which addresses (ROAs, RFC 6480) and which ASes are their upstream
providers (ASPAs, ``draft-ietf-sidrops-aspa-profile-29``). A *validator* fetches the whole
repository, checks every signature, and writes the surviving payloads to a JSON file. This
module downloads one such file per trust anchor per day, normalizes it, and stores it as
Parquet so later phases can query a snapshot instantly.

Two validators produce that JSON and their field names differ. Both shapes were confirmed
against real downloads in Phase 0; see ``docs/data-sources.md`` sections 3 and 4a.

* Routinator, used by the RIPE NCC archive: ``{"customer": "AS553", "providers": ["AS559"],
  "ta": "ripencc"}``.
* rpki-client, used by rpkiviews: ``{"customer_asid": 43, "expires": 1789657200,
  "providers": [293]}``, with no trust anchor on ASPA records.

There is one adapter per shape and a test for each, as plan Section 9 requires.
"""

from __future__ import annotations

import json
import lzma
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
import requests

from bgpshield import net
from bgpshield.config import Config
from bgpshield.models import (
    Aspa,
    RecordFormatError,
    Vrp,
    afi_of_prefix,
    apply_as0_rule,
    epoch_to_utc,
    parse_asn,
)

SnapshotFormat = Literal["routinator", "rpki-client"]

#: The plan's Section 9 table fixes the trust-anchor labels as
#: afrinic/apnic/arin/lacnic/ripe. Routinator calls the last one ``ripencc``, so map it.
CANONICAL_TA: dict[str, str] = {
    "afrinic": "afrinic",
    "apnic": "apnic",
    "arin": "arin",
    "lacnic": "lacnic",
    "ripe": "ripe",
    "ripencc": "ripe",
}

VRPS_SCHEMA: dict[str, pl.DataType] = {
    "prefix": pl.Utf8(),
    "afi": pl.Int8(),
    "max_length": pl.Int16(),
    "asn": pl.Int64(),
    "ta": pl.Utf8(),
    "snapshot_date": pl.Date(),
}

ASPAS_SCHEMA: dict[str, pl.DataType] = {
    "customer_asn": pl.Int64(),
    "provider_asns": pl.List(pl.Int64()),
    "ta": pl.Utf8(),
    "expires": pl.Datetime("us", "UTC"),
    "snapshot_date": pl.Date(),
}


def canonical_ta(value: str | None) -> str | None:
    """Map a validator's trust-anchor spelling to the project's canonical one."""
    if value is None:
        return None
    key = value.strip().lower().removesuffix(".tal")
    try:
        return CANONICAL_TA[key]
    except KeyError as exc:
        raise RecordFormatError(f"unknown trust anchor: {value!r}") from exc


@dataclass(slots=True)
class _Parsed:
    vrps: list[Vrp]
    aspas: list[Aspa]
    as0_dropped: int = 0
    """Records that listed AS 0 alongside real providers, which the profile forbids."""


@dataclass(slots=True)
class ParseStats:
    """Counts worth reporting, so nothing is silently dropped."""

    roa_rows: int = 0
    vrps_unique: int = 0
    aspa_rows: int = 0
    aspas_unique: int = 0
    aspas_merged: int = 0
    """Customers that published more than one ASPA. The verification draft Section 5.3
    says to take the union of their provider sets (the "U-SPAS"), which is what we do."""
    providers_as0: int = 0
    """ASPA records whose only provider is AS 0, meaning "I have no providers"."""
    as0_dropped: int = 0
    """Customers that listed AS 0 alongside real providers. The profile forbids that
    combination (Section 3) and says AS 0 must be removed from a union that has other
    members (Section 5.2), so it is dropped and counted here as a data-quality signal."""


def detect_format(obj: Mapping[str, Any]) -> SnapshotFormat:
    """Work out which validator wrote this JSON, from its metadata block."""
    meta = obj.get("metadata")
    if isinstance(meta, Mapping):
        if "buildtime" in meta:
            return "rpki-client"
        if "generatedTime" in meta or "generated" in meta:
            return "routinator"
    aspas = obj.get("aspas")
    if isinstance(aspas, list) and aspas:
        first = aspas[0]
        if isinstance(first, Mapping):
            if "customer_asid" in first:
                return "rpki-client"
            if "customer" in first:
                return "routinator"
    raise RecordFormatError(
        "cannot tell which validator wrote this snapshot; "
        "expected a metadata block with 'buildtime' or 'generatedTime'"
    )


def _as_list(obj: Mapping[str, Any], key: str) -> Sequence[Any]:
    value = obj.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RecordFormatError(f"{key!r} should be a list, got {type(value).__name__}")
    return value


def _vrp_from(entry: Mapping[str, Any], ta_fallback: str | None) -> Vrp:
    try:
        prefix = str(entry["prefix"])
        max_length = int(entry["maxLength"])
        asn = parse_asn(entry["asn"])
    except KeyError as exc:
        raise RecordFormatError(f"ROA entry missing {exc.args[0]!r}: {entry!r}") from exc
    ta = canonical_ta(entry.get("ta")) or ta_fallback
    if ta is None:
        raise RecordFormatError(f"ROA entry has no trust anchor: {entry!r}")
    return Vrp(prefix=prefix, afi=afi_of_prefix(prefix), max_length=max_length, asn=asn, ta=ta)


def parse_routinator(obj: Mapping[str, Any], ta_fallback: str | None = None) -> _Parsed:
    """Adapter for Routinator JSON, the format in the RIPE NCC archive."""
    vrps = [_vrp_from(e, ta_fallback) for e in _as_list(obj, "roas") if isinstance(e, Mapping)]
    aspas: list[Aspa] = []
    as0_dropped = 0
    for entry in _as_list(obj, "aspas"):
        if not isinstance(entry, Mapping):
            continue
        try:
            customer = parse_asn(entry["customer"])
        except KeyError as exc:
            raise RecordFormatError(f"ASPA entry missing 'customer': {entry!r}") from exc
        raw = {parse_asn(v) for v in _as_list(entry, "providers")}
        if 0 in raw and len(raw) > 1:
            as0_dropped += 1
        aspas.append(
            Aspa(
                customer_asn=customer,
                provider_asns=apply_as0_rule(raw),
                ta=canonical_ta(entry.get("ta")) or ta_fallback,
                expires=None,
            )
        )
    return _Parsed(vrps=vrps, aspas=aspas, as0_dropped=as0_dropped)


def parse_rpki_client(obj: Mapping[str, Any], ta_fallback: str | None = None) -> _Parsed:
    """Adapter for rpki-client JSON, the format in the rpkiviews snapshots."""
    vrps = [_vrp_from(e, ta_fallback) for e in _as_list(obj, "roas") if isinstance(e, Mapping)]
    aspas: list[Aspa] = []
    as0_dropped = 0
    for entry in _as_list(obj, "aspas"):
        if not isinstance(entry, Mapping):
            continue
        try:
            customer = parse_asn(entry["customer_asid"])
        except KeyError as exc:
            raise RecordFormatError(f"ASPA entry missing 'customer_asid': {entry!r}") from exc
        raw = {parse_asn(v) for v in _as_list(entry, "providers")}
        if 0 in raw and len(raw) > 1:
            as0_dropped += 1
        aspas.append(
            Aspa(
                customer_asn=customer,
                provider_asns=apply_as0_rule(raw),
                # rpki-client does not label ASPA records with a trust anchor.
                ta=canonical_ta(entry.get("ta")) or ta_fallback,
                expires=epoch_to_utc(entry.get("expires")),
            )
        )
    return _Parsed(vrps=vrps, aspas=aspas, as0_dropped=as0_dropped)


def parse_snapshot(obj: Mapping[str, Any], ta_fallback: str | None = None) -> _Parsed:
    """Parse a validator snapshot, choosing the adapter from the file's own metadata."""
    if detect_format(obj) == "rpki-client":
        return parse_rpki_client(obj, ta_fallback)
    return parse_routinator(obj, ta_fallback)


def deduplicate(parsed: _Parsed) -> tuple[list[Vrp], list[Aspa], ParseStats]:
    """Collapse duplicate VRPs, and union the provider sets of repeated customers.

    Two different ROAs can yield the identical VRP triple, and one AS may publish more than
    one ASPA. ``draft-ietf-sidrops-aspa-verification-28`` Section 5.3 defines the effective
    provider set as the union across all of a customer's valid ASPAs, so that is what a
    snapshot row holds.
    """
    stats = ParseStats(roa_rows=len(parsed.vrps), aspa_rows=len(parsed.aspas))

    seen_vrps: dict[tuple[str, int, int, str], Vrp] = {}
    for vrp in parsed.vrps:
        seen_vrps.setdefault((vrp.prefix, vrp.max_length, vrp.asn, vrp.ta), vrp)
    vrps = list(seen_vrps.values())
    stats.vrps_unique = len(vrps)

    merged: dict[tuple[int, str | None], Aspa] = {}
    union_dropped_as0 = 0
    for aspa in parsed.aspas:
        key = (aspa.customer_asn, aspa.ta)
        existing = merged.get(key)
        if existing is None:
            merged[key] = aspa
            continue
        stats.aspas_merged += 1
        combined = set(existing.provider_asns) | set(aspa.provider_asns)
        if 0 in combined and len(combined) > 1:
            union_dropped_as0 += 1
        union = apply_as0_rule(combined)
        expires = _earliest(existing.expires, aspa.expires)
        merged[key] = Aspa(
            customer_asn=aspa.customer_asn,
            provider_asns=union,
            ta=aspa.ta,
            expires=expires,
        )
    aspas = list(merged.values())
    stats.aspas_unique = len(aspas)
    stats.providers_as0 = sum(1 for a in aspas if a.provider_asns == (0,))
    stats.as0_dropped = parsed.as0_dropped + union_dropped_as0
    return vrps, aspas, stats


def _earliest(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def vrps_frame(vrps: Sequence[Vrp], snapshot_date: date) -> pl.DataFrame:
    """Build the ``vrps`` table for one snapshot date (plan Section 9)."""
    return pl.DataFrame(
        {
            "prefix": [v.prefix for v in vrps],
            "afi": [v.afi for v in vrps],
            "max_length": [v.max_length for v in vrps],
            "asn": [v.asn for v in vrps],
            "ta": [v.ta for v in vrps],
            "snapshot_date": [snapshot_date] * len(vrps),
        },
        schema=VRPS_SCHEMA,
    )


def aspas_frame(aspas: Sequence[Aspa], snapshot_date: date) -> pl.DataFrame:
    """Build the ``aspas`` table for one snapshot date (plan Section 9)."""
    return pl.DataFrame(
        {
            "customer_asn": [a.customer_asn for a in aspas],
            "provider_asns": [list(a.provider_asns) for a in aspas],
            "ta": [a.ta for a in aspas],
            "expires": [a.expires for a in aspas],
            "snapshot_date": [snapshot_date] * len(aspas),
        },
        schema=ASPAS_SCHEMA,
    )


# --------------------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------------------


def build_session(cfg: Config) -> requests.Session:
    """A session carrying the project's User-Agent (plan Section 16)."""
    return net.build_session(cfg.project.user_agent)


_LOCAL = threading.local()


def thread_session(cfg: Config) -> requests.Session:
    """One session per worker thread. ``requests.Session`` is not documented as
    thread-safe, so each thread gets its own and keeps connection reuse."""
    session: requests.Session | None = getattr(_LOCAL, "session", None)
    if session is None:
        session = build_session(cfg)
        _LOCAL.session = session
    return session


def archive_url(cfg: Config, ta: str, day: date) -> str:
    """URL of one trust anchor's validator output for one day.

    Verified pattern (Phase 0): ``https://ftp.ripe.net/rpki/<ta>.tal/YYYY/MM/DD/output.json.xz``
    """
    return f"{cfg.rpki.archive_base}/{ta}.tal/{day:%Y/%m/%d}/{cfg.rpki.file}"


def cache_path(cfg: Config, ta: str, day: date) -> Path:
    """Where a downloaded snapshot is cached. Everything under ``data/`` is gitignored."""
    return cfg.paths.raw / "rpki" / "ripe-archive" / f"{ta}.tal" / f"{day:%Y%m%d}.{cfg.rpki.file}"


def fetch_archive_file(
    cfg: Config,
    ta: str,
    day: date,
    *,
    session: requests.Session | None = None,
    force: bool = False,
) -> Path | None:
    """Download one snapshot, or return the cached copy.

    ``None`` means the archive published nothing for that trust anchor that day, which
    happens on the gap days listed in ``docs/data-sources.md``.
    """
    sess = session or thread_session(cfg)
    return net.download(sess, archive_url(cfg, ta, day), cache_path(cfg, ta, day), force=force)


def load_snapshot_json(path: Path) -> Mapping[str, Any]:
    """Read a validator snapshot, transparently handling ``.xz`` compression."""
    if path.suffix == ".xz":
        with lzma.open(path) as handle:
            loaded = json.load(handle)
    else:
        with path.open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise RecordFormatError(f"{path} does not contain a JSON object")
    return loaded


# --------------------------------------------------------------------------------------
# One day, end to end
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class DayResult:
    """What happened for one snapshot date."""

    snapshot_date: date
    trust_anchors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    vrps: int = 0
    aspas: int = 0
    aspas_merged: int = 0
    providers_as0: int = 0
    as0_dropped: int = 0
    vrps_path: Path | None = None
    aspas_path: Path | None = None
    skipped: bool = False


def table_path(cfg: Config, table: str, day: date) -> Path:
    """Hive-style partition path, so DuckDB and polars can read a date range directly."""
    return cfg.paths.processed / table / f"snapshot_date={day:%Y-%m-%d}" / f"{table}.parquet"


def ingest_date(
    cfg: Config,
    day: date,
    *,
    session: requests.Session | None = None,
    force: bool = False,
    jobs: int = 4,
) -> DayResult:
    """Fetch every trust anchor for ``day``, normalize, and write both Parquet tables.

    The five trust-anchor files are fetched concurrently because downloading dominates the
    runtime; parsing a whole day takes only a few seconds. ``jobs`` caps how many
    connections the archive sees at once, which keeps the job within polite limits
    (plan Section 16).
    """
    result = DayResult(snapshot_date=day)
    vrps_out = table_path(cfg, "vrps", day)
    aspas_out = table_path(cfg, "aspas", day)
    if vrps_out.exists() and aspas_out.exists() and not force:
        frame = pl.read_parquet(aspas_out)
        result.skipped = True
        result.vrps_path, result.aspas_path = vrps_out, aspas_out
        result.aspas = frame.height
        result.vrps = pl.read_parquet(vrps_out).height
        return result

    all_vrps: list[Vrp] = []
    all_aspas: list[Aspa] = []
    all_as0_dropped = 0

    def fetch(ta: str) -> tuple[str, Path | None]:
        sess = session or thread_session(cfg)
        return ta, fetch_archive_file(cfg, ta, day, session=sess, force=force)

    workers = max(1, min(jobs, len(cfg.rpki.trust_anchors)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = list(pool.map(fetch, cfg.rpki.trust_anchors))

    for ta, path in fetched:
        if path is None:
            result.missing.append(ta)
            continue
        parsed = parse_snapshot(load_snapshot_json(path), ta_fallback=canonical_ta(ta))
        all_vrps.extend(parsed.vrps)
        all_aspas.extend(parsed.aspas)
        all_as0_dropped += parsed.as0_dropped
        result.trust_anchors.append(ta)

    if not result.trust_anchors:
        return result

    vrps, aspas, stats = deduplicate(
        _Parsed(vrps=all_vrps, aspas=all_aspas, as0_dropped=all_as0_dropped)
    )
    vrps_out.parent.mkdir(parents=True, exist_ok=True)
    aspas_out.parent.mkdir(parents=True, exist_ok=True)
    vrps_frame(vrps, day).write_parquet(vrps_out)
    aspas_frame(aspas, day).write_parquet(aspas_out)

    result.vrps = stats.vrps_unique
    result.aspas = stats.aspas_unique
    result.aspas_merged = stats.aspas_merged
    result.providers_as0 = stats.providers_as0
    result.as0_dropped = stats.as0_dropped
    result.vrps_path, result.aspas_path = vrps_out, aspas_out
    return result


def date_range(start: date, end: date, every_days: int) -> list[date]:
    """Dates from ``start`` to ``end`` inclusive, stepping ``every_days`` at a time."""
    if every_days < 1:
        raise ValueError("--every must be at least 1 day")
    if end < start:
        raise ValueError("--to must not be before --from")
    out: list[date] = []
    current = start
    while current <= end:
        out.append(current)
        current = date.fromordinal(current.toordinal() + every_days)
    return out
