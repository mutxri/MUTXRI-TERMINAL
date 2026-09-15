#!/usr/bin/env python3
"""bot/selftest.py - proving the arithmetic, one worked example at a time.

A financial engine cannot be trusted because it looks right. Every ratio here is
checked against a fixture built from round numbers, with the expected answer
worked out by hand and written down beside it, so a wrong formula fails loudly
instead of producing a plausible number nobody questions.

That is what "self-improving" has to mean for calculation: not a model that
learns to do arithmetic, but a fixed engine whose arithmetic is measurably
correct, and a suite that fails the moment someone changes a denominator.

Three groups of checks:

  FORMULAS   every metric against a hand-computed fixture
  IDENTITIES relationships that must hold whatever the numbers - DuPont
             reconciling to ROE, the two P/E routes agreeing, the balance sheet
             balancing
  EDGES      the cases that produced wrong answers in the past: negative equity,
             a loss, liabilities in brackets, a gap in the fiscal years, and a
             bank whose interest expense is not a financing cost

Run: python mutxri_ai.py selftest
"""
from . import statements as S

# A company with numbers chosen so every ratio lands somewhere memorable.
FIXTURE = {
    "entity": {"id": "TESTCO", "name": "Testco Ltd", "kind": "private",
               "currency": "XTS", "marketCap": 1400.0, "sharesOutstanding": 100.0},
    "periods": ["FY2025", "FY2024"],
    "sections": {
        "income": {
            "revenue": [1000.0, 800.0],
            "cost_of_sales": [600.0, 500.0],
            "gross_profit": [400.0, 300.0],
            "operating_expenses": [250.0, 200.0],
            "ebit": [150.0, 100.0],
            "net_finance_costs": [50.0, 40.0],
            "pbt": [100.0, 60.0],
            "tax": [30.0, 18.0],
            "net_profit": [70.0, 42.0],
            "eps": [0.70, 0.42],
        },
        "balance": {
            "total_assets": [2000.0, 1800.0],
            "current_assets": [800.0, 700.0],
            "inventory": [200.0, 180.0],
            "receivables": [300.0, 250.0],
            "cash": [100.0, 90.0],
            "total_liabilities": [1200.0, 1100.0],
            "current_liabilities": [500.0, 450.0],
            "borrowings": [600.0, 550.0],
            "total_equity": [800.0, 700.0],
            "retained_earnings": [400.0, 340.0],
        },
        "cashflow": {
            "ocf": [140.0, 100.0],
            "capex": [40.0, 30.0],
            "fcf": [100.0, 70.0],
        },
    },
    "source": {"kind": "fixture"},
}

# metric -> (expected, how it was worked out by hand)
EXPECTED = {
    "gross_margin":         (40.0,   "400 / 1000"),
    "ebit_margin":          (15.0,   "150 / 1000"),
    "net_margin":           (7.0,    "70 / 1000"),
    "roe":                  (8.75,   "70 / 800"),
    "roa":                  (3.5,    "70 / 2000"),
    "debt_to_equity":       (0.75,   "600 / 800"),
    "liabilities_to_equity": (1.5,   "1200 / 800"),
    "net_debt":             (500.0,  "600 borrowings - 100 cash"),
    "net_debt_to_equity":   (0.625,  "500 / 800"),
    "current_ratio":        (1.6,    "800 / 500"),
    "quick_ratio":          (1.2,    "(800 - 200 inventory) / 500"),
    "interest_cover":       (3.0,    "150 EBIT / 50 finance costs"),
    "ocf_to_net_profit":    (2.0,    "140 / 70"),
    "fcf_margin":           (10.0,   "100 / 1000"),
    "capital_employed":     (1500.0, "2000 assets - 500 current liabilities"),
    "roce":                 (10.0,   "150 EBIT / 1500 capital employed"),
    "effective_tax_rate":   (30.0,   "30 tax / 100 PBT"),
    "roic":                 (7.0,    "150 x (1 - 0.30) = 105, / 1500"),
    "asset_turnover":       (0.5,    "1000 revenue / 2000 assets"),
    "equity_multiplier":    (2.5,    "2000 assets / 800 equity"),
    "working_capital":      (300.0,  "800 - 500"),
    "inventory_days":       (121.7,  "200 x 365 / 600 cost of sales"),
    "receivable_days":      (109.5,  "300 x 365 / 1000 revenue"),
    "revenue_growth":       (25.0,   "(1000 - 800) / 800"),
    "net_profit_growth":    (66.67,  "(70 - 42) / 42"),
}

EXPECTED_VALUATION = {
    "pe":             (20.0,  "1400 market cap / 70 net profit"),
    "pb":             (1.75,  "1400 / 800 equity"),
    "ps":             (1.4,   "1400 / 1000 revenue"),
    "earnings_yield": (5.0,   "70 / 1400"),
    "impliedPrice":   (14.0,  "1400 / 100 shares"),
    "pe_from_eps":    (20.0,  "14.00 price / 0.70 EPS"),
    "enterpriseValue": (1900.0, "1400 market cap + 500 net debt"),
    "ev_ebit":        (12.67, "1900 / 150 EBIT"),
}

TOL = 0.05          # absolute tolerance, generous enough for stated rounding


def _close(a, b, tol=TOL):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(tol, abs(b) * 0.001)


