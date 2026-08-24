"""
/api/bonds — Bonds & T-Bills board for AFRI Terminal (spec 9.2, P2).
Per-country sovereign-debt yield table: Kenya, Nigeria, South Africa,
Egypt. Unlike quotes/commodities, there is NO free real-time API for
African sovereign yields — the spec is explicit that these are curated
from central-bank auction results, updated on announcements. So this
handler does NOT pretend to fetch live data: it reads the curated
bonds.json and stamps each instrument with an honest freshness label
computed from its own as_of date.
Python stdlib ONLY. Wire into afri_server.py:
    from bonds_api import handle_bonds
    ...
    if parsed.path == "/api/bonds":
        return self._send_json(handle_bonds())
The value of this feature is trust, not speed: showing a real curated
yield clearly stamped "as of 18 Aug" beats showing a fake live number.
The staleness flag lets the UI warn when a figure is getting old so
nobody trades off a month-old auction thinking it's today's.
"""
import datetime
import json
import os
BONDS_FILE = os.path.join(os.path.dirname(__file__), "bonds.json")
# Beyond this many days since an instrument's auction, flag it stale so
# the UI can visually warn. T-bill auctions are typically weekly; 14 days
# is a conservative "this may be out of date" threshold.
STALE_AFTER_DAYS = 14
def _days_since(as_of):
    try:
        d = datetime.date.fromisoformat(as_of)
    except (ValueError, TypeError):
        return None
    return (datetime.date.today() - d).days
def _freshness_label(days):
    if days is None:
        return "date unknown"
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < STALE_AFTER_DAYS:
        return "{} days ago".format(days)
    return "{} days ago — may be out of date".format(days)
def handle_bonds(bonds_file=BONDS_FILE):
    try:
        with open(bonds_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # No curated file / bad JSON — return an honest empty board, not
        # invented yields.
        return {
            "count": 0,
            "countries": [],
            "note": "Curated bond data unavailable (bonds.json missing or invalid).",
        }
    countries_out = []
    total_instruments = 0
    oldest_days = None
    for country in data.get("countries", []):
        instruments_out = []
        for inst in country.get("instruments", []):
            days = _days_since(inst.get("as_of"))
            if days is not None:
                oldest_days = days if oldest_days is None else max(oldest_days, days)
            instruments_out.append({
                "name": inst.get("name"),
                "tenor": inst.get("tenor"),
                "yield": inst.get("yield"),
                "as_of": inst.get("as_of"),
                "freshness": _freshness_label(days),
                "stale": days is not None and days >= STALE_AFTER_DAYS,
            })
            total_instruments += 1
        countries_out.append({
            "iso": country.get("iso"),
            "country": country.get("country"),
            "source": country.get("source"),
            "source_url": country.get("source_url"),
            "instruments": instruments_out,
        })
    return {
        "count": total_instruments,
        "countries": countries_out,
        # Honest, prominent: this board is curated, not live.
        "note": "Curated from central-bank auction results — not a live feed. "
                "Each instrument shows its own auction date; update bonds.json on new auctions.",
        "oldest_days": oldest_days,
    }