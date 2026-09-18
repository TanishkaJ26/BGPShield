"""Turn a collector's routing-table dump into the ``routes`` table (plan Section 10.1).

Plain English. A *route collector* is a passive BGP speaker that peers with many networks
and writes down everything it hears. Once or twice a day it dumps its whole table, which is
one row per (peer, prefix): "this neighbour told me it can reach this block of addresses,
along this path". Those dumps are stored in MRT format (RFC 6396). This module streams one
dump, normalizes every path, and writes Parquet.

Memory matters here: a large collector's table has tens of millions of rows, so rows are
written out in batches and never all held at once (plan Section 16).

Path direction: the stored ``as_path`` is **origin first**. See ``hijax.paths``.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import bgpkit
import pyarrow as pa
import pyarrow.parquet as pq

from hijax.config import Config
from hijax.paths import PathFlag, normalize

#: Arrow schema for the ``routes`` table, following plan Section 9.
ROUTES_SCHEMA = pa.schema(
    [
        pa.field("collector", pa.string()),
        pa.field("peer_ip", pa.string()),
        pa.field("peer_asn", pa.int64()),
        pa.field("prefix", pa.string()),
        pa.field("afi", pa.int8()),
        pa.field("as_path_raw", pa.string()),
        pa.field("as_path", pa.list_(pa.int64())),
        pa.field("has_as_set", pa.bool_()),
        pa.field("origin_asn", pa.int64()),  # null when the path ends in an AS_SET
        pa.field("timestamp", pa.timestamp("us", tz="UTC")),
        pa.field("snapshot_date", pa.date32()),
    ]
)

DEFAULT_BATCH_ROWS = 250_000


class RibNotFoundError(RuntimeError):
    """No routing-table dump was published for that collector on that date."""


@dataclass(slots=True)
class CollectorResult:
    """What one collector's dump produced, including why rows were flagged."""

    collector: str
    snapshot_date: date
    url: str = ""
    rows: int = 0
    peers: int = 0
    prefixes: int = 0
    flags: Counter[PathFlag] = field(default_factory=Counter)
    seconds: float = 0.0
    path: Path | None = None
    skipped: bool = False
    error: str | None = None
    """Set when this collector failed. One collector failing must not lose the others."""

    def flag_rate(self, flag: PathFlag) -> float:
        """Share of rows carrying one flag, as a fraction of all rows."""
        return self.flags.get(flag, 0) / self.rows if self.rows else 0.0


def find_rib_url(cfg: Config, collector: str, day: date, *, hour_pref: str | None = None) -> str:
    """Ask the BGPKIT Broker for the routing-table dump nearest the configured time.

    Collectors dump on their own timetable: RIPE RIS every 8 hours, RouteViews every 2
    (verified in Phase 0). Asking the Broker avoids hard-coding either schedule.
    """
    want = hour_pref or cfg.bgp.rib_time_utc
    hour, minute = (int(x) for x in want.split(":"))
    target = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)

    # The Broker is a network call and this laptop's DNS is intermittently unreliable, so
    # retry before giving up. A wrong answer is worse than a slow one (Section 0, rule 3).
    broker = bgpkit.Broker()
    items: list[Any] = []
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            items = list(
                broker.query(
                    ts_start=f"{day:%Y-%m-%d}T00:00:00Z",
                    ts_end=f"{day:%Y-%m-%d}T23:59:59Z",
                    collector_id=collector,
                    data_type="rib",
                )
            )
            break
        except Exception as exc:  # noqa: BLE001 - any transport error is worth retrying
            last = exc
            time.sleep(2.0 * attempt)
    else:
        raise RibNotFoundError(f"broker lookup failed for {collector} on {day}: {last}")

    if not items:
        raise RibNotFoundError(f"{collector} published no RIB dump on {day}")

    def distance(item: Any) -> float:
        stamp = datetime.fromisoformat(item.ts_start).replace(tzinfo=UTC)
        return abs((stamp - target).total_seconds())

    return str(min(items, key=distance).url)


def table_path(cfg: Config, collector: str, day: date) -> Path:
    """Partitioned by date then collector, so a single day can be read on its own."""
    return (
        cfg.paths.processed
        / "routes"
        / f"snapshot_date={day:%Y-%m-%d}"
        / f"collector={collector}"
        / "routes.parquet"
    )


def stats_path(cfg: Config, collector: str, day: date) -> Path:
    """Sidecar holding the per-collector counts for one run.

    Plan Section 11 Phase 2 asks for a report of routes per collector and the share flagged
    by each normalization rule. The flags themselves are not part of the Section 9 ``routes``
    schema, and recomputing them means re-reading tens of millions of rows, so each run
    leaves its own counts next to the data it wrote.
    """
    return table_path(cfg, collector, day).with_name("stats.json")