def _mutate(**changes):
    """A copy of the fixture with specific line items replaced."""
    import copy
    doc = copy.deepcopy(FIXTURE)
    for path, val in changes.items():
        section, key = path.split("__", 1)
        if val is None:
            doc["sections"][section].pop(key, None)
        else:
            doc["sections"][section][key] = val
    return doc


def check_formulas():
    a = S.analyse(FIXTURE)
    cur = a["metrics"][0]
    out = []
    for metric, (want, how) in EXPECTED.items():
        got = cur.get(metric)
        out.append({"group": "formula", "name": metric, "expected": want,
                    "got": got, "how": how, "ok": _close(got, want)})
    val = a["valuation"] or {}
    for metric, (want, how) in EXPECTED_VALUATION.items():
        got = val.get(metric)
        out.append({"group": "valuation", "name": metric, "expected": want,
                    "got": got, "how": how, "ok": _close(got, want)})
    return out


def check_identities():
    """Relationships that hold regardless of the particular numbers."""
    a = S.analyse(FIXTURE)
    cur = a["metrics"][0]
    out = []

    # DuPont: ROE = net margin x asset turnover x equity multiplier.
    dupont = (cur["net_margin"] / 100.0) * cur["asset_turnover"] * cur["equity_multiplier"] * 100
    out.append({"group": "identity", "name": "dupont_reconciles_to_roe",
                "expected": cur["roe"], "got": round(dupont, 4),
                "how": "net margin x asset turnover x equity multiplier",
                "ok": _close(dupont, cur["roe"], 0.01)})

    # Two independent routes to P/E must agree.
    val = a["valuation"]
    out.append({"group": "identity", "name": "pe_routes_agree",
                "expected": val["pe"], "got": val["pe_from_eps"],
                "how": "market cap / net profit  vs  price / EPS",
                "ok": _close(val["pe"], val["pe_from_eps"], 0.05)})

    # The balance sheet must balance.
    ta, tl, te = cur["total_assets"], cur["total_liabilities"], cur["total_equity"]
    out.append({"group": "identity", "name": "balance_sheet_balances",
                "expected": ta, "got": tl + te,
                "how": "assets = liabilities + equity",
                "ok": _close(ta, tl + te, 0.01)})

    # Working capital is the numerator of the current ratio.
    out.append({"group": "identity", "name": "working_capital_matches_current_ratio",
                "expected": round(cur["current_ratio"], 4),
                "got": round((cur["working_capital"] + 500.0) / 500.0, 4),
                "how": "(working capital + current liabilities) / current liabilities",
                "ok": _close(cur["current_ratio"], (cur["working_capital"] + 500.0) / 500.0, 0.01)})

    # The audit built into analyse() must pass on a clean fixture.
    v = a["verification"]
    out.append({"group": "identity", "name": "consistency_audit_passes",
                "expected": 0, "got": len(v["failed"]),
                "how": "no accounting identity may fail on the fixture",
                "ok": not v["failed"]})
    return out


def check_edges():
    """The cases that have produced confidently wrong answers before."""
    out = []

    # Negative equity: every equity-based ratio must be withheld, not inverted.
    neg = S.analyse(_mutate(balance__total_equity=[-300.0, 700.0]))["metrics"][0]
    out.append({"group": "edge", "name": "negative_equity_withholds_roe",
                "expected": None, "got": neg["roe"],
                "how": "a loss over negative equity computed to ROE +915% on ArcelorMittal",
                "ok": neg["roe"] is None})
    out.append({"group": "edge", "name": "negative_equity_withholds_gearing",
                "expected": None, "got": neg["debt_to_equity"],
                "how": "debt/equity is meaningless when equity is negative",
                "ok": neg["debt_to_equity"] is None})

    # Loss-making: no P/E, and growth off a negative base is not growth.
    loss = S.analyse(_mutate(income__net_profit=[-50.0, 42.0]))
    out.append({"group": "edge", "name": "loss_making_withholds_pe",
                "expected": None, "got": (loss["valuation"] or {}).get("pe"),
                "how": "a negative P/E is not a valuation",
                "ok": (loss["valuation"] or {}).get("pe") is None})
    recover = S.analyse(_mutate(income__net_profit=[70.0, -42.0]))["metrics"][0]
    out.append({"group": "edge", "name": "growth_off_negative_base_withheld",
                "expected": None, "got": recover["net_profit_growth"],
                "how": "-5.8bn to -2.9bn computed as '+50% growth' on a loss-making company",
                "ok": recover["net_profit_growth"] is None})

    # Liabilities presented in brackets are still a magnitude.
    brack = S.analyse(_mutate(balance__current_liabilities=[-500.0, -450.0]))["metrics"][0]
    out.append({"group": "edge", "name": "bracketed_liabilities_are_magnitudes",
                "expected": 1.6, "got": brack["current_ratio"],
                "how": "BAT Kenya reports 'Current liabilities (6,198)' in a net-assets layout",
                "ok": _close(brack["current_ratio"], 1.6)})

    # A gap in the fiscal years must not be treated as one year of growth.
    gap = dict(FIXTURE, periods=["FY2025", "FY2021"])
    gapped = S.analyse(gap)["metrics"][0]
    out.append({"group": "edge", "name": "non_contiguous_years_withhold_growth",
                "expected": None, "got": gapped["revenue_growth"],
                "how": "FY2025 against FY2021 is not a one-year change",
                "ok": gapped["revenue_growth"] is None})

    # A bank's interest expense is not a financing cost, so EBIT must not be
    # rebuilt from it when the result exceeds revenue.
    bank = _mutate(income__ebit=None, income__net_finance_costs=[900.0, 800.0])
    bank_row = S.analyse(bank)["metrics"][0]
    out.append({"group": "edge", "name": "bank_ebit_not_derived",
                "expected": None, "got": bank_row["ebit"],
                "how": "PBT 100 + finance costs 900 = 1000 exceeds revenue; Absa's rebuild did this",
                "ok": bank_row["ebit"] is None})

    # A genuine non-financial with no EBIT line should get one.
    ind = _mutate(income__ebit=None)
    ind_row = S.analyse(ind)["metrics"][0]
    out.append({"group": "edge", "name": "missing_ebit_derived_when_plausible",
                "expected": 150.0, "got": ind_row["ebit"],
                "how": "PBT 100 + finance costs 50, inside revenue 1000",
                "ok": _close(ind_row["ebit"], 150.0) and ind_row["ebit_derived"]})

    # Missing data must produce None, never zero.
    nodata = S.analyse(_mutate(balance__total_assets=None))["metrics"][0]
    out.append({"group": "edge", "name": "missing_input_yields_none_not_zero",
                "expected": None, "got": nodata["roa"],
                "how": "a missing denominator is unknown, not 0%",
                "ok": nodata["roa"] is None})
    return out


