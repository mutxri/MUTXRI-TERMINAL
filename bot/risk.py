#!/usr/bin/env python3
"""bot/risk.py - how much a holding can hurt, and whether the return paid for it.

  sharpe / sortino   excess return per unit of total / downside volatility,
                     against the shortest-dated government yield on file for
                     that market (bonds.json), dated and flagged if stale
  VaR / CVaR         historical (nearest-rank) and parametric (normal) one-day
                     value at risk, and the average loss beyond it
  drawdown           worst peak-to-trough fall and whether it has recovered
  beta               sensitivity to the board

There is no index price history on file, so beta is measured against the
board's median daily return across every security that traded on consecutive
sessions. The median rather than the mean, so one bad print cannot move the
board. It is labelled as exactly that wherever it appears; calling it "beta to
the NSE All-Share" would be a claim the data does not support.

Portfolio figures use a sample covariance over the dates every holding traded.
Returns are in each listing's own currency. With no FX history on file they are
not converted, and a mixed-currency portfolio says so rather than quietly
blending a rand move into a naira return.
"""
import datetime as dt
import math

from . import fixed_income as FI, technicals as T

TRADING_DAYS = 252
MIN_OBS = 60
BOARD_MIN_NAMES = 5
BOARD_TRIM = 0.10        # drop the top and bottom 10% of each day's returns
WEAK_R2 = 0.10           # below this the board explains too little for beta to mean much
Z = {0.95: 1.6448536269514722, 0.99: 2.3263478740408408}
_BOARD = {}


# ------------------------------------------------------------ primitives
def sharpe(rets, rf_pct=0.0):
    rd = rf_pct / 100.0 / TRADING_DAYS
    ex = [r - rd for r in rets]
    sd = T.stdev(ex)
    return T.mean(ex) / sd * math.sqrt(TRADING_DAYS) if sd else None


def sortino(rets, rf_pct=0.0):
    rd = rf_pct / 100.0 / TRADING_DAYS
    if not rets:
        return None
    dd = math.sqrt(sum(min(0.0, r - rd) ** 2 for r in rets) / len(rets))
    return (T.mean(rets) - rd) / dd * math.sqrt(TRADING_DAYS) if dd else None


def var_historical(rets, level=0.95):
    """Nearest-rank: the k-th worst day, k = ceil((1 - level) * n)."""
    n = len(rets)
    if not n:
        return None
    k = max(1, int(math.ceil(round((1 - level) * n, 9))))
    worst = sorted(rets)[:k]
    return {"varPct": -worst[-1] * 100, "cvarPct": -T.mean(worst) * 100,
            "level": level, "observations": n, "tailDays": k}


def var_parametric(rets, level=0.95):
    sd = T.stdev(rets)
    if sd is None:
        return None
    return {"varPct": (Z[level] * sd - T.mean(rets)) * 100, "level": level}


def beta(asset, market):
    n = len(asset)
    if n != len(market) or n < 3:
        return None
    ma, mm = T.mean(asset), T.mean(market)
    cov = sum((a - ma) * (m - mm) for a, m in zip(asset, market)) / (n - 1)
    var_m = sum((m - mm) ** 2 for m in market) / (n - 1)
    var_a = sum((a - ma) ** 2 for a in asset) / (n - 1)
    if not var_m:
        return None
    corr = cov / math.sqrt(var_a * var_m) if var_a else None
    return {"beta": cov / var_m, "correlation": corr,
            "rSquared": corr * corr if corr is not None else None, "observations": n}


def portfolio_stats(series, weights):
    """Volatility and risk contributions from aligned daily return series."""
    n = len(series)
    tot = float(sum(weights))
    w = [x / tot for x in weights]
    means = [T.mean(s) for s in series]
    obs = len(series[0])
    cov = [[sum((series[i][t] - means[i]) * (series[j][t] - means[j]) for t in range(obs)) / (obs - 1)
            for j in range(n)] for i in range(n)]
    sw = [sum(cov[i][j] * w[j] for j in range(n)) for i in range(n)]
    pvar = sum(w[i] * sw[i] for i in range(n))
    vols = [math.sqrt(cov[i][i]) for i in range(n)]
    corr = [[cov[i][j] / (vols[i] * vols[j]) if vols[i] and vols[j] else None
             for j in range(n)] for i in range(n)]
    pvol = math.sqrt(max(pvar, 0.0))
    weighted = sum(w[i] * vols[i] for i in range(n))
    return {
        "weights": w,
        "volAnnualPct": pvol * math.sqrt(TRADING_DAYS) * 100,
        "holdingVolAnnualPct": [v * math.sqrt(TRADING_DAYS) * 100 for v in vols],
        "diversificationRatio": weighted / pvol if pvol else None,
        "riskContributionPct": [w[i] * sw[i] / pvar * 100 if pvar else None for i in range(n)],
        "correlation": corr,
    }


