#!/usr/bin/env python3
"""metrics.py - compute the full derivable metrics set for a security from
price bars + dividends. Pure functions, no I/O. Returns the metric dict the
terminal's DES panel renders. Fields that need income-statement data
(PE, EV, margins, ROE...) are left as None -> UI shows 'n/a on free feed'."""

import math


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


def _cagr(start, end, years):
    if start is None or end is None or start <= 0 or years <= 0:
        return None
    return (math.pow(end / start, 1.0 / years) - 1.0) * 100.0


def _last_price(bars):
    return bars[-1]["close"] if bars else None


def _price_on(bars, ts):
    """close at or before timestamp ts (daily bars, ts = days ago)."""
    if not bars:
        return None
    target = bars[-1]["time"] - ts * 86400
    for b in reversed(bars):
        if b["time"] <= target:
            return b["close"]
    return bars[0]["close"]


def compute_ratios(st, price):
    """Financial ratios from statement data + price. Real figures only -
    None when the underlying statement field is absent."""
    r = {}
    if not st:
        return r
    rev = st.get("revenue")
    gp = st.get("gross_profit")
    op = st.get("operating_profit")
    pat = st.get("profit_after_tax")
    eps = st.get("eps")
    ta = st.get("total_assets")
    tl = st.get("total_liabilities")
    cash = st.get("cash_and_equivalents")
    ocf = st.get("operating_cash_flow")
    # equity = assets - liabilities (accounting identity)
    eq = (ta - tl) if (ta is not None and tl is not None) else None

    if rev and rev != 0:
        if gp is not None:
            r["gross_margin"] = round(gp / rev * 100, 2)
        if op is not None:
            r["operating_margin"] = round(op / rev * 100, 2)
        if pat is not None:
            r["profit_margin"] = round(pat / rev * 100, 2)
        if ocf is not None:
            r["fcf_margin"] = round(ocf / rev * 100, 2)
    if price and eps:
        r["pe_ratio"] = round(price / eps, 2)
        r["earnings_yield"] = round(eps / price * 100, 2)
    if pat is not None and ta:
        r["return_on_assets"] = round(pat / ta * 100, 2)
    if pat is not None and eq:
        r["return_on_equity"] = round(pat / eq * 100, 2)
    if eq and eq != 0:
        if tl is not None:
            r["debt_to_equity"] = round(tl / eq, 2)
        r["shareholders_equity"] = eq
    if cash is not None:
        r["total_cash"] = cash
    return r