def check_models():
    """The named models, each against a hand-worked answer."""
    from . import models as M
    a = S.analyse(FIXTURE)
    m = M.score_all(a)
    out = []

    # Altman Z'' (EM variant), worked by hand:
    #   X1 = 300/2000 = 0.15      6.56 x 0.15    = 0.984
    #   X2 = 400/2000 = 0.20      3.26 x 0.20    = 0.652
    #   X3 = 150/2000 = 0.075     6.72 x 0.075   = 0.504
    #   X4 = 800/1200 = 0.6667    1.05 x 0.6667  = 0.700
    #   + 3.25 constant                          = 3.250
    #                                      total = 6.09  -> safe (> 2.6)
    z = m["altmanZ"]
    out.append({"group": "model", "name": "altman_z_score", "expected": 6.09,
                "got": z.get("score"), "how": "6.56(.15)+3.26(.20)+6.72(.075)+1.05(.6667)+3.25",
                "ok": z.get("available") and _close(z.get("score"), 6.09, 0.02)})
    out.append({"group": "model", "name": "altman_band", "expected": "safe",
                "got": z.get("band"), "how": "6.09 is above the 2.6 cut",
                "ok": z.get("band") == "safe"})

    # Sloan accruals: (70 - 140) / ((2000 + 1800)/2) = -70/1900 = -3.68%
    acc = m["accruals"]
    out.append({"group": "model", "name": "sloan_accruals", "expected": -3.68,
                "got": acc.get("ratio"), "how": "(net profit 70 - OCF 140) / average assets 1900",
                "ok": _close(acc.get("ratio"), -3.68, 0.02)})

    # Piotroski: every signal passes on this fixture except share issuance,
    # which has no data, so the score is 8 out of 8 scored.
    pio = m["piotroski"]
    out.append({"group": "model", "name": "piotroski_score", "expected": "8/8",
                "got": "%s/%s" % (pio.get("score"), pio.get("outOf")),
                "how": "all measurable signals improve year on year",
                "ok": pio.get("score") == 8 and pio.get("outOf") == 8})
    out.append({"group": "model", "name": "piotroski_excludes_unmeasurable",
                "expected": ["no_dilution"], "got": pio.get("unavailableSignals"),
                "how": "no share-count history, so the signal is not assumed clean",
                "ok": pio.get("unavailableSignals") == ["no_dilution"]})

    # Book value per share 800/100 = 8.00; Graham sqrt(22.5 x 0.70 x 8) = 11.225
    ps = m["perShare"]
    out.append({"group": "model", "name": "book_value_per_share", "expected": 8.0,
                "got": ps.get("bookValuePerShare"), "how": "800 equity / 100 shares",
                "ok": _close(ps.get("bookValuePerShare"), 8.0)})
    out.append({"group": "model", "name": "graham_number", "expected": 11.225,
                "got": ps.get("grahamNumber"), "how": "sqrt(22.5 x 0.70 EPS x 8.00 book)",
                "ok": _close(ps.get("grahamNumber"), 11.225, 0.01)})

    # Cost-to-income 250/1000 = 25%; DOL = EBIT growth 50% / revenue growth 25% = 2.0
    out.append({"group": "model", "name": "cost_to_income", "expected": 25.0,
                "got": m["costToIncome"].get("ratio"), "how": "250 opex / 1000 revenue",
                "ok": _close(m["costToIncome"].get("ratio"), 25.0)})
    out.append({"group": "model", "name": "operating_leverage", "expected": 2.0,
                "got": m["operatingLeverage"].get("dol"),
                "how": "EBIT +50% / revenue +25%",
                "ok": _close(m["operatingLeverage"].get("dol"), 2.0, 0.02)})

    # Without retained earnings the Z-score must refuse rather than drop a term.
    noz = M.altman_z(S.analyse(_mutate(balance__retained_earnings=None))["metrics"][0])
    out.append({"group": "model", "name": "altman_refuses_partial",
                "expected": False, "got": noz.get("available"),
                "how": "dropping a term yields something that is not a Z-score",
                "ok": noz.get("available") is False
                      and "retained_earnings" in (noz.get("missing") or [])})
    return out