# --------------------------------------------------- performance measures
def treynor(return_pct, rf_pct, beta_coef):
    """Excess return per unit of market risk."""
    return (return_pct - rf_pct) / beta_coef if beta_coef else None


def jensen_alpha(return_pct, rf_pct, beta_coef, market_return_pct):
    """Return above what CAPM says the beta earned."""
    return return_pct - (rf_pct + beta_coef * (market_return_pct - rf_pct))


def tracking_error(portfolio, benchmark, periods_per_year=TRADING_DAYS):
    if len(portfolio) != len(benchmark):
        raise ValueError("portfolio and benchmark need the same number of periods")
    sd = T.stdev([p - b for p, b in zip(portfolio, benchmark)])
    return sd * math.sqrt(periods_per_year) * 100 if sd is not None else None


def information_ratio(portfolio, benchmark, periods_per_year=TRADING_DAYS):
    if len(portfolio) != len(benchmark):
        raise ValueError("portfolio and benchmark need the same number of periods")
    active = [p - b for p, b in zip(portfolio, benchmark)]
    sd = T.stdev(active)
    return T.mean(active) / sd * math.sqrt(periods_per_year) if sd else None


def calmar(annual_return_pct, max_drawdown_pct):
    return annual_return_pct / abs(max_drawdown_pct) if max_drawdown_pct else None


def m_squared(sharpe_ratio, benchmark_vol_pct, rf_pct):
    """Modigliani: the return the portfolio would earn at the benchmark's risk."""
    return rf_pct + sharpe_ratio * benchmark_vol_pct


def portfolio_vol_two(weight_1, vol_1_pct, vol_2_pct, correlation):
    w2 = 1 - weight_1
    var = (weight_1 ** 2 * vol_1_pct ** 2 + w2 ** 2 * vol_2_pct ** 2
           + 2 * weight_1 * w2 * correlation * vol_1_pct * vol_2_pct)
    return math.sqrt(max(var, 0.0))


# ------------------------------------------------------------ market data
def _trimmed_mean(xs, cut=BOARD_TRIM):
    xs = sorted(xs)
    k = int(len(xs) * cut)
    core = xs[k:len(xs) - k] if len(xs) - 2 * k > 0 else xs
    return sum(core) / len(core)


def board_returns(ex):
    """{date: trimmed mean daily return} across the board's liquid names, for beta."""
    ex = ex.upper()
    if ex in _BOARD:
        return _BOARD[ex]
    by_day = {}
    for _, path in T.exchange_files(ex):
        try:
            _, bars = T.load_bars(path)
        except Exception:
            continue
        # A name whose price rarely changes contributes a string of zeros that
        # flattens the board and inflates every beta measured against it.
        if len(bars) < T.MIN_BARS or T.liquidity(ex, bars)["thin"]:
            continue
        for d, r in T.daily_returns(ex, bars)[0]:
            by_day.setdefault(d, []).append(r)
    out = {d: _trimmed_mean(rs) for d, rs in by_day.items() if len(rs) >= BOARD_MIN_NAMES}
    _BOARD[ex] = out
    return out


def _window(ticker, ex, days):
    loc = T.locate(ticker, ex)
    if not loc:
        return None
    x, sid, path = loc
    doc, bars = T.load_bars(path)
    if not bars:
        return None
    cut = bars[-1]["d"] - dt.timedelta(days=days)
    rets = [(d, r) for d, r in T.daily_returns(x, bars)[0] if d > cut]
    return {"exchange": x, "id": sid, "doc": doc, "bars": bars,
            "yearBars": [b for b in bars if b["d"] > cut], "returns": rets}


