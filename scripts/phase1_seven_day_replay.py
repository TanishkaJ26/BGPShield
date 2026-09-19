"""Phase 1 acceptance: prove the daily job works seven days in a row.

Plan Section 11 Phase 1 accepts when the ASPA count matches a public reference *and* "the
daily job has run 7 days in a row". The first half passed in Phase 1. The second half has a
part that only the calendar can supply and a part that can be proved now, and this script is
about keeping those two apart honestly.

What the criterion is really testing is not that time passes. It is that the job works
**repeatedly and idempotently on a fresh checkout**. On GitHub Actions every run starts from a
clean clone, and everything under `data/` is gitignored, so a run holds only the single day it
just ingested. The published series survives solely because it is committed to the repository
and each run *merges* into it. If that merge were wrong, the series would never hold more than
one day, and only a multi-day run would reveal it.

So this replays exactly that: seven consecutive dates, each starting from an empty processed
directory, each merging into the one JSON file that carries over. It exercises the real
archive, the real ingester and the real export path.

**What it does not prove:** that seven calendar days have elapsed with the schedule enabled.
That needs the workflow pushed and a week to pass, and nothing here should be read as a
substitute for it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BGPSHIELD = REPO / ".venv" / "Scripts" / "bgpshield.exe"
SCRATCH = REPO / "data" / "interim" / "phase1_replay"
CONFIG = SCRATCH / "replay.yaml"
SERIES = SCRATCH / "aspa_adoption.json"

DAYS = 7


def write_config() -> None:
    """A config identical to the default except that it writes into the scratch tree.

    The raw cache stays shared with the real one. Re-downloading files the project already
    holds would be rude to the archive (plan Section 16) and would measure nothing useful.
    """
    original = (REPO / "config" / "default.yaml").read_text(encoding="utf-8")
    processed = (SCRATCH / "processed").as_posix()
    web = (SCRATCH / "web").as_posix()
    patched = original.replace("  processed: data/processed", f"  processed: {processed}").replace(
        "  web_data: web/public/data", f"  web_data: {web}"
    )
    if f"processed: {processed}" not in patched:
        raise SystemExit("could not patch the processed path in the config")
    CONFIG.write_text(patched, encoding="utf-8")


def run(args: list[str], label: str) -> tuple[bool, str]:
    started = time.time()
    proc = subprocess.run(
        [str(BGPSHIELD), *args, "--config", str(CONFIG)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    ok = proc.returncode == 0
    print(f"    {label}: {'ok' if ok else 'FAILED'} in {time.time() - started:.0f}s", flush=True)
    if not ok:
        print((proc.stdout or "")[-1200:], flush=True)
        print((proc.stderr or "")[-1200:], flush=True)
    return ok, (proc.stdout or "")


def main() -> None:
    # End on the most recent day the archive is sure to hold: yesterday UTC, as the workflow
    # itself defaults to.
    last = date.today() - timedelta(days=1)
    days = [last - timedelta(days=offset) for offset in range(DAYS - 1, -1, -1)]

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    write_config()

    print(f"replaying {DAYS} consecutive days: {days[0]} .. {days[-1]}", flush=True)
    print("each run starts from an empty processed directory, as a fresh checkout would\n")

    failures: list[str] = []
    for index, day in enumerate(days, start=1):
        print(f"[{index}/{DAYS}] {day}", flush=True)

        # A fresh GitHub Actions checkout has no processed data at all. Only the committed
        # JSON carries over, so wipe everything except it.
        processed = SCRATCH / "processed"
        if processed.exists():
            shutil.rmtree(processed)

        ok, _ = run(["ingest-rpki", "--date", str(day)], "ingest-rpki")
        if not ok:
            failures.append(f"{day}: ingest failed")
            continue

        ok, _ = run(["adoption", "--export", str(SERIES)], "adoption --export")
        if not ok:
            failures.append(f"{day}: export failed")
            continue

        payload = json.loads(SERIES.read_text(encoding="utf-8"))
        stored = sorted(row["snapshot_date"] for row in payload.get("by_day", []))
        expected = sorted(str(d) for d in days[:index])
        if stored != expected:
            failures.append(f"{day}: series holds {len(stored)} day(s), expected {len(expected)}")
            print(f"    MERGE WRONG: {stored}", flush=True)
        else:
            latest = payload.get("latest_snapshot")
            aspas = next(
                (r["aspas"] for r in payload["by_day"] if r["snapshot_date"] == str(day)), None
            )
            print(
                f"    series now holds {len(stored)} day(s); latest={latest} aspas={aspas}",
                flush=True,
            )

    print("\n=== PHASE 1, SEVEN CONSECUTIVE DAYS ===")
    if failures:
        print(f"FAILED ({len(failures)}):")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)

    payload = json.loads(SERIES.read_text(encoding="utf-8"))
    rows = sorted(payload["by_day"], key=lambda r: r["snapshot_date"])
    print(f"{DAYS} consecutive daily runs, each from an empty processed directory: all passed")
    print(
        f"series holds {len(rows)} days, {rows[0]['snapshot_date']} .. {rows[-1]['snapshot_date']}"
    )
    for row in rows:
        print(f"  {row['snapshot_date']}  aspas={row['aspas']}")
    print(
        "\nThis proves the job is repeatable and merges correctly on a fresh checkout.\n"
        "It does NOT prove seven calendar days have elapsed with the schedule enabled;\n"
        "that needs the workflow pushed and a week to pass."
    )


if __name__ == "__main__":
    main()