def _row(group, name, want, got, how, tol=0.01):
    return {"group": group, "name": name, "expected": want,
            "got": round(got, 4) if isinstance(got, float) else got,
            "how": how, "ok": _close(got, want, tol)}


def check_markets():
    """Indicators and risk measures, each on a series small enough to do by hand."""
    import datetime as dt
    from . import risk as R, technicals as T
    out = []
    out.append(_row("markets", "sma_3", 4.0, T.sma([1, 2, 3, 4, 5], 3), "(3 + 4 + 5) / 3"))
    out.append(_row("markets", "ema_3", 8.0, T.ema_series([2, 4, 6, 8, 10], 3)[-1],
                    "seed SMA(2,4,6)=4; k=0.5: 8->6, 10->8"))
    # Seven +1 and seven -1 changes: average gain = average loss = 0.5, RSI 50.
    # One more +2: gain (0.5x13 + 2)/14 = 0.607143, loss 6.5/14 = 0.464286,
    # RS 1.307692, RSI 100 - 100/2.307692 = 56.667
    closes = [10.0]
    for i in range(14):
        closes.append(closes[-1] + (1 if i % 2 == 0 else -1))
    out.append(_row("markets", "rsi_balanced", 50.0, T.rsi(closes), "equal average gain and loss"))
    out.append(_row("markets", "rsi_wilder_smoothing", 56.667, T.rsi(closes + [closes[-1] + 2]),
                    "Wilder: ((0.5x13+2)/14) / (6.5/14) -> RSI 56.667"))
    out.append({"group": "markets", "name": "rsi_flat_is_none", "expected": None,
                "got": T.rsi([5.0] * 20), "how": "no trades is not RSI 50",
                "ok": T.rsi([5.0] * 20) is None})
    flat = [3.0] * 40
    out.append(_row("markets", "macd_constant_is_zero", 0.0, T.macd(flat)["macd"],
                    "both EMAs equal the constant"))
    day = dt.date(2026, 1, 1)
    bars = [{"d": day, "h": 11.0, "l": 9.0, "c": 10.0, "v": None} for _ in range(20)]
    out.append(_row("markets", "atr_constant_range", 2.0, T.atr(bars), "high 11 - low 9, no gaps"))
    dd = T.max_drawdown([100, 120, 90, 95, 130, 104])
    out.append(_row("markets", "max_drawdown", -25.0, dd["pct"],
                    "120 -> 90 is -25%, deeper than 130 -> 104 at -20%"))
    out.append(_row("markets", "annualised_volatility", 22.45,
                    T.stdev([0.01, -0.01]) * 252 ** 0.5 * 100,
                    "sample sd of +1%, -1% = 1.4142%, x sqrt(252)"))
    tail = [-0.05, -0.03] + [0.0] * 38
    v = R.var_historical(tail, 0.95)
    out.append(_row("markets", "historical_var_95", 3.0, v["varPct"],
                    "40 days: ceil(0.05 x 40) = 2nd worst day, -3%"))
    out.append(_row("markets", "historical_cvar_95", 4.0, v["cvarPct"],
                    "mean of the two worst days, -5% and -3%"))
    out.append(_row("markets", "sharpe_ratio", 11.225, R.sharpe([0.002, 0.0], 0.0),
                    "mean 0.1% / sd 0.14142% x sqrt(252)"))
    b = R.beta([0.02, -0.04, 0.06], [0.01, -0.02, 0.03])
    out.append(_row("markets", "beta_double_the_board", 2.0, b["beta"], "asset = 2 x board"))
    out.append(_row("markets", "correlation_perfect", 1.0, b["correlation"], "exact multiple"))
    a = [0.01, -0.01, 0.01, -0.01]
    hedge = R.portfolio_stats([a, [-x for x in a]], [1, 1])
    out.append(_row("markets", "perfect_hedge_zero_vol", 0.0, hedge["volAnnualPct"],
                    "equal weights in two series with correlation -1"))
    lev = R.portfolio_stats([a, [2 * x for x in a]], [1, 1])
    out.append(_row("markets", "risk_contribution", 33.333, lev["riskContributionPct"][0],
                    "cov s^2[[1,2],[2,4]], w=.5: 0.75 / 2.25 of the variance", 0.05))
    return out


