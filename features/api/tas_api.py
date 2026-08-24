"""
/api/tas — Time & Sales (trade tape) for AFRI Terminal (spec 9.4, P2).
HONEST SCOPE (read first): true tick-by-tick trade prints are not in any
free feed for these markets. What IS available is intraday OHLCV bars
(1m/5m) from Yahoo for JSE/EGX during session. So this module derives a
*bar-level tape* — one row per intraday bar (time, close as print price,
bar volume, up/down vs prior) — and labels it honestly as bar-derived,
NOT raw trade prints. For NGX/NSE (EOD only, no intraday) it returns an
explicit "no intraday tape" state rather than fabricating trades.
This is the honest version of the feature: a real derived tape beats a
fake stream of invented ticks. Never fabricates prints.
Python stdlib ONLY. Wire into afri_server.py:
    from tas_api import build_tape
    if parsed.path == "/api/tas":
        bars = self._intraday_bars(symbol)   # [{t, close, volume}], may be []
        return self._send_json(build_tape(symbol, bars, is_intraday_market))
"""
from typing import List, Optional
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
def build_tape(symbol: str, bars: List[dict], intraday_available: bool = True, limit: int = 100) -> dict:
    """
    bars: list of {t (epoch or iso), close, volume} in chronological order.
    Returns a tape (most-recent first) of bar-derived prints with an
    up/down tick flag vs the previous bar's close.
    If no intraday data (EOD market or empty bars), returns an honest
    empty tape with a reason — never invented trades.
    """
    if not intraday_available:
        return {
            "symbol": symbol,
            "available": False,
            "reason": "This market is end-of-day only; no intraday tape available.",
            "source": "n/a",
            "prints": [],
        }
    clean = []
    for b in bars:
        c = _f(b.get("close"))
        v = _f(b.get("volume"))
        if c is None:
            continue  # skip bars with no price, don't guess one
        clean.append({"t": b.get("t"), "close": c, "volume": v})
    if not clean:
        return {
            "symbol": symbol,
            "available": False,
            "reason": "No intraday bars returned (market may be closed with no session data).",
            "source": "Yahoo intraday",
            "prints": [],
        }
    prints = []
    prev_close = None
    cum_vol = 0.0
    for row in clean:
        tick = None
        if prev_close is not None:
            if row["close"] > prev_close:
                tick = "up"
            elif row["close"] < prev_close:
                tick = "down"
            else:
                tick = "flat"
        if row["volume"] is not None:
            cum_vol += row["volume"]
        prints.append({
            "t": row["t"],
            "price": round(row["close"], 6),
            "volume": row["volume"],           # may be None — shown as "—", not 0
            "cumVolume": round(cum_vol, 2) if row["volume"] is not None else None,
            "tick": tick,                       # up / down / flat / None (first bar)
        })
        prev_close = row["close"]
    prints.reverse()  # most recent first
    return {
        "symbol": symbol,
        "available": True,
        "reason": None,
        "source": "Yahoo intraday bars (bar-derived tape, not raw trade prints)",
        "count": len(prints),
        "prints": prints[:limit],
    }