"""
Heatmap helper for AFRI Terminal (build spec section 5 — the flagship
visual). Turns a flat list of quotes into a sector-grouped heatmap payload
with volume-proportional cell sizes and change-keyed colors.
Python stdlib ONLY. Two responsibilities, both pure/testable:
  1. classify_sector(name, existing) — keyword rules (the spec's
     SECTOR_RULES) to bucket a company by name when no sector is known.
  2. build_heatmap(rows) — group by sector, compute per-cell size (log
     volume scale) and color (redmint gradient on % change), plus
     per-sector rollups (avg change, up/down split, count).
Wire into afri_server.py alongside the existing /api/heatmap route to
supply sector classification and consistent sizing/coloring, or use the
payload shape directly.
Honesty: a cell with no volume gets the minimum size (not hidden, not
faked); a cell with no % change renders neutral gray, never green/red.
"""
import math
# Keyword -> sector. Order matters: first match wins, so more specific
# keywords should precede generic ones. This is the spec's ~50-group
# SECTOR_RULES, condensed to the major buckets that cover the 4 markets.
SECTOR_RULES = [
    (("bank", "banc", "microfin"), "Banks"),
    (("insur", "assurance", "life "), "Insurance"),
    (("reit", "propert", "real estate", "fund "), "REIT / Property"),
    (("gold", "platinum", "mining", "minerals", "resources", "coal", "iron"), "Mining"),
    (("oil", "gas", "petroleum", "energy", "sasol"), "Oil & Gas"),
    (("telecom", "telkom", "mtn", "airtel", "safaricom", "vodacom", "communications"), "Telecom"),
    (("cement", "construct", "build", "steel", "industri"), "Industrials"),
    (("brew", "beer", "distill", "beverage", "food", "sugar", "dairy", "consumer"), "Food & Beverage"),
    (("retail", "stores", "supermarket", "shoprite", "spar"), "Retail"),
    (("tech", "software", "digital", "data", "naspers", "prosus"), "Technology"),
    (("health", "pharma", "hospital", "medical"), "Healthcare"),
    (("media", "broadcast", "publish", "nation"), "Media"),
    (("transport", "logistic", "airline", "airways", "port", "rail"), "Transport"),
    (("agri", "farm", "plantation", "tea", "coffee", "tobacco"), "Agriculture"),
]
MIN_CELL = 46.0   # px, spec section 5
MAX_CELL = 120.0  # px
HEIGHT_RATIO = 0.42
# Change beyond +/- this (%) saturates the color; between, it interpolates.
COLOR_CLAMP = 4.0
def classify_sector(name, existing=None):
    """Return a sector. If an explicit sector is already known (e.g. from
    African Financials for NGX/NSE), trust it. Otherwise keyword-classify
    the company name. Unknown -> 'Other' (honest, not a guess)."""
    if existing and str(existing).strip() and str(existing).strip().lower() != "other":
        return str(existing).strip()
    n = (name or "").lower()
    for keywords, sector in SECTOR_RULES:
        for kw in keywords:
            if kw in n:
                return sector
    return "Other"
def _cell_size(volume, vmax):
    """Log-scaled size between MIN_CELL and MAX_CELL. No/zero volume ->
    minimum size (the cell still shows; it isn't dropped or faked)."""
    if not volume or volume <= 0 or not vmax or vmax <= 0:
        return MIN_CELL
    # log scale so a few huge-volume names don't dwarf everything.
    frac = math.log10(volume + 1) / math.log10(vmax + 1)
    frac = max(0.0, min(1.0, frac))
    return round(MIN_CELL + frac * (MAX_CELL - MIN_CELL), 1)
def cell_color(chg_pct):
    """Red (down)  dark gray (flat/none)  mint (up). Returns a hex string.
    None -> neutral gray, never a directional color."""
    if chg_pct is None:
        return "#2a2a2a"
    c = max(-COLOR_CLAMP, min(COLOR_CLAMP, chg_pct))
    if c >= 0:
        # interpolate #141414 -> #33e29a as 0 -> +clamp
        t = c / COLOR_CLAMP
        return _lerp_hex("#141414", "#33e29a", t)
    else:
        t = (-c) / COLOR_CLAMP
        return _lerp_hex("#141414", "#f87171", t)
def _lerp_hex(a, b, t):
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return "#{:02x}{:02x}{:02x}".format(r, g, bl)
def build_heatmap(rows):
    """
    rows: list of {sym, ticker, name, chgPct, volume, sector?}
    Returns sectors[] each with cells[] (size/color computed) and rollups.
    Sectors sorted by total volume desc; cells within a sector by volume desc.
    """
    vmax = 0
    enriched = []
    for r in rows:
        sector = classify_sector(r.get("name"), r.get("sector"))
        vol = r.get("volume") or 0
        vmax = max(vmax, vol)
        enriched.append({
            "sym": r.get("sym"),
            "ticker": r.get("ticker") or (r.get("sym") or "").split(".")[0],
            "name": r.get("name"),
            "chgPct": r.get("chgPct"),
            "volume": vol,
            "sector": sector,
        })
    buckets = {}
    for e in enriched:
        buckets.setdefault(e["sector"], []).append(e)
    sectors_out = []
    for sector, cells in buckets.items():
        for c in cells:
            c["size"] = _cell_size(c["volume"], vmax)
            c["color"] = cell_color(c["chgPct"])
        cells.sort(key=lambda c: c["volume"], reverse=True)
        changes = [c["chgPct"] for c in cells if c["chgPct"] is not None]
        ups = sum(1 for x in changes if x > 0)
        downs = sum(1 for x in changes if x < 0)
        avg = round(sum(changes) / len(changes), 2) if changes else None
        sectors_out.append({
            "sector": sector,
            "count": len(cells),
            "avgChange": avg,
            "up": ups,
            "down": downs,
            "totalVolume": sum(c["volume"] for c in cells),
            "cells": cells,
        })
    sectors_out.sort(key=lambda s: s["totalVolume"], reverse=True)
    return {"sectors": sectors_out, "count": len(enriched)}