def check_fixed_income():
    import datetime as dt
    from . import fixed_income as F
    out = []
    out.append(_row("bonds", "par_bond_prices_at_100", 100.0, F.price(100, 10, 10, 5, 1),
                    "coupon equals yield"))
    out.append(_row("bonds", "discount_bond_price", 92.7904, F.price(100, 10, 12, 5, 1),
                    "10 x annuity(12%, 5) 3.604776 + 100 / 1.762342"))
    out.append(_row("bonds", "ytm_round_trip", 12.0, F.ytm(F.price(100, 10, 12, 5, 1), 100, 10, 5, 1),
                    "solving the yield of a bond priced at 12% returns 12%", 1e-6))
    rk = F.risk(100, 10, 10, 5, 1)
    out.append(_row("bonds", "macaulay_duration", 4.1699, rk["macaulayDuration"],
                    "sum of t x PV(cf) = 416.9865, / price 100"))
    out.append(_row("bonds", "modified_duration", 3.7908, rk["modifiedDuration"], "4.1699 / 1.10"))
    out.append(_row("bonds", "convexity", 19.3683, rk["convexity"],
                    "sum t(t+1) PV = 2343.568, / (100 x 1.21)"))
    out.append(_row("bonds", "zero_coupon_duration_is_maturity", 5.0,
                    F.risk(100, 0, 10, 5, 1)["macaulayDuration"], "one cash flow at year 5", 1e-9))
    out.append(_row("bonds", "accrued_interest", 2.5,
                    F.accrued_interest(100, 10, 2, dt.date(2026, 1, 1), dt.date(2026, 7, 1),
                                       dt.date(2026, 4, 1)),
                    "5 coupon x 90 of 181 days = 2.486", 0.02))
    out.append(_row("bonds", "bill_price_364_basis", 97.8545, F.bill_price(8.77, 91, 364),
                    "100 / (1 + 0.0877 x 91/364)"))
    out.append(_row("bonds", "discount_rate_price", 92.0219, F.discount_price(16, 182, 365),
                    "100 x (1 - 0.16 x 182/365)"))
    out.append(_row("bonds", "discount_to_true_yield", 17.3871, F.discount_to_yield(16, 182, 365),
                    "0.16 / (1 - 0.0797808)"))
    out.append(_row("bonds", "yield_discount_round_trip", 16.0,
                    F.yield_to_discount(F.discount_to_yield(16, 182, 365), 182, 365),
                    "the two conversions invert each other", 1e-9))
    out.append(_row("bonds", "fisher_real_yield", 4.7619, F.real_yield(10, 5), "1.10 / 1.05 - 1"))
    return out


def check_valuation():
    from . import valuation as V
    out = []
    out.append(_row("valuation-models", "capm", 17.2, V.capm(10, 1.2, 6), "10 + 1.2 x 6"))
    out.append(_row("valuation-models", "wacc", 11.8, V.wacc(600, 400, 15, 10, 30),
                    "0.6 x 15 + 0.4 x 10 x (1 - 0.30)"))
    out.append(_row("valuation-models", "gordon_ddm", 42.0, V.ddm(2, 10, 5), "2 x 1.05 / (0.10 - 0.05)"))
    d = V.dcf(100, 10, 5, 10, 2)
    out.append(_row("valuation-models", "dcf_explicit_pv", 200.0, d["pvExplicit"],
                    "110 / 1.1 + 121 / 1.21"))
    out.append(_row("valuation-models", "dcf_terminal_pv", 2100.0, d["pvTerminal"],
                    "121 x 1.05 / 0.05 = 2541, / 1.21"))
    out.append(_row("valuation-models", "dcf_terminal_share", 91.304, d["terminalSharePct"],
                    "2100 / 2300"))
    br = V.equity_bridge(d["enterpriseValue"], 300, 100)
    out.append(_row("valuation-models", "equity_per_share", 20.0, br["perShare"],
                    "(2300 - 300 net debt) / 100 shares"))
    out.append(_row("valuation-models", "reverse_dcf_recovers_growth", 10.0,
                    V.reverse_dcf(2300, 100, 10, 5, 2),
                    "the growth that prices EV 2300 is the 10% that produced it", 1e-6))
    try:
        V.gordon(1, 5, 5)
        refused = False
    except ValueError:
        refused = True
    out.append({"group": "valuation-models", "name": "growth_at_discount_rate_refused",
                "expected": True, "got": refused,
                "how": "r = g has no finite perpetuity value", "ok": refused})
    return out


def _check(group, name, expected, got, how, ok):
    return {"group": group, "name": name, "expected": expected, "got": got,
            "how": how, "ok": bool(ok)}


