"""
Technical indicators for AFRI Terminal charts (spec section 6, P1).
Pure functions over a list of closing prices. Python stdlib ONLY, no
numpy — matches the architecture note and keeps afri_server.py
dependency-free. Every function returns a list aligned to the input
(None-padded where an indicator isn't defined yet), so the frontend can
zip it straight onto the price series without index math.
Wire into afri_server.py, e.g. extend the existing chart endpoint:
    from indicators import sma, ema, rsi, macd, bollinger
    closes = [bar["close"] for bar in bars]
    payload["indicators"] = {
        "sma20": sma(closes, 20),
        "ema12": ema(closes, 12),
        "rsi14": rsi(closes, 14),
        "macd":  macd(closes),
        "boll":  bollinger(closes, 20, 2),
    }
Honesty: where an indicator needs N prior points it returns None for
those leading positions rather than a wrong partial value. Non-numeric
or missing closes are skipped-as-None, never guessed.
"""
from typing import List, Optional
Number = Optional[float]
def _clean(values):
    """Coerce to floats; anything non-numeric becomes None (not dropped,
    so index alignment with the price series is preserved)."""
    out = []
    for v in values:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(None)
    return out
def sma(closes: List[Number], period: int) -> List[Number]:
    """Simple moving average. First (period-1) entries are None."""
    closes = _clean(closes)
    out: List[Number] = [None] * len(closes)
    if period <= 0:
        return out
    window = []
    running = 0.0
    for i, c in enumerate(closes):
        if c is None:
            # A gap resets the window — we won't average across a hole.
            window = []
            running = 0.0
            continue
        window.append(c)
        running += c
        if len(window) > period:
            running -= window.pop(0)
        if len(window) == period:
            out[i] = round(running / period, 6)
    return out
def ema(closes: List[Number], period: int) -> List[Number]:
    """Exponential moving average, seeded with the SMA of the first
    `period` valid points (standard convention)."""
    closes = _clean(closes)
    out: List[Number] = [None] * len(closes)
    if period <= 0:
        return out
    k = 2.0 / (period + 1.0)
    prev: Number = None
    seed_window = []
    for i, c in enumerate(closes):
        if c is None:
            continue
        if prev is None:
            seed_window.append((i, c))
            if len(seed_window) == period:
                seed_val = sum(v for _, v in seed_window) / period
                prev = seed_val
                out[i] = round(seed_val, 6)
        else:
            prev = c * k + prev * (1 - k)
            out[i] = round(prev, 6)
    return out
def rsi(closes: List[Number], period: int = 14) -> List[Number]:
    """Relative Strength Index (Wilder's smoothing). 0-100. Leading
    positions before enough data are None."""
    closes = _clean(closes)
    out: List[Number] = [None] * len(closes)
    if period <= 0:
        return out
    gains, losses = [], []
    avg_gain = avg_loss = None
    prev_close = None
    count = 0
    for i, c in enumerate(closes):
        if c is None:
            prev_close = None
            continue
        if prev_close is None:
            prev_close = c
            continue
        change = c - prev_close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        prev_close = c
        count += 1
        if count <= period:
            gains.append(gain)
            losses.append(loss)
            if count == period:
                avg_gain = sum(gains) / period
                avg_loss = sum(losses) / period
                out[i] = _rsi_from(avg_gain, avg_loss)
        else:
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            out[i] = _rsi_from(avg_gain, avg_loss)
    return out
def _rsi_from(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 4)
def macd(closes: List[Number], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    MACD line, signal line, histogram. Returns dict of three aligned
    lists. MACD = EMA(fast) - EMA(slow); signal = EMA(MACD, signal);
    histogram = MACD - signal.
    """
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    macd_line: List[Number] = []
    for f, s in zip(fast_e, slow_e):
        macd_line.append(round(f - s, 6) if (f is not None and s is not None) else None)
    # Signal EMA over the defined portion of the MACD line.
    signal_line = ema(macd_line, signal)
    hist: List[Number] = []
    for m, sg in zip(macd_line, signal_line):
        hist.append(round(m - sg, 6) if (m is not None and sg is not None) else None)
    return {"macd": macd_line, "signal": signal_line, "histogram": hist}
def bollinger(closes: List[Number], period: int = 20, mult: float = 2.0) -> dict:
    """Bollinger Bands: middle = SMA(period); upper/lower = middle +/-
    mult * population stddev over the same window."""
    closes = _clean(closes)
    mid = sma(closes, period)
    upper: List[Number] = [None] * len(closes)
    lower: List[Number] = [None] * len(closes)
    window = []
    for i, c in enumerate(closes):
        if c is None:
            window = []
            continue
        window.append(c)
        if len(window) > period:
            window.pop(0)
        if len(window) == period and mid[i] is not None:
            mean = mid[i]
            var = sum((x - mean) ** 2 for x in window) / period
            sd = var ** 0.5
            upper[i] = round(mean + mult * sd, 6)
            lower[i] = round(mean - mult * sd, 6)
    return {"middle": mid, "upper": upper, "lower": lower}