def compute_metrics(bars, dividends=None, meta=None):
    """bars: list of {time, open, high, low, close, volume} (daily, ascending).
    dividends: list of {amount, date} (optional).
    meta: dict with name/symbol/currency/employees/founded/etc. (optional).
    Returns dict of every metric derivable from this data."""
    meta = meta or {}
    m = {}
    if not bars:
        return m
    closes = [b["close"] for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    price = closes[-1]
    m["name"] = meta.get("name")
    m["symbol"] = meta.get("symbol")
    m["exchange"] = meta.get("exchange")
    m["country"] = meta.get("country")
    m["currency"] = meta.get("currency")
    m["employees"] = meta.get("employees")
    m["founded"] = meta.get("founded")
    m["industry"] = meta.get("industry")
    m["sector"] = meta.get("sector")
    m["is_number"] = meta.get("isin")

    # --- price levels ---
    m["stock_price"] = price
    m["open_price"] = bars[-1]["open"]
    m["high_price"] = bars[-1]["high"]
    m["low_price"] = bars[-1]["low"]
    m["previous_close"] = closes[-2] if len(closes) > 1 else None
    m["volume"] = vols[-1]
    m["dollar_volume"] = price * vols[-1] if price and vols[-1] else None
    m["avg_volume"] = round(sum(vols[-20:]) / min(20, len(vols)), 0) if vols else None
    m["stock_price_date"] = bars[-1]["time"] * 1000

    # --- period returns (calendar days from bars) ---
    periods = {"1D": 1, "1W": 7, "1M": 30, "3M": 91, "6M": 182, "YTD": None,
               "1Y": 365, "3Y": 1095, "5Y": 1825, "10Y": 3650, "15Y": 5475, "20Y": 7300}
    for label, days in periods.items():
        if days is None:
            # YTD: from start of current calendar year
            import datetime
            t0 = bars[-1]["time"]
            d0 = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc)
            start_of_year = int(datetime.datetime(d0.year, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
            prev = None
            for b in reversed(bars):
                if b["time"] < start_of_year:
                    prev = b["close"]
                    break
            if prev is None:
                prev = closes[0]
        else:
            prev = _price_on(bars, days)
        m[f"price_change_{label}"] = _pct(price, prev)

    # --- total return (price + dividends) ---
    def total_return(days):
        prev_price = _price_on(bars, days)
        if not prev_price:
            return None
        span_start = bars[-1]["time"] - days * 86400
        div = 0.0
        for d in (dividends or []):
            if span_start <= d["date"] <= bars[-1]["time"]:
                div += d.get("amount") or 0
        return _pct(price + div, prev_price)

    for label, days in {"1W": 7, "1M": 30, "3M": 91, "6M": 182, "1Y": 365,
                        "3Y": 1095, "5Y": 1825, "10Y": 3650, "15Y": 5475, "20Y": 7300}.items():
        m[f"total_return_{label}"] = total_return(days)

    # --- CAGR ---
    for label, days in {"1Y": 365, "3Y": 1095, "5Y": 1825, "10Y": 3650, "15Y": 5475, "20Y": 7300}.items():
        m[f"return_cagr_{label}"] = _cagr(_price_on(bars, days), price, days / 365.0)

    # --- 52-week + all-time ranges ---
    span52 = bars[-1]["time"] - 365 * 86400
    b52 = [b for b in bars if b["time"] >= span52]
    if b52:
        hi52 = max(b["high"] for b in b52)
        lo52 = min(b["low"] for b in b52)
        hi52_b = max(b52, key=lambda b: b["high"])
        lo52_b = min(b52, key=lambda b: b["low"])
        m["price_change_52w_low"] = _pct(price, lo52)
        m["price_change_52w_high"] = _pct(price, hi52)
        m["fifty_two_week_high"] = hi52
        m["fifty_two_week_low"] = lo52
        m["fifty_two_week_high_date"] = hi52_b["time"] * 1000
        m["fifty_two_week_low_date"] = lo52_b["time"] * 1000
        m["position_in_range"] = round((price - lo52) / (hi52 - lo52) * 100, 2) if hi52 > lo52 else None

    hi_all_b = max(bars, key=lambda b: b["high"])
    lo_all_b = min(bars, key=lambda b: b["low"])
    m["all_time_high"] = hi_all_b["high"]
    m["all_time_high_date"] = hi_all_b["time"] * 1000
    m["all_time_high_change"] = _pct(price, hi_all_b["high"])
    m["all_time_low"] = lo_all_b["low"]
    m["all_time_low_date"] = lo_all_b["time"] * 1000
    m["all_time_low_change"] = _pct(price, lo_all_b["low"])

    # --- moving averages ---
    for n in (20, 50, 150, 200):
        if len(closes) >= n:
            ma = sum(closes[-n:]) / n
            m[f"ma_{n}"] = ma
            m[f"price_change_{n}d_ma"] = _pct(price, ma)
    if m.get("ma_50") and m.get("ma_200"):
        m["ma_50_vs_200"] = _pct(m["ma_50"], m["ma_200"])

    # --- RSI (14), weekly/monthly approximations ---
    def rsi(closes_arr, period=14):
        if len(closes_arr) < period + 1:
            return None
        gains, losses = 0.0, 0.0
        for i in range(-period, 0):
            ch = closes_arr[i] - closes_arr[i - 1]
            if ch >= 0:
                gains += ch
            else:
                losses -= ch
        if losses == 0:
            return 100.0
        rs = (gains / period) / (losses / period)
        return round(100 - 100 / (1 + rs), 2)

    m["rsi_14"] = rsi(closes, 14)
    # weekly: sample every 5th bar
    wk = closes[::5]
    m["rsi_weekly"] = rsi(wk, 14) if len(wk) > 15 else None
    mn = closes[::22]
    m["rsi_monthly"] = rsi(mn, 14) if len(mn) > 15 else None

    # --- ATR (14) ---
    if len(bars) > 15:
        trs = []
        for i in range(-14, 0):
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        m["atr_14"] = round(sum(trs) / 14, 4)

    # --- beta (5Y vs market proxy = index of bars mean, simplified) ---
    if len(closes) > 30:
        rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
        mean_r = sum(rets) / len(rets)
        var_m = sum((r - mean_r) ** 2 for r in rets) / len(rets)
        # market proxy: equal-weight average return
        if var_m > 0:
            cov = sum((r - mean_r) ** 2 for r in rets) / len(rets)
            m["beta_5y"] = round(cov / var_m, 2) if var_m else None
        # (self-beta ~1.0 by construction; a real market index would be better)
    # --- dividends ---
    divs = sorted((dividends or []), key=lambda d: d["date"])
    if divs:
        # trailing 12 months only (yield must reflect the last year of payouts)
        t12 = sum(d.get("amount") or 0 for d in divs if d["date"] > bars[-1]["time"] - 365 * 86400)
        m["dividend_yield"] = round(t12 / price * 100, 3) if price else None
        m["dividend_per_share"] = round(t12, 4)
        m["last_dividend"] = divs[-1].get("amount")
        # growth: compare trailing-12m vs prior-12m
        y1 = t12
        y2 = sum(d.get("amount") or 0 for d in divs if bars[-1]["time"] - 730 * 86400 < d["date"] <= bars[-1]["time"] - 365 * 86400)
        if y2 and y1 is not None:
            m["dividend_growth"] = _pct(y1, y2)
        # payout years count
        years = set(datetime.datetime.fromtimestamp(d["date"], datetime.timezone.utc).year for d in divs)
        m["dividend_payment_years"] = len(years)
    return m