def check_tvm():
    import datetime as dt
    from . import tvm as V
    g = "time-value"
    cf = [-1000.0, 500.0, 500.0, 500.0]
    loan = V.amortisation(100000, 12, 1)
    return [
        _row(g, "future_value", 1331.0, V.fv(1000, 10, 3), "1000 x 1.1^3"),
        _row(g, "present_value", 1000.0, V.pv(1331, 10, 3), "1331 / 1.1^3"),
        _row(g, "annuity_pv", 248.6852, V.annuity_pv(100, 10, 3), "100 x (1 - 1.1^-3) / 0.1"),
        _row(g, "annuity_fv", 331.0, V.annuity_fv(100, 10, 3), "100 x (1.1^3 - 1) / 0.1"),
        _row(g, "annuity_due_pv", 273.5537, V.annuity_pv(100, 10, 3, due=True), "248.6852 x 1.1"),
        _row(g, "growing_perpetuity", 2000.0, V.growing_perpetuity(100, 10, 5), "100 / (0.10 - 0.05)"),
        _row(g, "effective_annual_rate", 12.6825, V.ear(12, 12), "1.01^12 - 1"),
        _row(g, "continuous_ear", 12.7497, V.ear_continuous(12), "e^0.12 - 1"),
        _row(g, "nominal_ear_round_trip", 12.0, V.nominal_from_ear(V.ear(12, 12), 12),
             "the two conversions invert each other", 1e-9),
        _row(g, "loan_payment", 8884.88, loan["payment"], "100000 x 0.01 / (1 - 1.01^-12)"),
        _row(g, "loan_clears_to_zero", 0.0, loan["schedule"][-1]["balance"],
             "the twelfth payment leaves nothing owed", 1e-6),
        _row(g, "npv", 243.426, V.npv(10, cf), "-1000 + 500 x 2.486852"),
        _row(g, "irr", 23.3752, V.irr(cf), "the rate at which the 3-year annuity factor is 2.0"),
        _row(g, "npv_at_irr_is_zero", 0.0, V.npv(V.irr(cf), cf), "the definition of IRR", 1e-6),
        _row(g, "irr_one_period", 10.0, V.irr([-100.0, 110.0]), "110 / 100 - 1", 1e-9),
        _check(g, "irr_none_without_sign_change", None, V.irr([100.0, 50.0]),
               "no outlay, no rate of return", V.irr([100.0, 50.0]) is None),
        _row(g, "mirr", 18.285, V.mirr(cf, 10, 10), "(605 + 550 + 500 = 1655) / 1000, cube root - 1"),
        _row(g, "xirr_one_year", 10.0, V.xirr([(dt.date(2025, 1, 1), -1000.0),
                                              (dt.date(2026, 1, 1), 1100.0)]),
             "365 days apart, 1100 back on 1000", 1e-6),
        _row(g, "payback", 2.5, V.payback([-1000.0, 400.0, 400.0, 400.0]),
             "-600, -200, then 200 of the third 400"),
        _row(g, "discounted_payback", 2.352, V.discounted_payback(10, cf),
             "454.55 + 413.22, then 132.23 of 375.66"),
        _row(g, "profitability_index", 1.2434, V.profitability_index(10, cf), "1243.43 / 1000"),
        _row(g, "equivalent_annual_annuity", 97.885, V.equivalent_annual_annuity(10, cf),
             "243.426 x 0.1 / (1 - 1.1^-3)"),
        _row(g, "cagr", 10.0, V.cagr(100, 121, 2), "(121 / 100)^(1/2) - 1"),
        _row(g, "holding_period_return", 15.0, V.holding_period_return(100, 110, 5),
             "(110 - 100 + 5) / 100"),
        _row(g, "time_weighted_return", 4.5, V.twr([10, -5]), "1.10 x 0.95 - 1"),
        _row(g, "geometric_mean_return", 1.8152, V.geometric_mean_return([10, -5, 1]),
             "(1.10 x 0.95 x 1.01)^(1/3) - 1, below the arithmetic 2.0"),
        _row(g, "breakeven_units", 500.0, V.breakeven_units(10000, 50, 30), "10000 / (50 - 30)"),
        _row(g, "financial_leverage", 1.5, V.degree_financial_leverage(150, 50), "150 / (150 - 50)"),
    ]


def check_derivatives():
    from . import derivatives as D
    g = "derivatives"
    gk = D.greeks(100, 100, 1, 5, 20)
    put = D.black_scholes(100, 100, 1, 5, 20, kind="put")
    american_put = D.binomial(100, 100, 1, 5, 20, steps=300, kind="put", american=True)
    return [
        _row(g, "black_scholes_call", 10.4506, gk["price"],
             "100 N(0.35) - 100 e^-0.05 N(0.15) = 63.6831 - 53.2325"),
        _row(g, "black_scholes_put", 5.5735, put, "100 e^-0.05 N(-0.15) - 100 N(-0.35)"),
        _row(g, "put_call_parity", 4.8771, gk["price"] - put, "C - P = 100 - 100 e^-0.05"),
        _row(g, "delta_call", 0.6368, gk["delta"], "N(0.35)", 0.001),
        _row(g, "gamma", 0.018762, gk["gamma"], "phi(0.35) / (100 x 0.2)", 0.0001),
        _row(g, "vega_per_point", 0.3752, gk["vegaPerPoint"], "100 x phi(0.35) / 100", 0.001),
        _row(g, "theta_per_year", -6.414, gk["thetaPerYear"],
             "-100 x phi(0.35) x 0.2 / 2 - 0.05 x 95.1229 x N(0.15)"),
        _row(g, "rho_per_point", 0.5323, gk["rhoPerPoint"], "95.1229 x N(0.15) / 100", 0.001),
        _row(g, "implied_vol_round_trip", 20.0, D.implied_vol(gk["price"], 100, 100, 1, 5),
             "the price of a 20% option implies 20%", 1e-4),
        _row(g, "binomial_converges_to_black_scholes", 10.4506,
             D.binomial(100, 100, 1, 5, 20, steps=500), "CRR tree, 500 steps", 0.02),
        _check(g, "american_put_at_least_european", True, round(american_put - put, 4),
               "early exercise can only add value", american_put >= put - 0.01),
        _row(g, "forward_price", 103.0455, D.forward_price(100, 5, 1, 2), "100 e^(0.05 - 0.02)"),
        _row(g, "fx_forward_interest_parity", 135.2019, D.fx_forward(129, 9, 4, 1),
             "129 x 1.09 / 1.04"),
        _row(g, "cross_rate", 11.6279, D.cross_rate(129, 1500), "1500 NGN / 129 KES per dollar"),
        _row(g, "fx_adjusted_return", 3.4, D.fx_adjusted_return(10, -6), "1.10 x 0.94 - 1"),
    ]