def write_stats(cfg: Config, result: CollectorResult) -> Path:
    out = stats_path(cfg, result.collector, result.snapshot_date)
    payload = {
        "collector": result.collector,
        "snapshot_date": result.snapshot_date.isoformat(),
        "url": result.url,
        "rows": result.rows,
        "peers": result.peers,
        "prefixes": result.prefixes,
        "seconds": round(result.seconds, 1),
        "flags": {str(flag): count for flag, count in sorted(result.flags.items())},
        "flag_rates": {
            str(flag): round(count / result.rows, 6) if result.rows else 0.0
            for flag, count in sorted(result.flags.items())
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return out


def read_stats(cfg: Config, collector: str, day: date) -> dict[str, Any] | None:
    path = stats_path(cfg, collector, day)
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _batch_to_table(rows: dict[str, list[Any]]) -> pa.Table:
    return pa.table(rows, schema=ROUTES_SCHEMA)


def _empty_batch() -> dict[str, list[Any]]:
    return {name: [] for name in ROUTES_SCHEMA.names}


def ingest_rib(
    cfg: Config,
    collector: str,
    day: date,
    *,
    url: str | None = None,
    force: bool = False,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    limit: int | None = None,
) -> CollectorResult:
    """Stream one collector's dump into Parquet, normalizing every path on the way.

    ``limit`` stops after that many elements, which is how the test suite and the quick
    smoke runs avoid pulling a full table.
    """
    started = datetime.now(tz=UTC)
    result = CollectorResult(collector=collector, snapshot_date=day)
    out = table_path(cfg, collector, day)
    if out.exists() and not force:
        result.skipped = True
        result.path = out
        result.rows = pq.ParquetFile(out).metadata.num_rows
        return result

    result.url = url or find_rib_url(cfg, collector, day)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temporary file and rename only once the whole dump has been read. A run
    # killed part way through must not leave behind a short file that later looks like a
    # complete cached result: a truncated Parquet file is still a readable Parquet file.
    partial = out.with_name(f"{out.name}.part{os.getpid()}")

    peers: set[str] = set()
    prefixes: set[str] = set()
    batch = _empty_batch()
    writer: pq.ParquetWriter | None = None
    flags = result.flags
    try:
        writer = pq.ParquetWriter(partial, ROUTES_SCHEMA, compression="zstd")
        # Bound methods hoisted out of the loop: this runs tens of millions of times.
        add_collector = batch["collector"].append
        add_peer_ip = batch["peer_ip"].append
        add_peer_asn = batch["peer_asn"].append
        add_prefix = batch["prefix"].append
        add_afi = batch["afi"].append
        add_raw = batch["as_path_raw"].append
        add_path = batch["as_path"].append
        add_set = batch["has_as_set"].append
        add_origin = batch["origin_asn"].append
        add_time = batch["timestamp"].append
        add_date = batch["snapshot_date"].append
        seen_peer = peers.add
        seen_prefix = prefixes.add
        rows = 0

        for elem in bgpkit.Parser(url=result.url):
            if limit is not None and rows >= limit:
                break
            raw = elem.as_path
            peer_asn = elem.peer_asn
            norm = normalize(raw, peer_asn=peer_asn)
            if norm.flags:
                for flag in norm.flags:
                    flags[flag] += 1

            prefix = elem.prefix
            peer_ip = elem.peer_ip
            add_collector(collector)
            add_peer_ip(peer_ip)
            add_peer_asn(peer_asn)
            add_prefix(prefix)
            add_afi(6 if ":" in prefix else 4)
            add_raw(raw)
            add_path(norm.as_path)
            add_set(norm.has_as_set)
            add_origin(norm.origin_asn)
            # Microseconds since the epoch. Building a datetime per row costs far more and
            # pyarrow stores exactly this integer anyway.
            add_time(int(elem.timestamp * 1_000_000))
            add_date(day)

            seen_peer(peer_ip)
            seen_prefix(prefix)
            rows += 1

            if rows % batch_rows == 0:
                writer.write_table(_batch_to_table(batch))
                batch = _empty_batch()
                add_collector = batch["collector"].append
                add_peer_ip = batch["peer_ip"].append
                add_peer_asn = batch["peer_asn"].append
                add_prefix = batch["prefix"].append
                add_afi = batch["afi"].append
                add_raw = batch["as_path_raw"].append
                add_path = batch["as_path"].append
                add_set = batch["has_as_set"].append
                add_origin = batch["origin_asn"].append
                add_time = batch["timestamp"].append
                add_date = batch["snapshot_date"].append

        result.rows = rows
        if batch["prefix"]:
            writer.write_table(_batch_to_table(batch))
    except BaseException:
        if writer is not None:
            writer.close()
            writer = None
        partial.unlink(missing_ok=True)
        raise
    finally:
        if writer is not None:
            writer.close()

    partial.replace(out)

    result.peers = len(peers)
    result.prefixes = len(prefixes)
    result.path = out
    result.seconds = (datetime.now(tz=UTC) - started).total_seconds()
    write_stats(cfg, result)
    return result


def ingest_many(
    cfg: Config,
    collectors: Sequence[str],
    day: date,
    *,
    force: bool = False,
    limit: int | None = None,
    jobs: int = 1,
) -> list[CollectorResult]:
    """Ingest several collectors for one date, optionally in parallel.

    Collectors are independent and each writes its own file, so they parallelise cleanly.
    Separate *processes* rather than threads, because the per-route work is Python and so
    holds the interpreter lock. ``jobs`` also caps how many archives are being downloaded at
    once, which keeps the job polite (plan Section 16).
    """
    results: list[CollectorResult] = []
    if jobs <= 1:
        for collector in collectors:
            results.append(_ingest_guarded(cfg, collector, day, force=force, limit=limit))
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, len(collectors))) as pool:
            futures = [
                pool.submit(_ingest_guarded, cfg, collector, day, force=force, limit=limit)
                for collector in collectors
            ]
            for future in as_completed(futures):
                results.append(future.result())
    order = {name: i for i, name in enumerate(collectors)}
    return sorted(results, key=lambda r: order.get(r.collector, 0))


def _ingest_guarded(
    cfg: Config, collector: str, day: date, *, force: bool, limit: int | None
) -> CollectorResult:
    """Run one collector and turn any failure into a result, not an exception.

    One collector being unreachable must not throw away the work done for the others.
    """
    try:
        return ingest_rib(cfg, collector, day, force=force, limit=limit)
    except Exception as exc:  # noqa: BLE001 - recorded and reported, never swallowed
        return CollectorResult(collector=collector, snapshot_date=day, error=str(exc))
