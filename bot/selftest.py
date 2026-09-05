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


def run():
    results = check_formulas() + check_identities() + check_edges()
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