def check_performance():
    from . import risk as R
    g = "performance"
    return [
        _row(g, "treynor", 8.0, R.treynor(15, 5, 1.25), "(15 - 5) / 1.25"),
        _row(g, "jensen_alpha", 1.25, R.jensen_alpha(15, 5, 1.25, 12), "15 - (5 + 1.25 x 7)"),
        _row(g, "tracking_error", 0.7071, R.tracking_error([0.03, 0.02], [0.01, 0.01], 1),
             "sample sd of active returns 2% and 1%"),
        _row(g, "information_ratio", 2.1213, R.information_ratio([0.03, 0.02], [0.01, 0.01], 1),
             "mean active 1.5% / 0.7071%"),
        _row(g, "calmar", 0.8, R.calmar(20, -25), "20 / 25"),
        _row(g, "m_squared", 15.0, R.m_squared(0.5, 20, 5), "5 + 0.5 x 20"),
        _row(g, "two_asset_volatility", 18.0278, R.portfolio_vol_two(0.5, 20, 30, 0.0),
             "sqrt(0.25 x 400 + 0.25 x 900)"),
    ]


# Lines a fuller filing carries, added to the fixture for the extended toolkit.
TOOLKIT_CHANGES = dict(cashflow__depreciation=[50.0, 40.0], balance__payables=[150.0, 120.0],
                       cashflow__dividends_paid=[-28.0, -20.0], cashflow__icf=[-40.0, -30.0],
                       cashflow__fcf_financing=[-60.0, -50.0])

EXPECTED_TOOLKIT = {
    "ebitda":                  (200.0,  "150 EBIT + 50 depreciation"),
    "ebitda_margin":           (20.0,   "200 / 1000"),
    "net_debt_to_ebitda":      (2.5,    "500 / 200"),
    "pretax_margin":           (10.0,   "100 / 1000"),
    "tax_burden":              (0.7,    "70 / 100"),
    "interest_burden":         (0.6667, "100 / 150"),
    "cash_ratio":              (0.2,    "100 / 500"),
    "ocf_ratio":               (0.28,   "140 / 500"),
    "equity_ratio":            (40.0,   "800 / 2000"),
    "debt_ratio":              (60.0,   "1200 / 2000"),
    "non_current_asset_turnover": (0.8333, "1000 / (2000 - 800)"),
    "working_capital_turnover": (3.3333, "1000 / 300"),
    "payable_days":            (91.25,  "150 x 365 / 600"),
    "cash_conversion_cycle":   (139.92, "121.67 + 109.5 - 91.25"),
    "capex_to_revenue":        (4.0,    "40 / 1000"),
    "capex_to_depreciation":   (0.8,    "40 / 50"),
    "fcf_to_net_profit":       (1.4286, "100 / 70"),
    "cash_return_on_assets":   (7.0,    "140 / 2000"),
    "dividend_payout":         (40.0,   "28 / 70"),
    "retention_ratio":         (60.0,   "100 - 40"),
    "sustainable_growth":      (5.25,   "ROE 8.75 x 60%"),
    "roe_avg":                 (9.333,  "70 / ((800 + 700) / 2)"),
    "roa_avg":                 (3.684,  "70 / ((2000 + 1800) / 2)"),
}


def check_statement_toolkit():
    cur = S.analyse(_mutate(**TOOLKIT_CHANGES))["metrics"][0]
    out = [_row("toolkit", m, want, cur.get(m), how, 0.02)
           for m, (want, how) in EXPECTED_TOOLKIT.items()]
    parts = [cur.get(k) for k in ("tax_burden", "interest_burden", "ebit_margin",
                                  "asset_turnover", "equity_multiplier")]
    five = None
    if None not in parts:
        five = parts[0] * parts[1] * parts[2] * parts[3] * parts[4]
    out.append(_row("toolkit", "five_step_dupont_reconciles", cur["roe"], five,
                    "0.70 x 0.6667 x 15% x 0.5 x 2.5 = ROE", 0.05))
    return out


def _beneish_doc(ocf_now):
    """Two identical years, so every Beneish index is 1; only accruals vary."""
    return {"entity": {"id": "BENEISH", "name": "Beneish Test", "kind": "private"},
            "periods": ["FY2025", "FY2024"],
            "sections": {
                "income": {"revenue": [1000.0, 1000.0], "cost_of_sales": [600.0, 600.0],
                           "gross_profit": [400.0, 400.0], "operating_expenses": [250.0, 250.0],
                           "net_profit": [70.0, 70.0]},
                "balance": {"total_assets": [2000.0, 2000.0], "current_assets": [800.0, 800.0],
                            "ppe": [900.0, 900.0], "receivables": [300.0, 300.0],
                            "total_liabilities": [1200.0, 1200.0],
                            "total_equity": [800.0, 800.0]},
                "cashflow": {"ocf": [ocf_now, 70.0], "depreciation": [50.0, 50.0]}},
            "source": {"kind": "fixture"}}