def analyse(ticker, ex=None, rf_pct=None, days=365):
    w = _window(ticker, ex, days)
    if not w:
        return {"available": False, "reason": "no price history on file for %s" % ticker}
    rets = [r for _, r in w["returns"]]
    if len(rets) < MIN_OBS:
        return {"available": False, "exchange": w["exchange"], "id": w["id"],
                "reason": "only %d daily returns in the window; %d needed"
                          % (len(rets), MIN_OBS)}
    if rf_pct is not None:
        rf = {"yieldPct": rf_pct, "instrument": "given", "asOf": None, "stale": False}
    else:
        rf = FI.risk_free(w["exchange"])
    rfp = rf["yieldPct"] if rf else 0.0
    out = {"available": True, "exchange": w["exchange"], "id": w["id"],
           "name": w["doc"].get("name") or T.display_name(w["exchange"], w["id"]),
           "currency": w["doc"].get("currency"),
           "window": {"from": str(w["returns"][0][0]), "to": str(w["returns"][-1][0]),
                      "observations": len(rets)},
           "riskFree": rf or {"yieldPct": 0.0, "instrument": None,
                              "note": "no government yield on file; measured against 0%"},
           "volAnnualPct": T.stdev(rets) * math.sqrt(TRADING_DAYS) * 100,
           "sharpe": sharpe(rets, rfp), "sortino": sortino(rets, rfp),
           "var95": var_historical(rets, 0.95), "var95Parametric": var_parametric(rets, 0.95),
           "var99": var_historical(rets, 0.99) if len(rets) >= 100 else None,
           "maxDrawdown": T.max_drawdown([b["c"] for b in w["yearBars"]],
                                         [b["d"] for b in w["yearBars"]]),
           "bestDayPct": max(rets) * 100, "worstDayPct": min(rets) * 100}
    board = board_returns(w["exchange"])
    pairs = [(r, board[d]) for d, r in w["returns"] if d in board]
    b = beta([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= MIN_OBS else None
    cautions = []
    if b:
        b["against"] = ("%s board, trimmed mean daily return of liquid names "
                        "(no index history on file)" % w["exchange"])
        b["weakFit"] = b["rSquared"] is None or b["rSquared"] < WEAK_R2
        if b["weakFit"]:
            cautions.append("the board explains only %.0f%% of this security's daily moves "
                            "(R-squared), so its beta is not meaningful"
                            % ((b["rSquared"] or 0) * 100))
    out["beta"] = b
    liq = T.liquidity(w["exchange"], w["bars"])
    if liq["thin"]:
        cautions.append("thinly traded: few price changes understate volatility and "
                        "VaR, and flatten beta toward zero")
    if cautions:
        out["caution"] = "; ".join(cautions)
    out["liquidity"] = liq
    return out


def portfolio(holdings, days=365):
    """holdings: [(ticker, weight, exchange or None)]."""
    if not holdings:
        raise ValueError("no holdings")
    if any(w <= 0 for _, w, _ in holdings):
        raise ValueError("weights must be positive")
    legs, missing = [], []
    for t, wt, ex in holdings:
        win = _window(t, ex, days)
        if not win or len(win["returns"]) < MIN_OBS:
            missing.append(t)
        else:
            legs.append((t, wt, win))
    if missing:
        return {"available": False,
                "reason": "not enough history for: %s" % ", ".join(missing)}
    common = set.intersection(*[set(d for d, _ in leg[2]["returns"]) for leg in legs])
    days_ = sorted(common)
    if len(days_) < MIN_OBS:
        return {"available": False,
                "reason": "the holdings share only %d trading days; %d needed"
                          % (len(days_), MIN_OBS)}
    series = []
    for _, _, win in legs:
        m = dict(win["returns"])
        series.append([m[d] for d in days_])
    st = portfolio_stats(series, [leg[1] for leg in legs])
    port = [sum(st["weights"][i] * series[i][t] for i in range(len(series)))
            for t in range(len(days_))]
    currencies = sorted(set((leg[2]["doc"].get("currency") or "?") for leg in legs))
    out = {"available": True, "holdings": [{"id": leg[2]["id"], "exchange": leg[2]["exchange"],
                                            "weight": st["weights"][i],
                                            "volAnnualPct": st["holdingVolAnnualPct"][i],
                                            "riskContributionPct": st["riskContributionPct"][i]}
                                           for i, leg in enumerate(legs)],
           "commonDays": len(days_), "from": str(days_[0]), "to": str(days_[-1]),
           "volAnnualPct": st["volAnnualPct"],
           "diversificationRatio": st["diversificationRatio"],
           "correlation": st["correlation"], "var95": var_historical(port, 0.95),
           "currencies": currencies}
    if len(currencies) > 1:
        out["caution"] = ("holdings are priced in %s and no FX history is on file, so "
                          "returns are unconverted local-currency returns"
                          % ", ".join(currencies))
    return out
