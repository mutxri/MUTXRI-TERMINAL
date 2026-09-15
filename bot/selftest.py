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


def run():
    results = (check_formulas() + check_identities() + check_edges() + check_models()
               + check_markets() + check_fixed_income() + check_valuation())
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