def check_models_extra():
    from . import models as M
    g = "model"
    a = S.analyse(FIXTURE)
    cur = a["metrics"][0]
    zo, zp = M.altman_z_original(cur, 1400.0), M.altman_z_private(cur)
    b0 = M.beneish(S.analyse(_beneish_doc(70.0))["metrics"])
    b1 = M.beneish(S.analyse(_beneish_doc(-30.0))["metrics"])
    nob = M.beneish(a["metrics"])
    return [
        _row(g, "altman_z_listed", 1.91, zo.get("score"),
             "1.2(.15) + 1.4(.20) + 3.3(.075) + 0.6(1400/1200) + 1.0(.5) = 1.9075", 0.01),
        _check(g, "altman_z_listed_band", "grey", zo.get("band"), "between 1.81 and 2.99",
               zo.get("band") == "grey"),
        _row(g, "altman_z_private", 1.29, zp.get("score"),
             "0.717(.15) + 0.847(.20) + 3.107(.075) + 0.420(.6667) + 0.998(.5) = 1.289", 0.01),
        _row(g, "beneish_neutral_company", -2.48, b0.get("score"),
             "all indices 1, no accruals: -4.84 + the index weights", 0.005),
        _row(g, "beneish_accruals_term", -2.25, b1.get("score"),
             "TATA (70 + 30) / 2000 = 0.05 adds 4.679 x 0.05 = 0.234", 0.01),
        _check(g, "beneish_refuses_without_inputs", False, nob.get("available"),
               "the fixture has no property or depreciation lines",
               nob.get("available") is False and "ppe" in (nob.get("missing") or [])),
    ]


def check_registry():
    from . import formulas as F
    broken = []
    for fid, e in F.REGISTRY.items():
        try:
            F.run_example(e)
        except Exception as ex:
            broken.append("%s: %s" % (fid, ex))
    out = [_check("registry", "every_formula_runs_its_example", 0, len(broken),
                  "; ".join(broken[:3]) or "%d formulas" % len(F.REGISTRY), not broken)]
    cur = S.analyse(_mutate(**TOOLKIT_CHANGES))["metrics"][0]
    pairs = [("current_ratio", {"current_assets": 800, "current_liabilities": 500}, "current_ratio"),
             ("quick_ratio", {"current_assets": 800, "inventory": 200, "current_liabilities": 500},
              "quick_ratio"),
             ("roe", {"net_profit": 70, "total_equity": 800}, "roe"),
             ("interest_cover", {"ebit": 150, "finance_costs": 50}, "interest_cover"),
             ("ebitda_margin", {"ebit": 150, "depreciation": 50, "revenue": 1000}, "ebitda_margin"),
             ("payable_days", {"payables": 150, "cost_of_sales": 600}, "payable_days"),
             ("sustainable_growth", {"roe_pct": 8.75, "retention_pct": 60}, "sustainable_growth")]
    for fid, kwargs, metric in pairs:
        out.append(_row("registry", "calculator_matches_engine_" + fid, cur.get(metric),
                        F.REGISTRY[fid]["fn"](**kwargs),
                        "the calculator and statements.compute must agree", 0.01))
    return out


def check_reader():
    from . import reader as RD
    g = "reader"
    rep = RD.read(_mutate(**TOOLKIT_CHANGES))
    f = {x["metric"]: x for s in rep["sections"] for x in s["findings"]}
    life = f.get("lifecycle") or {}
    roe = f.get("roe") or {}
    bank = _mutate(**TOOLKIT_CHANGES)
    bank["entity"] = dict(bank["entity"], name="Testco Bank Ltd")
    br = RD.read(bank)
    bf = {x["metric"]: x for s in br["sections"] for x in s["findings"]}
    return [
        _check(g, "life_cycle_mature", "mature", life.get("display"),
               "operating +, investing -, financing -: Dickinson's mature stage",
               life.get("display") == "mature"),
        _check(g, "general_company_classified", "general", rep["kind"],
               "no bank, insurer or property marker", rep["kind"] == "general"),
        _check(g, "roe_judged_without_a_yield", "neutral", roe.get("verdict"),
               "8.75% with no yield on file sits between the 5% and 15% conventions",
               roe.get("verdict") == "neutral"),
        _check(g, "covered_dividend_not_flagged", False, "dividend_vs_fcf" in f,
               "28 of dividends against 100 of free cash flow", "dividend_vs_fcf" not in f),
        _check(g, "bank_liquidity_not_judged", "info", (bf.get("liquidity") or {}).get("verdict"),
               "a bank has no meaningful current ratio",
               br["kind"] == "bank" and "current_ratio" not in bf
               and (bf.get("liquidity") or {}).get("verdict") == "info"),
    ]


def run():
    results = (check_formulas() + check_identities() + check_edges() + check_models()
               + check_markets() + check_fixed_income() + check_valuation()
               + check_tvm() + check_derivatives() + check_performance()
               + check_statement_toolkit() + check_models_extra() + check_registry()
               + check_reader())
    passed = sum(1 for r in results if r["ok"])
    return {"results": results, "passed": passed, "total": len(results),
            "ok": passed == len(results)}


if __name__ == "__main__":
    rep = run()
    for r in rep["results"]:
        mark = "PASS" if r["ok"] else "FAIL"
        print("%-5s %-10s %-42s got=%-12s want=%s"
              % (mark, r["group"], r["name"], r["got"], r["expected"]))
        if not r["ok"]:
            print("        %s" % r["how"])
    print("\n%d/%d passed" % (rep["passed"], rep["total"]))
