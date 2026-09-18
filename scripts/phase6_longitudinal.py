"""Phase 6: a quarterly longitudinal sweep of ROV, ASPA and leak aggregates.

Plan Section 11 Phase 6 asks for RIB snapshots across the whole period turned into
aggregates over time. The RPKI side already spans 155 weekly snapshots; this fills in the
BGP side, which is the expensive half.

Two deliberate reductions, both recorded in docs/methodology.md:

* **Quarterly, not weekly.** A weekly BGP sweep over three years is ~150 table dumps.
* **One collector.** route-views2 in Oregon, the collector Phases 4 and 5 already used, so
  the series is comparable with them.

A download budget guard stops the sweep before it can exceed the limit that CLAUDE.md rule 8
says to ask the owner about, so the script can never quietly cross it.

**The guard measures the MRT dumps over the network, not disk growth.** bgpkit streams each
routing-table dump straight from the archive URL and never caches it under `data/raw`, so
watching the raw directory would have measured almost nothing. The guard instead asks each
dump's URL for its `Content-Length` before ingesting and accumulates that, plus any growth in
`data/raw` from the CAIDA files. Measured on 2026-09-18, a route-views2 dump runs 104 MB in
2023 down to 76 MB in 2026, so the full thirteen-date sweep is about 1.17 GB.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import requests

from hijax.config import load_config
from hijax.ingest.bgp import find_rib_url

REPO = Path(__file__).resolve().parent.parent
HIJAX = REPO / ".venv" / "Scripts" / "hijax.exe"
RAW = REPO / "data" / "raw"
OUT = REPO / "data" / "processed" / "longitudinal"

COLLECTOR = "route-views2"
BUDGET_BYTES = 4_500_000_000
"""Stop before CLAUDE.md rule 8's 5 GB ask-the-owner threshold."""

ASSUMED_RIB_BYTES = 150_000_000
"""Charged against the budget when a dump's size cannot be read, so an unmeasurable
download is treated as expensive rather than free."""

DATES = [
    "2023-10-11",
    "2024-01-03",
    "2024-04-03",
    "2024-07-03",
    "2024-10-02",
    "2025-01-01",
    "2025-04-02",
    "2025-07-02",
    "2025-10-01",
    "2026-01-07",
    "2026-04-01",
    "2026-07-01",
    "2026-09-16",
]


def raw_bytes() -> int:
    """Bytes in the raw cache. Covers the CAIDA files but never the streamed MRT dumps."""
    if not RAW.exists():
        return 0
    return sum(f.stat().st_size for f in RAW.rglob("*") if f.is_file())


def rib_bytes(day: date) -> int:
    """What the routing-table dump for one date will cost to download.

    bgpkit streams the dump straight from the archive and never writes it to `data/raw`, so
    asking the server first is the only way to count it against the budget.
    """
    try:
        url = find_rib_url(load_config(REPO / "config" / "default.yaml"), COLLECTOR, day)
        response = requests.head(url, allow_redirects=True, timeout=60)
        return int(response.headers.get("Content-Length", 0)) or ASSUMED_RIB_BYTES
    except Exception as exc:  # a failed lookup must not be read as "free"
        print(f"    could not size the dump ({exc}); charging {ASSUMED_RIB_BYTES / 1e6:.0f} MB")
        return ASSUMED_RIB_BYTES


def previous_month(day: date) -> str:
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def run(args: list[str], label: str) -> tuple[bool, str]:
    started = time.time()
    proc = subprocess.run(
        [str(HIJAX), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    took = time.time() - started
    ok = proc.returncode == 0
    print(f"    {label}: {'ok' if ok else 'FAILED'} in {took / 60:.1f} min", flush=True)
    if not ok:
        print((proc.stdout or "")[-1500:], flush=True)
        print((proc.stderr or "")[-1500:], flush=True)
    return ok, (proc.stdout or "")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    start_bytes = raw_bytes()
    print(f"raw data before sweep: {start_bytes / 1e9:.2f} GB", flush=True)
    log: list[dict[str, object]] = []
    downloaded_ribs = 0

    for index, iso in enumerate(DATES, start=1):
        day = date.fromisoformat(iso)
        used = (raw_bytes() - start_bytes) + downloaded_ribs
        print(
            f"\n[{index}/{len(DATES)}] {iso}  (downloaded {used / 1e9:.2f} GB so far)", flush=True
        )
        if used > BUDGET_BYTES:
            print("BUDGET REACHED - stopping before the 5 GB ask-the-owner threshold.", flush=True)
            break

        this_rib = rib_bytes(day)
        if used + this_rib > BUDGET_BYTES:
            print("BUDGET would be exceeded by this dump - stopping.", flush=True)
            break

        entry: dict[str, object] = {"date": iso, "collector": COLLECTOR}
        month = previous_month(day)

        meta_dir = REPO / "data" / "processed" / "as_meta" / f"month={month}"
        if not (meta_dir / "as_meta.parquet").exists():
            ok, _ = run(["ingest-meta", "--month", month], f"meta {month}")
            entry["meta_ok"] = ok
            if not ok:
                entry["stopped"] = "metadata unavailable"
                log.append(entry)
                continue

        downloaded_ribs += this_rib
        entry["rib_bytes"] = this_rib
        ok, _ = run(["ingest-bgp", "--date", iso, "--collectors", COLLECTOR], "ingest-bgp")
        entry["ingest_ok"] = ok
        if not ok:
            entry["stopped"] = "ingest failed"
            log.append(entry)
            continue

        ok, out = run(["validate", "--date", iso, "--collectors", COLLECTOR], "validate")
        entry["validate_ok"] = ok
        entry["validate_output"] = out[-3000:]

        ok, out = run(["detect", "--date", iso, "--collectors", COLLECTOR], "detect")
        entry["detect_ok"] = ok
        entry["detect_output"] = out[-3000:]

        log.append(entry)
        (OUT / "sweep_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")

    (OUT / "sweep_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    done = sum(1 for e in log if e.get("detect_ok"))
    print(f"\nsweep finished: {done} of {len(DATES)} dates fully processed", flush=True)
    total = (raw_bytes() - start_bytes) + downloaded_ribs
    print(f"downloaded this sweep: {total / 1e9:.2f} GB", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
