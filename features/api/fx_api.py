"""
/api/fx — FX cross-rate matrix for AFRI Terminal.
Builds an NxN cross-rate table across the African market currencies plus
the majors (USD/EUR/GBP), from a set of USD-base rates. Cross rates are
triangulated through USD:  rate(A->B) = usd_per_A? — no: we store
"units of currency per 1 USD" and derive A->B = (per_USD[B] / per_USD[A]).
Python stdlib ONLY. The USD-base rates come from whatever feed
afri_server.py already uses for its FX pairs (the spec notes 6 FX pairs
already work); this module only does the triangulation + matrix shaping,
which is the part worth testing. Wire in:
    from fx_api import build_matrix, convert
    if parsed.path == "/api/fx":
        return self._send_json(build_matrix(usd_rates))   # usd_rates: {ccy: units_per_usd}
Honesty: a currency with no rate is included in the matrix but its cells
are null (never guessed). The diagonal is exactly 1.0 by construction.
"""
from typing import Dict, Optional
# Display order + labels. Africa first (the point of the product), then majors.
CURRENCIES = [
    ("KES", "Kenyan Shilling"),
    ("NGN", "Nigerian Naira"),
    ("ZAR", "South African Rand"),
    ("EGP", "Egyptian Pound"),
    ("USD", "US Dollar"),
    ("EUR", "Euro"),
    ("GBP", "British Pound"),
]
def _rate(usd_rates: Dict[str, float], frm: str, to: str) -> Optional[float]:
    """units of `to` per 1 unit of `frm`, triangulated through USD.
    usd_rates maps currency -> units per 1 USD (so USD itself is 1.0).
    frm->to = per_usd[to] / per_usd[frm].
    """
    a = usd_rates.get(frm)
    b = usd_rates.get(to)
    if a is None or b is None or a == 0:
        return None
    if frm == to:
        return 1.0
    return b / a
def convert(amount: float, frm: str, to: str, usd_rates: Dict[str, float]) -> Optional[float]:
    r = _rate(usd_rates, frm, to)
    if r is None:
        return None
    try:
        return float(amount) * r
    except (TypeError, ValueError):
        return None
def build_matrix(usd_rates: Dict[str, float]) -> dict:
    """
    Full cross-rate matrix. Each row = base currency, each cell = units of
    the column currency per 1 unit of the row currency. Diagonal is 1.0;
    missing rates are null.
    """
    codes = [c for c, _ in CURRENCIES]
    rows = []
    for frm in codes:
        cells = []
        for to in codes:
            r = _rate(usd_rates, frm, to)
            cells.append({
                "to": to,
                "rate": round(r, 6) if r is not None else None,
            })
        rows.append({
            "base": frm,
            "name": dict(CURRENCIES)[frm],
            "has_rate": usd_rates.get(frm) is not None,
            "cells": cells,
        })
    return {
        "currencies": [{"code": c, "name": n} for c, n in CURRENCIES],
        "matrix": rows,
        "note": "Cross rates triangulated via USD. Currencies without a "
                "source rate show blank cells rather than an estimate.",
    }