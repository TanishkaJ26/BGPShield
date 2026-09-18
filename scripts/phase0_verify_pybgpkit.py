"""Phase 0 check: confirm the pybgpkit API on real MRT samples (plan Section 11).

Plain-English: MRT (RFC 6396) is the on-disk format route collectors use to
dump BGP messages. An "updates" file holds the BGP UPDATE messages received in
a 5- or 15-minute window; a RIB dump ("bview"/"rib") holds every route the
collector knew at one instant. Each parsed element carries the prefix, the
AS_PATH (as received: neighbour first, origin last) and the peer that sent it.

Run: uv run python scripts/phase0_verify_pybgpkit.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import bgpkit
import requests

UA = "hijax-phase0/0.1 (research; tanishkajangir26@gmail.com)"
SAMPLES = Path("data/raw/samples/mrt")

print("bgpkit module:", bgpkit.__file__)
print("attrs:", [a for a in dir(bgpkit) if not a.startswith("_")])

# 1. Parser iteration over every sample (two updates files, two RIB dumps).
for f in sorted(SAMPLES.iterdir()):
    print(f"\n=== {f.name}")
    n = 0
    kinds: Counter[str] = Counter()
    peers: set[tuple[str, int]] = set()
    first = None
    for elem in bgpkit.Parser(url=str(f)):
        if first is None:
            first = elem
        n += 1
        kinds[str(elem.elem_type)] += 1
        peers.add((elem.peer_ip, elem.peer_asn))
    print("elements:", n, "by type:", dict(kinds), "distinct peers:", len(peers))
    if first is not None:
        print("fields:", [a for a in dir(first) if not a.startswith("_")])
        print("first element:", first)

# 2. Filters: restrict to one peer ASN and one prefix on the RouteViews updates sample.
rv = SAMPLES / "updates.20260901.0000.bz2"
peer_only = list(bgpkit.Parser(url=str(rv), filters={"peer_asn": "57866"}))
print(
    "\nfilter peer_asn=57866 ->",
    len(peer_only),
    "elements; all match:",
    all(e.peer_asn == 57866 for e in peer_only),
)
pfx_only = list(bgpkit.Parser(url=str(rv), filters={"prefix": "5.42.164.0/22"}))
print("filter prefix=5.42.164.0/22 ->", len(pfx_only), "elements")
ipv4_only = list(bgpkit.Parser(url=str(rv), filters={"ip_version": "ipv4"}))
print("filter ip_version=ipv4 ->", len(ipv4_only), "elements")

# 3. Broker: discover file URLs by time window and collector.
broker = bgpkit.Broker()
items = broker.query(
    ts_start="2026-09-01T00:00:00Z", ts_end="2026-09-01T00:10:00Z", collector_id="rrc00"
)
print("\nbroker.query rrc00 ->", len(items), "items")
for it in items:
    print("  ", it)

# 4. Collector list. pybgpkit 0.8.0's Broker.collectors() crashes because the API
#    now returns a 'data_url' key that CollectorItem does not accept; call the REST
#    endpoint directly instead (documented in docs/data-sources.md).
try:
    broker.collectors()
    print("broker.collectors() works")
except TypeError as e:
    print("broker.collectors() BUG:", e)
r = requests.get(
    "https://api.bgpkit.com/v3/broker/collectors", headers={"User-Agent": UA}, timeout=60
)
r.raise_for_status()
cols = r.json()["data"]
print("REST collectors:", len(cols), "keys:", list(cols[0].keys()))
