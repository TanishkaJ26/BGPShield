"""Phase 0 probe: when do ASPA records first appear in the RIPE NCC RPKI archive?

Downloads ``output.json.xz`` (Routinator JSON) for the 1st of every month from
2023-10 (ASPA enabled per the archive changelog on 2023-10-10) to today, for
each of the five trust anchors, and records the number of ``aspas`` and ``roas``
entries per (date, TA). Files are cached under data/raw/samples/ripe-rpki/.

Plain-English: a trust anchor (TA) is the root certificate of one RIR's RPKI
tree (RFC 6480 §2.4). Every ROA/ASPA object hangs under exactly one TA.
"""

from __future__ import annotations

import csv
import json
import lzma
import sys
import time
from datetime import date
from pathlib import Path

import requests

UA = "hijax-phase0/0.1 (research; tanishkajangir26@gmail.com)"
BASE = "https://ftp.ripe.net/rpki"
TAS = ["afrinic", "apnic", "arin", "lacnic", "ripencc"]
CACHE = Path("data/raw/samples/ripe-rpki/monthly")
OUT = Path("data/interim/phase0/ripe_archive_aspa_counts.csv")


def month_starts(start: date, end: date) -> list[date]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch(ta: str, d: date, sess: requests.Session) -> Path | None:
    dest = CACHE / f"{ta}.tal" / f"{d:%Y%m%d}.output.json.xz"
    if dest.exists():
        return dest
    url = f"{BASE}/{ta}.tal/{d:%Y/%m/%d}/output.json.xz"
    r = sess.get(url, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def main() -> None:
    dates = month_starts(date(2023, 10, 1), date.today())
    # first day ASPA JSON exists per changelog is 2023-10-11; add it explicitly
    dates = [date(2023, 10, 11)] + [d for d in dates if d > date(2023, 10, 11)]
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in dates:
        for ta in TAS:
            try:
                p = fetch(ta, d, sess)
            except Exception as e:  # noqa: BLE001 - probe script, report and continue
                rows.append([d.isoformat(), ta, "ERROR", "", "", str(e)[:80]])
                print(d, ta, "ERROR", e, flush=True)
                continue
            if p is None:
                rows.append([d.isoformat(), ta, "MISSING", "", "", ""])
                print(d, ta, "missing", flush=True)
                continue
            with lzma.open(p) as f:
                j = json.load(f)
            n_aspa = len(j.get("aspas", []))
            n_roa = len(j.get("roas", []))
            has_key = "aspas" in j
            rows.append([d.isoformat(), ta, "OK", n_roa, n_aspa, f"aspas_key={has_key}"])
            print(d, ta, "roas", n_roa, "aspas", n_aspa, flush=True)
            time.sleep(0.5)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "ta", "status", "n_roas", "n_aspas", "note"])
        w.writerows(rows)
    print("wrote", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
