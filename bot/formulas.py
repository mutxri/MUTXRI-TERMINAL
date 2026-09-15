#!/usr/bin/env python3
"""bot/formulas.py - every formula the bot knows, callable by name.

    python mutxri_ai.py formulas                  list them by category
    python mutxri_ai.py formulas yield            search
    python mutxri_ai.py calc npv rate_pct=10 cashflows=-1000,500,500,500
    python mutxri_ai.py calc black_scholes --example

Each entry carries its formula in words, a worked example that selftest runs,
and a one-line reading. The statement engine (statements.py) computes ratios
from filings; this registry is the same arithmetic as a calculator, for figures
you bring yourself, and selftest checks that the two agree.

Inputs are named, rates are percentages (10 means 10%), return series are
decimals per period (0.01 means 1%), cash flows start at time zero, and dated
cash flows are written date:amount;date:amount.
"""
import datetime as dt
import inspect
import math

from . import (derivatives as D, fixed_income as FI, models as M, risk as R,
               technicals as T, tvm as TV, valuation as VAL)

REGISTRY = {}
CATEGORIES = []


def reg(fid, category, name, formula, fn, example, reading=""):
    if fid in REGISTRY:
        raise ValueError("duplicate formula id %s" % fid)
    if category not in CATEGORIES:
        CATEGORIES.append(category)
    REGISTRY[fid] = {"id": fid, "category": category, "name": name, "formula": formula,
                     "fn": fn, "example": example, "reading": reading}


def _div(a, b):
    if b == 0:
        raise ZeroDivisionError("the denominator is zero")
    return a / float(b)


def _pct(a, b):
    return _div(a, b) * 100


# ------------------------------------------------------------ time value
C = "time value of money"
reg("fv", C, "Future value", "PV x (1 + r / m)^(years x m)", TV.fv,
    {"present_value": 1000, "rate_pct": 10, "years": 3}, "What a sum grows to at a compound rate.")
reg("pv", C, "Present value", "FV / (1 + r / m)^(years x m)", TV.pv,
    {"future_value": 1331, "rate_pct": 10, "years": 3}, "What a future sum is worth today.")
reg("fv_continuous", C, "Future value, continuous compounding", "PV x e^(r x years)",
    TV.fv_continuous, {"present_value": 1000, "rate_pct": 10, "years": 3})
reg("pv_continuous", C, "Present value, continuous compounding", "FV x e^(-r x years)",
    TV.pv_continuous, {"future_value": 1349.86, "rate_pct": 10, "years": 3})
reg("simple_interest", C, "Simple interest", "principal x r x years", TV.simple_interest,
    {"principal": 1000, "rate_pct": 10, "years": 3})
reg("annuity_pv", C, "Present value of an annuity",
    "PMT x (1 - (1 + r)^-n) / r; x (1 + r) if paid in advance", TV.annuity_pv,
    {"payment": 100, "rate_pct": 10, "periods": 3, "due": False})
reg("annuity_fv", C, "Future value of an annuity",
    "PMT x ((1 + r)^n - 1) / r; x (1 + r) if paid in advance", TV.annuity_fv,
    {"payment": 100, "rate_pct": 10, "periods": 3, "due": False})
reg("annuity_payment", C, "Level payment on a loan or annuity",
    "(principal - balloon / (1 + r)^n) x r / (1 - (1 + r)^-n)", TV.annuity_payment,
    {"principal": 100000, "rate_pct": 1, "periods": 12})
reg("growing_annuity_pv", C, "Present value of a growing annuity",
    "PMT1 / (r - g) x (1 - ((1 + g) / (1 + r))^n)", TV.growing_annuity_pv,
    {"first_payment": 100, "rate_pct": 10, "growth_pct": 5, "periods": 10})
reg("perpetuity", C, "Perpetuity", "PMT / r", TV.perpetuity, {"payment": 100, "rate_pct": 5})
reg("growing_perpetuity", C, "Growing perpetuity", "next PMT / (r - g)", TV.growing_perpetuity,
    {"next_payment": 100, "rate_pct": 10, "growth_pct": 5}, "Finite only while r exceeds g.")
reg("ear", C, "Effective annual rate", "(1 + nominal / m)^m - 1", TV.ear,
    {"nominal_pct": 12, "per_year": 12}, "What a quoted rate really costs once compounding is counted.")
reg("ear_continuous", C, "Effective rate, continuous compounding", "e^nominal - 1",
    TV.ear_continuous, {"nominal_pct": 12})
reg("nominal_from_ear", C, "Nominal rate from an effective rate", "m x ((1 + EAR)^(1/m) - 1)",
    TV.nominal_from_ear, {"ear_pct": 12.6825, "per_year": 12})
reg("rule_of_72", C, "Rule of 72", "72 / rate", TV.rule_of_72, {"rate_pct": 8},
    "Approximate years for money to double.")
reg("doubling_time", C, "Exact doubling time", "ln 2 / ln(1 + r)", TV.doubling_time, {"rate_pct": 8})
reg("periods_to_grow", C, "Periods to reach a target", "ln(FV / PV) / ln(1 + r)",
    TV.periods_to_grow, {"present_value": 1000, "future_value": 2000, "rate_pct": 8})
reg("loan_payment", C, "Loan instalment", "annuity payment at r / payments a year",
    lambda principal, rate_pct, years, per_year=12:
    TV.amortisation(principal, rate_pct, years, per_year)["payment"],
    {"principal": 100000, "rate_pct": 12, "years": 1, "per_year": 12})
reg("loan_total_interest", C, "Total interest over a loan", "payments x instalment - principal",
    lambda principal, rate_pct, years, per_year=12:
    TV.amortisation(principal, rate_pct, years, per_year)["totalInterest"],
    {"principal": 100000, "rate_pct": 12, "years": 1, "per_year": 12})

# ------------------------------------------------------ capital budgeting
C = "capital budgeting"
CF = [-1000.0, 500.0, 500.0, 500.0]
reg("npv", C, "Net present value", "sum of CF_t / (1 + r)^t, t from 0", TV.npv,
    {"rate_pct": 10, "cashflows": CF}, "Positive: the project earns more than the discount rate.")
reg("irr", C, "Internal rate of return", "the r at which NPV = 0", TV.irr_report,
    {"cashflows": CF}, "Compare with the cost of capital; several sign changes can mean several IRRs.")
reg("mirr", C, "Modified IRR",
    "(FV of inflows at reinvest rate / PV of outflows at finance rate)^(1/n) - 1", TV.mirr,
    {"cashflows": CF, "finance_pct": 10, "reinvest_pct": 10})
reg("xnpv", C, "NPV on actual dates", "sum of CF / (1 + r)^(days / 365)", TV.xnpv,
    {"rate_pct": 10, "dated_cashflows": [(dt.date(2025, 1, 1), -1000.0),
                                         (dt.date(2026, 1, 1), 1100.0)]})
reg("xirr", C, "IRR on actual dates", "the r at which XNPV = 0", TV.xirr,
    {"dated_cashflows": [(dt.date(2025, 1, 1), -1000.0), (dt.date(2026, 1, 1), 1100.0)]})
reg("payback", C, "Payback period", "years until cumulative cash flow reaches zero", TV.payback,
    {"cashflows": [-1000.0, 400.0, 400.0, 400.0]}, "Ignores the time value of money and later cash.")
reg("discounted_payback", C, "Discounted payback", "payback on discounted cash flows",
    TV.discounted_payback, {"rate_pct": 10, "cashflows": CF})
reg("profitability_index", C, "Profitability index", "PV of future cash flows / initial outlay",
    TV.profitability_index, {"rate_pct": 10, "cashflows": CF}, "Above 1 creates value.")
reg("equivalent_annual_annuity", C, "Equivalent annual annuity", "NPV x r / (1 - (1 + r)^-n)",
    TV.equivalent_annual_annuity, {"rate_pct": 10, "cashflows": CF},
    "Compares projects with different lives.")

# ---------------------------------------------------------------- returns
C = "returns"
reg("holding_period_return", C, "Holding period return", "(sell - buy + income) / buy",
    TV.holding_period_return, {"buy_price": 100, "sell_price": 110, "income": 5})
reg("roi", C, "Return on investment", "(final value - cost) / cost",
    lambda final_value, cost: _pct(final_value - cost, cost), {"final_value": 1150, "cost": 1000})
reg("annualised_return", C, "Annualised return", "(1 + total return)^(1 / years) - 1",
    TV.annualise, {"total_return_pct": 21, "years": 2})
reg("cagr", C, "Compound annual growth rate", "(end / begin)^(1 / years) - 1", TV.cagr,
    {"begin": 100, "end": 121, "years": 2})
reg("twr", C, "Time-weighted return", "product of (1 + sub-period return) - 1", TV.twr,
    {"period_returns_pct": [10, -5]}, "The manager's result, unaffected by money moving in or out.")
reg("arithmetic_mean_return", C, "Arithmetic mean return", "sum of returns / n",
    TV.arithmetic_mean_return, {"returns_pct": [10, -5, 8]})
reg("geometric_mean_return", C, "Geometric mean return", "(product of (1 + r))^(1/n) - 1",
    TV.geometric_mean_return, {"returns_pct": [10, -5, 8]},
    "What was actually compounded; always at or below the arithmetic mean.")
reg("expected_return", C, "Expected return", "sum of probability x outcome", TV.expected_return,
    {"outcomes_pct": [20, 5, -10], "probabilities": [0.3, 0.5, 0.2]})
reg("real_return", C, "Real return (Fisher)", "(1 + nominal) / (1 + inflation) - 1", FI.real_yield,
    {"nominal_pct": 10, "inflation_pct": 5})
reg("after_tax_return", C, "After-tax return", "return x (1 - tax rate)", FI.after_tax,
    {"yield_pct": 12, "withholding_pct": 15})
reg("fx_adjusted_return", C, "Return in the investor's currency",
    "(1 + local return) x (1 + currency change) - 1", D.fx_adjusted_return,
    {"local_return_pct": 10, "currency_change_pct": -6})

# ---------------------------------------------------------- profitability
C = "profitability"
reg("gross_margin", C, "Gross margin", "(revenue - cost of sales) / revenue",
    lambda revenue, cost_of_sales: _pct(revenue - abs(cost_of_sales), revenue),
    {"revenue": 1000, "cost_of_sales": 600}, "Pricing power over direct costs.")
reg("operating_margin", C, "Operating (EBIT) margin", "EBIT / revenue",
    lambda ebit, revenue: _pct(ebit, revenue), {"ebit": 150, "revenue": 1000})
reg("ebitda", C, "EBITDA", "EBIT + depreciation and amortisation",
    lambda ebit, depreciation: ebit + abs(depreciation), {"ebit": 150, "depreciation": 50})
reg("ebitda_margin", C, "EBITDA margin", "(EBIT + depreciation) / revenue",
    lambda ebit, depreciation, revenue: _pct(ebit + abs(depreciation), revenue),
    {"ebit": 150, "depreciation": 50, "revenue": 1000})
reg("pretax_margin", C, "Pre-tax margin", "profit before tax / revenue",
    lambda pbt, revenue: _pct(pbt, revenue), {"pbt": 100, "revenue": 1000})
reg("net_margin", C, "Net margin", "net profit / revenue",
    lambda net_profit, revenue: _pct(net_profit, revenue), {"net_profit": 70, "revenue": 1000})
reg("roe", C, "Return on equity", "net profit / shareholders' equity",
    lambda net_profit, total_equity: _pct(net_profit, total_equity),
    {"net_profit": 70, "total_equity": 800}, "Meaningless when equity is negative.")
reg("roe_average", C, "Return on average equity", "net profit / ((opening + closing equity) / 2)",
    lambda net_profit, equity_start, equity_end: _pct(net_profit, (equity_start + equity_end) / 2.0),
    {"net_profit": 70, "equity_start": 700, "equity_end": 800})
reg("roa", C, "Return on assets", "net profit / total assets",
    lambda net_profit, total_assets: _pct(net_profit, total_assets),
    {"net_profit": 70, "total_assets": 2000})
reg("roce", C, "Return on capital employed", "EBIT / (total assets - current liabilities)",
    lambda ebit, total_assets, current_liabilities: _pct(ebit, total_assets - abs(current_liabilities)),
    {"ebit": 150, "total_assets": 2000, "current_liabilities": 500},
    "Return on all long-term capital, not flattered by leverage.")
reg("nopat", C, "Net operating profit after tax", "EBIT x (1 - tax rate)",
    lambda ebit, tax_rate_pct: ebit * (1 - tax_rate_pct / 100.0), {"ebit": 150, "tax_rate_pct": 30})
reg("roic", C, "Return on invested capital", "EBIT x (1 - tax rate) / invested capital",
    lambda ebit, tax_rate_pct, invested_capital:
    _pct(ebit * (1 - tax_rate_pct / 100.0), invested_capital),
    {"ebit": 150, "tax_rate_pct": 30, "invested_capital": 1500},
    "Value is created when ROIC exceeds the cost of capital.")
reg("cash_return_on_assets", C, "Cash return on assets", "operating cash flow / total assets",
    lambda ocf, total_assets: _pct(ocf, total_assets), {"ocf": 140, "total_assets": 2000})
reg("effective_tax_rate", C, "Effective tax rate", "tax / profit before tax",
    lambda tax, pbt: _pct(abs(tax), pbt), {"tax": 30, "pbt": 100})

C = "dupont"
reg("tax_burden", C, "Tax burden", "net profit / profit before tax",
    lambda net_profit, pbt: _div(net_profit, pbt), {"net_profit": 70, "pbt": 100})
reg("interest_burden", C, "Interest burden", "profit before tax / EBIT",
    lambda pbt, ebit: _div(pbt, ebit), {"pbt": 100, "ebit": 150})
reg("asset_turnover", C, "Asset turnover", "revenue / total assets",
    lambda revenue, total_assets: _div(revenue, total_assets), {"revenue": 1000, "total_assets": 2000})
reg("equity_multiplier", C, "Equity multiplier", "total assets / equity",
    lambda total_assets, total_equity: _div(total_assets, total_equity),
    {"total_assets": 2000, "total_equity": 800})
reg("dupont_3", C, "DuPont, three-step", "net margin x asset turnover x equity multiplier",
    lambda net_margin_pct, asset_turnover, equity_multiplier:
    net_margin_pct * asset_turnover * equity_multiplier,
    {"net_margin_pct": 7, "asset_turnover": 0.5, "equity_multiplier": 2.5})
reg("dupont_5", C, "DuPont, five-step",
    "tax burden x interest burden x EBIT margin x asset turnover x equity multiplier",
    lambda tax_burden, interest_burden, ebit_margin_pct, asset_turnover, equity_multiplier:
    tax_burden * interest_burden * ebit_margin_pct * asset_turnover * equity_multiplier,
    {"tax_burden": 0.7, "interest_burden": 0.666667, "ebit_margin_pct": 15,
     "asset_turnover": 0.5, "equity_multiplier": 2.5},
    "Shows whether ROE comes from operations, financing or tax.")

# -------------------------------------------------------------- liquidity
C = "liquidity"
reg("current_ratio", C, "Current ratio", "current assets / current liabilities",
    lambda current_assets, current_liabilities: _div(current_assets, abs(current_liabilities)),
    {"current_assets": 800, "current_liabilities": 500})
reg("quick_ratio", C, "Quick (acid-test) ratio", "(current assets - inventory) / current liabilities",
    lambda current_assets, inventory, current_liabilities:
    _div(current_assets - abs(inventory), abs(current_liabilities)),
    {"current_assets": 800, "inventory": 200, "current_liabilities": 500})
reg("cash_ratio", C, "Cash ratio", "cash / current liabilities",
    lambda cash, current_liabilities: _div(cash, abs(current_liabilities)),
    {"cash": 100, "current_liabilities": 500})
reg("ocf_ratio", C, "Operating cash flow ratio", "operating cash flow / current liabilities",
    lambda ocf, current_liabilities: _div(ocf, abs(current_liabilities)),
    {"ocf": 140, "current_liabilities": 500})
reg("working_capital", C, "Working capital", "current assets - current liabilities",
    lambda current_assets, current_liabilities: current_assets - abs(current_liabilities),
    {"current_assets": 800, "current_liabilities": 500})
reg("defensive_interval", C, "Defensive interval (days)",
    "(cash + receivables) / (annual cash expenses / 365)",
    lambda cash, receivables, annual_cash_expenses:
    _div(cash + receivables, annual_cash_expenses / 365.0),
    {"cash": 100, "receivables": 300, "annual_cash_expenses": 850},
    "Days the business could run on liquid assets alone.")

# --------------------------------------------------------------- solvency
C = "solvency"
reg("debt_to_equity", C, "Debt to equity", "borrowings / equity",
    lambda borrowings, total_equity: _div(abs(borrowings), total_equity),
    {"borrowings": 600, "total_equity": 800})
reg("debt_ratio", C, "Debt ratio", "total liabilities / total assets",
    lambda total_liabilities, total_assets: _pct(abs(total_liabilities), total_assets),
    {"total_liabilities": 1200, "total_assets": 2000})
reg("equity_ratio", C, "Equity ratio", "equity / total assets",
    lambda total_equity, total_assets: _pct(total_equity, total_assets),
    {"total_equity": 800, "total_assets": 2000})
reg("capitalisation_ratio", C, "Capitalisation ratio", "debt / (debt + equity)",
    lambda borrowings, total_equity: _pct(abs(borrowings), abs(borrowings) + total_equity),
    {"borrowings": 600, "total_equity": 800})
reg("net_debt", C, "Net debt", "borrowings - cash",
    lambda borrowings, cash: abs(borrowings) - cash, {"borrowings": 600, "cash": 100})
reg("net_debt_to_ebitda", C, "Net debt to EBITDA", "(borrowings - cash) / EBITDA",
    lambda borrowings, cash, ebitda: _div(abs(borrowings) - cash, ebitda),
    {"borrowings": 600, "cash": 100, "ebitda": 200}, "Above about 3, lenders grow cautious.")
reg("interest_cover", C, "Interest cover", "EBIT / finance costs",
    lambda ebit, finance_costs: _div(ebit, abs(finance_costs)), {"ebit": 150, "finance_costs": 50},
    "Below about 2, most operating profit goes to lenders.")
reg("dscr", C, "Debt service coverage", "cash available for debt service / (interest + principal)",
    lambda cash_available, interest, principal: _div(cash_available, interest + principal),
    {"cash_available": 200, "interest": 50, "principal": 100}, "Below 1, debt cannot be serviced from cash.")
reg("fixed_charge_cover", C, "Fixed charge cover", "(EBIT + lease payments) / (interest + lease payments)",
    lambda ebit, lease_payments, interest: _div(ebit + lease_payments, interest + lease_payments),
    {"ebit": 150, "lease_payments": 30, "interest": 50})
reg("degree_financial_leverage", C, "Degree of financial leverage", "EBIT / (EBIT - interest)",
    TV.degree_financial_leverage, {"ebit": 150, "interest": 50})

# ------------------------------------------------------------- efficiency
C = "efficiency"
reg("inventory_turnover", C, "Inventory turnover", "cost of sales / inventory",
    lambda cost_of_sales, inventory: _div(abs(cost_of_sales), abs(inventory)),
    {"cost_of_sales": 600, "inventory": 200})
reg("inventory_days", C, "Inventory days", "inventory x 365 / cost of sales",
    lambda inventory, cost_of_sales: _div(abs(inventory) * 365.0, abs(cost_of_sales)),
    {"inventory": 200, "cost_of_sales": 600})
reg("receivable_turnover", C, "Receivable turnover", "revenue / receivables",
    lambda revenue, receivables: _div(revenue, abs(receivables)), {"revenue": 1000, "receivables": 300})
reg("receivable_days", C, "Receivable days (DSO)", "receivables x 365 / revenue",
    lambda receivables, revenue: _div(abs(receivables) * 365.0, revenue),
    {"receivables": 300, "revenue": 1000})
reg("payable_days", C, "Payable days (DPO)", "payables x 365 / cost of sales",
    lambda payables, cost_of_sales: _div(abs(payables) * 365.0, abs(cost_of_sales)),
    {"payables": 150, "cost_of_sales": 600})
reg("cash_conversion_cycle", C, "Cash conversion cycle",
    "inventory days + receivable days - payable days",
    lambda inventory_days, receivable_days, payable_days: inventory_days + receivable_days - payable_days,
    {"inventory_days": 121.67, "receivable_days": 109.5, "payable_days": 91.25},
    "Days cash is tied up between paying suppliers and collecting from customers.")
reg("fixed_asset_turnover", C, "Fixed (non-current) asset turnover", "revenue / non-current assets",
    lambda revenue, non_current_assets: _div(revenue, non_current_assets),
    {"revenue": 1000, "non_current_assets": 1200})
reg("working_capital_turnover", C, "Working capital turnover", "revenue / working capital",
    lambda revenue, working_capital: _div(revenue, working_capital),
    {"revenue": 1000, "working_capital": 300})

# -------------------------------------------------------------- cash flow
C = "cash flow"
reg("free_cash_flow", C, "Free cash flow", "operating cash flow - capital expenditure",
    lambda ocf, capex: ocf - abs(capex), {"ocf": 140, "capex": 40})
reg("fcff", C, "Free cash flow to the firm",
    "EBIT x (1 - tax) + depreciation - capex - increase in working capital",
    lambda ebit, tax_rate_pct, depreciation, capex, change_in_working_capital:
    ebit * (1 - tax_rate_pct / 100.0) + abs(depreciation) - abs(capex) - change_in_working_capital,
    {"ebit": 150, "tax_rate_pct": 30, "depreciation": 50, "capex": 40, "change_in_working_capital": 20})
reg("fcfe", C, "Free cash flow to equity", "FCFF - interest x (1 - tax) + net borrowing",
    lambda fcff, interest, tax_rate_pct, net_borrowing:
    fcff - interest * (1 - tax_rate_pct / 100.0) + net_borrowing,
    {"fcff": 95, "interest": 50, "tax_rate_pct": 30, "net_borrowing": 50})
reg("cash_conversion", C, "Cash conversion", "operating cash flow / net profit",
    lambda ocf, net_profit: _div(ocf, net_profit), {"ocf": 140, "net_profit": 70},
    "Persistently below 1: profit is not arriving as cash.")
reg("fcf_conversion", C, "Free cash flow conversion", "free cash flow / net profit",
    lambda fcf, net_profit: _div(fcf, net_profit), {"fcf": 100, "net_profit": 70})
reg("capex_to_revenue", C, "Capital intensity", "capex / revenue",
    lambda capex, revenue: _pct(abs(capex), revenue), {"capex": 40, "revenue": 1000})
reg("capex_to_depreciation", C, "Capex to depreciation", "capex / depreciation",
    lambda capex, depreciation: _div(abs(capex), abs(depreciation)), {"capex": 40, "depreciation": 50},
    "Below 1 for long: the asset base is shrinking.")
reg("sloan_accruals", C, "Sloan accruals ratio", "(net profit - operating cash flow) / average assets",
    lambda net_profit, ocf, average_total_assets: _pct(net_profit - ocf, average_total_assets),
    {"net_profit": 70, "ocf": 140, "average_total_assets": 1900},
    "High accruals predict weaker earnings ahead.")

# ------------------------------------------------ per share and multiples
C = "per share and multiples"
reg("eps", C, "Earnings per share", "(net profit - preference dividends) / shares",
    lambda net_profit, shares, preference_dividends=0.0: _div(net_profit - preference_dividends, shares),
    {"net_profit": 70, "shares": 100})
reg("bvps", C, "Book value per share", "equity / shares",
    lambda total_equity, shares: _div(total_equity, shares), {"total_equity": 800, "shares": 100})
reg("dps", C, "Dividend per share", "dividends / shares",
    lambda dividends, shares: _div(abs(dividends), shares), {"dividends": 28, "shares": 100})
reg("market_cap", C, "Market capitalisation", "price x shares",
    lambda price, shares: price * shares, {"price": 14, "shares": 100})
reg("pe", C, "Price to earnings", "price / EPS",
    lambda price, eps: _div(price, eps), {"price": 14, "eps": 0.7}, "Not meaningful for a loss.")
reg("peg", C, "PEG ratio", "P/E / earnings growth %",
    lambda pe, growth_pct: _div(pe, growth_pct), {"pe": 20, "growth_pct": 15})
reg("pb", C, "Price to book", "price / book value per share",
    lambda price, bvps: _div(price, bvps), {"price": 14, "bvps": 8})
reg("ps", C, "Price to sales", "market cap / revenue",
    lambda market_cap, revenue: _div(market_cap, revenue), {"market_cap": 1400, "revenue": 1000})
reg("price_to_cash_flow", C, "Price to operating cash flow", "market cap / operating cash flow",
    lambda market_cap, ocf: _div(market_cap, ocf), {"market_cap": 1400, "ocf": 140})
reg("enterprise_value", C, "Enterprise value",
    "market cap + borrowings - cash + minorities + preference shares",
    lambda market_cap, borrowings, cash, minorities=0.0, preference=0.0:
    market_cap + abs(borrowings) - cash + minorities + preference,
    {"market_cap": 1400, "borrowings": 600, "cash": 100})
reg("ev_ebitda", C, "EV to EBITDA", "enterprise value / EBITDA",
    lambda enterprise_value, ebitda: _div(enterprise_value, ebitda),
    {"enterprise_value": 1900, "ebitda": 200})
reg("ev_ebit", C, "EV to EBIT", "enterprise value / EBIT",
    lambda enterprise_value, ebit: _div(enterprise_value, ebit), {"enterprise_value": 1900, "ebit": 150})
reg("ev_sales", C, "EV to sales", "enterprise value / revenue",
    lambda enterprise_value, revenue: _div(enterprise_value, revenue),
    {"enterprise_value": 1900, "revenue": 1000})
reg("earnings_yield", C, "Earnings yield", "EPS / price",
    lambda eps, price: _pct(eps, price), {"eps": 0.7, "price": 14},
    "Set it beside the government bond yield.")
reg("fcf_yield", C, "Free cash flow yield", "free cash flow / market cap",
    lambda fcf, market_cap: _pct(fcf, market_cap), {"fcf": 100, "market_cap": 1400})
reg("dividend_yield", C, "Dividend yield", "dividend per share / price",
    lambda dps, price: _pct(dps, price), {"dps": 0.28, "price": 14})
reg("graham_number", C, "Graham number", "sqrt(22.5 x EPS x book value per share)",
    lambda eps, bvps: math.sqrt(22.5 * eps * bvps) if eps > 0 and bvps > 0 else None,
    {"eps": 0.7, "bvps": 8})

# -------------------------------------------------- dividends and growth
C = "dividends and growth"
reg("payout_ratio", C, "Dividend payout ratio", "dividends / net profit",
    lambda dividends, net_profit: _pct(abs(dividends), net_profit), {"dividends": 28, "net_profit": 70})
reg("retention_ratio", C, "Retention ratio", "1 - payout ratio",
    lambda dividends, net_profit: 100 - _pct(abs(dividends), net_profit),
    {"dividends": 28, "net_profit": 70})
reg("dividend_cover", C, "Dividend cover", "net profit / dividends",
    lambda net_profit, dividends: _div(net_profit, abs(dividends)), {"net_profit": 70, "dividends": 28})
reg("sustainable_growth", C, "Sustainable growth rate", "ROE x retention ratio",
    lambda roe_pct, retention_pct: roe_pct * retention_pct / 100.0,
    {"roe_pct": 8.75, "retention_pct": 60}, "Growth fundable without new equity or more leverage.")
reg("internal_growth", C, "Internal growth rate", "ROA x b / (1 - ROA x b)",
    lambda roa_pct, retention_pct:
    _div(roa_pct / 100.0 * retention_pct / 100.0, 1 - roa_pct / 100.0 * retention_pct / 100.0) * 100,
    {"roa_pct": 3.5, "retention_pct": 60}, "Growth fundable from retained profit alone, with no borrowing.")

# -------------------------------------------------------- equity valuation
C = "equity valuation"
reg("capm", C, "Cost of equity (CAPM)", "risk-free + beta x equity risk premium + country premium",
    VAL.capm, {"rf_pct": 10, "beta": 1.2, "erp_pct": 6})
reg("wacc", C, "Weighted average cost of capital", "E/V x Re + D/V x Rd x (1 - tax)", VAL.wacc,
    {"equity": 600, "debt": 400, "cost_equity_pct": 15, "cost_debt_pct": 10, "tax_pct": 30})
reg("levered_beta", C, "Levered beta (Hamada)", "unlevered beta x (1 + (1 - tax) x D/E)",
    lambda unlevered_beta, debt, equity, tax_pct:
    unlevered_beta * (1 + (1 - tax_pct / 100.0) * _div(debt, equity)),
    {"unlevered_beta": 0.8, "debt": 400, "equity": 600, "tax_pct": 30})
reg("unlevered_beta", C, "Unlevered beta (Hamada)", "levered beta / (1 + (1 - tax) x D/E)",
    lambda levered_beta, debt, equity, tax_pct:
    levered_beta / (1 + (1 - tax_pct / 100.0) * _div(debt, equity)),
    {"levered_beta": 1.1733, "debt": 400, "equity": 600, "tax_pct": 30})
reg("gordon_growth", C, "Gordon growth value", "next cash flow / (r - g)", VAL.gordon,
    {"cash_flow_next": 2.1, "r_pct": 10, "g_pct": 5})
reg("ddm", C, "Dividend discount model", "D0 x (1 + g) / (r - g)", VAL.ddm,
    {"dividend_now": 2, "r_pct": 10, "g_pct": 5})
reg("dcf", C, "Discounted cash flow",
    "sum of FCF_t / (1 + r)^t + FCF_n x (1 + g) / (r - g) / (1 + r)^n",
    lambda fcf0, r_pct, terminal_g_pct, growth_pct, years:
    {k: v for k, v in VAL.dcf(fcf0, r_pct, terminal_g_pct, growth_pct, years).items() if k != "years"},
    {"fcf0": 100, "r_pct": 10, "terminal_g_pct": 5, "growth_pct": 10, "years": 2})
reg("reverse_dcf", C, "Implied growth (reverse DCF)", "the growth at which DCF value = target EV",
    VAL.reverse_dcf, {"target_ev": 2300, "fcf0": 100, "r_pct": 10, "terminal_g_pct": 5, "years": 2})
reg("justified_pe", C, "Justified P/E", "payout x (1 + g) / (r - g)",
    lambda payout_pct, growth_pct, r_pct:
    _div(payout_pct / 100.0 * (1 + growth_pct / 100.0), (r_pct - growth_pct) / 100.0),
    {"payout_pct": 40, "growth_pct": 5, "r_pct": 12})
reg("justified_pb", C, "Justified P/B", "(ROE - g) / (r - g)",
    lambda roe_pct, growth_pct, r_pct: _div(roe_pct - growth_pct, r_pct - growth_pct),
    {"roe_pct": 15, "growth_pct": 5, "r_pct": 12}, "Above 1 only when ROE exceeds the cost of equity.")
reg("residual_income_value", C, "Residual income value", "book value + book x (ROE - r) / (r - g)",
    lambda book_value, roe_pct, r_pct, growth_pct:
    book_value + book_value * _div(roe_pct - r_pct, r_pct - growth_pct),
    {"book_value": 800, "roe_pct": 15, "r_pct": 12, "growth_pct": 5})
reg("margin_of_safety", C, "Margin of safety", "(value - price) / value", VAL.margin_of_safety,
    {"value": 20, "market_price": 14})

# ---------------------------------------------------------------- banking
C = "banking"
reg("loan_to_deposit", C, "Loan to deposit ratio", "loans / customer deposits",
    lambda loans, deposits: _pct(loans, deposits), {"loans": 850, "deposits": 1000},
    "Above 100%: lending relies on wholesale funding.")
reg("net_interest_margin", C, "Net interest margin", "net interest income / average earning assets",
    lambda net_interest_income, average_earning_assets: _pct(net_interest_income, average_earning_assets),
    {"net_interest_income": 60, "average_earning_assets": 1000})
reg("cost_to_income", C, "Cost to income", "operating expenses / operating income",
    lambda operating_expenses, operating_income: _pct(abs(operating_expenses), operating_income),
    {"operating_expenses": 50, "operating_income": 100}, "Below 50% is efficient for a bank.")
reg("cost_of_risk", C, "Cost of risk", "loan impairment charges / average loans",
    lambda impairment_charges, average_loans: _pct(abs(impairment_charges), average_loans),
    {"impairment_charges": 15, "average_loans": 850})
reg("npl_ratio", C, "Non-performing loan ratio", "non-performing loans / gross loans",
    lambda non_performing_loans, gross_loans: _pct(non_performing_loans, gross_loans),
    {"non_performing_loans": 90, "gross_loans": 900})
reg("npl_coverage", C, "NPL coverage", "loan loss provisions / non-performing loans",
    lambda loan_loss_provisions, non_performing_loans: _pct(loan_loss_provisions, non_performing_loans),
    {"loan_loss_provisions": 60, "non_performing_loans": 90})
reg("capital_adequacy", C, "Capital adequacy ratio", "(tier 1 + tier 2 capital) / risk-weighted assets",
    lambda tier1_capital, tier2_capital, risk_weighted_assets:
    _pct(tier1_capital + tier2_capital, risk_weighted_assets),
    {"tier1_capital": 120, "tier2_capital": 30, "risk_weighted_assets": 900})
reg("leverage_ratio", C, "Basel leverage ratio", "tier 1 capital / total exposure",
    lambda tier1_capital, total_exposure: _pct(tier1_capital, total_exposure),
    {"tier1_capital": 120, "total_exposure": 1500})

# -------------------------------------------------------------- insurance
C = "insurance"
reg("loss_ratio", C, "Loss ratio", "claims incurred / net earned premium",
    lambda claims_incurred, net_earned_premium: _pct(abs(claims_incurred), net_earned_premium),
    {"claims_incurred": 650, "net_earned_premium": 1000})
reg("expense_ratio", C, "Expense ratio", "operating expenses / net earned premium",
    lambda operating_expenses, net_earned_premium: _pct(abs(operating_expenses), net_earned_premium),
    {"operating_expenses": 300, "net_earned_premium": 1000})
reg("combined_ratio", C, "Combined ratio", "(claims + expenses) / net earned premium",
    lambda claims_incurred, operating_expenses, net_earned_premium:
    _pct(abs(claims_incurred) + abs(operating_expenses), net_earned_premium),
    {"claims_incurred": 650, "operating_expenses": 300, "net_earned_premium": 1000},
    "Above 100%: an underwriting loss.")

# -------------------------------------------------- credit and distress
C = "credit and distress"
_Z = {"working_capital": 300, "retained_earnings": 400, "ebit": 150, "total_equity": 800,
      "total_liabilities": 1200, "total_assets": 2000}
reg("altman_z_em", C, "Altman Z'' (emerging markets)",
    "6.56 WC/TA + 3.26 RE/TA + 6.72 EBIT/TA + 1.05 equity/liabilities + 3.25",
    lambda working_capital, retained_earnings, ebit, total_equity, total_liabilities, total_assets:
    M.altman_z(dict(working_capital=working_capital, retained_earnings=retained_earnings, ebit=ebit,
                    total_equity=total_equity, total_liabilities=total_liabilities,
                    total_assets=total_assets)),
    dict(_Z), "Below 1.1 distress, above 2.6 safe.")
reg("altman_z_listed", C, "Altman Z (listed manufacturers)",
    "1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 market cap/liabilities + 1.0 sales/TA",
    lambda working_capital, retained_earnings, ebit, total_liabilities, total_assets, revenue, market_cap:
    M.altman_z_original(dict(working_capital=working_capital, retained_earnings=retained_earnings,
                             ebit=ebit, total_liabilities=total_liabilities,
                             total_assets=total_assets, revenue=revenue), market_cap),
    dict({k: v for k, v in _Z.items() if k != "total_equity"}, revenue=1000, market_cap=1400),
    "Below 1.81 distress, above 2.99 safe.")
reg("altman_z_private", C, "Altman Z' (private companies)",
    "0.717 WC/TA + 0.847 RE/TA + 3.107 EBIT/TA + 0.420 equity/liabilities + 0.998 sales/TA",
    lambda working_capital, retained_earnings, ebit, total_equity, total_liabilities, total_assets, revenue:
    M.altman_z_private(dict(working_capital=working_capital, retained_earnings=retained_earnings,
                            ebit=ebit, total_equity=total_equity, total_liabilities=total_liabilities,
                            total_assets=total_assets, revenue=revenue)),
    dict(_Z, revenue=1000), "Below 1.23 distress, above 2.90 safe.")
reg("beneish_m", C, "Beneish M-score (8 variables)",
    "-4.84 + .920 DSRI + .528 GMI + .404 AQI + .892 SGI + .115 DEPI - .172 SGAI + 4.679 TATA - .327 LVGI",
    lambda dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi:
    {"score": M.beneish_from_indices(dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi),
     "likelyManipulator": M.beneish_from_indices(dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi)
     > M.BENEISH_THRESHOLD},
    {"dsri": 1, "gmi": 1, "aqi": 1, "sgi": 1, "depi": 1, "sgai": 1, "tata": 0, "lvgi": 1},
    "Above -1.78 matches the pattern of earnings manipulation.")
reg("debt_to_ebitda", C, "Debt to EBITDA", "borrowings / EBITDA",
    lambda borrowings, ebitda: _div(abs(borrowings), ebitda), {"borrowings": 600, "ebitda": 200})

# ---------------------------------------------------- risk and performance
C = "risk and performance"
RET = [0.01, -0.005, 0.012, -0.008, 0.004, 0.009, -0.011, 0.006]
reg("sharpe", C, "Sharpe ratio", "(mean return - risk-free) / volatility, annualised",
    lambda returns, rf_pct=0.0, periods_per_year=252:
    R.sharpe(returns, rf_pct) * math.sqrt(periods_per_year / 252.0) if R.sharpe(returns, rf_pct) is not None else None,
    {"returns": RET, "rf_pct": 0.0})
reg("sortino", C, "Sortino ratio", "(mean return - risk-free) / downside deviation, annualised",
    lambda returns, rf_pct=0.0: R.sortino(returns, rf_pct), {"returns": RET, "rf_pct": 0.0})
reg("treynor", C, "Treynor ratio", "(portfolio return - risk-free) / beta", R.treynor,
    {"return_pct": 15, "rf_pct": 5, "beta_coef": 1.25})
reg("jensen_alpha", C, "Jensen's alpha", "return - (risk-free + beta x (market - risk-free))",
    R.jensen_alpha, {"return_pct": 15, "rf_pct": 5, "beta_coef": 1.25, "market_return_pct": 12})
reg("tracking_error", C, "Tracking error", "standard deviation of (portfolio - benchmark), annualised",
    R.tracking_error, {"portfolio": [0.03, 0.02], "benchmark": [0.01, 0.01], "periods_per_year": 1})
reg("information_ratio", C, "Information ratio", "mean active return / tracking error",
    R.information_ratio, {"portfolio": [0.03, 0.02], "benchmark": [0.01, 0.01], "periods_per_year": 1})
reg("calmar", C, "Calmar ratio", "annual return / maximum drawdown", R.calmar,
    {"annual_return_pct": 20, "max_drawdown_pct": -25})
reg("m_squared", C, "M-squared (Modigliani)", "risk-free + Sharpe x benchmark volatility", R.m_squared,
    {"sharpe_ratio": 0.5, "benchmark_vol_pct": 20, "rf_pct": 5})
reg("beta", C, "Beta", "covariance(asset, market) / variance(market)",
    lambda asset_returns, market_returns: R.beta(asset_returns, market_returns),
    {"asset_returns": [0.02, -0.04, 0.06], "market_returns": [0.01, -0.02, 0.03]})
reg("annualised_volatility", C, "Annualised volatility", "standard deviation x sqrt(periods a year)",
    lambda returns, periods_per_year=252: T.stdev(returns) * math.sqrt(periods_per_year) * 100,
    {"returns": RET, "periods_per_year": 252})
reg("var_historical", C, "Historical value at risk", "the k-th worst return, k = ceil((1 - level) x n)",
    lambda returns, level=0.95: R.var_historical(returns, level), {"returns": RET, "level": 0.95})
reg("var_parametric", C, "Parametric value at risk", "z x volatility - mean return",
    lambda mean_return_pct, vol_pct, level=0.95: R.Z[level] * vol_pct - mean_return_pct,
    {"mean_return_pct": 0.05, "vol_pct": 1.4, "level": 0.95})
reg("max_drawdown", C, "Maximum drawdown", "largest peak-to-trough fall",
    lambda prices: T.max_drawdown(prices), {"prices": [100, 120, 90, 95, 130, 104]})
reg("portfolio_vol_two", C, "Two-asset portfolio volatility",
    "sqrt(w1^2 s1^2 + w2^2 s2^2 + 2 w1 w2 rho s1 s2)", R.portfolio_vol_two,
    {"weight_1": 0.5, "vol_1_pct": 20, "vol_2_pct": 30, "correlation": 0.0})
reg("coefficient_of_variation", C, "Coefficient of variation", "volatility / mean return",
    lambda vol_pct, mean_return_pct: _div(vol_pct, mean_return_pct), {"vol_pct": 20, "mean_return_pct": 12},
    "Risk per unit of return.")

# ----------------------------------------------------------- fixed income
C = "fixed income"
_B = {"face": 100, "coupon_pct": 10, "ytm_pct": 10, "years": 5, "freq": 1}
reg("bond_price", C, "Bond price", "sum of coupon / (1 + y/f)^t + face / (1 + y/f)^n", FI.price, dict(_B))
reg("ytm", C, "Yield to maturity", "the yield at which the bond price equals the market price",
    lambda price, face, coupon_pct, years, freq=2: FI.ytm(price, face, coupon_pct, years, freq),
    {"price": 92.7904, "face": 100, "coupon_pct": 10, "years": 5, "freq": 1})
reg("bond_risk", C, "Duration, convexity and DV01", "Macaulay, modified, convexity, DV01", FI.risk, dict(_B))
reg("macaulay_duration", C, "Macaulay duration", "sum of t x PV(cash flow) / price",
    lambda face, coupon_pct, ytm_pct, years, freq=2: FI.risk(face, coupon_pct, ytm_pct, years, freq)["macaulayDuration"],
    dict(_B))
reg("modified_duration", C, "Modified duration", "Macaulay duration / (1 + y/f)",
    lambda face, coupon_pct, ytm_pct, years, freq=2: FI.risk(face, coupon_pct, ytm_pct, years, freq)["modifiedDuration"],
    dict(_B), "Approximate % price change for a 1-point yield move.")
reg("convexity", C, "Convexity", "sum of t(t + 1) PV(cash flow) / (price x (1 + y/f)^2 x f^2)",
    lambda face, coupon_pct, ytm_pct, years, freq=2: FI.risk(face, coupon_pct, ytm_pct, years, freq)["convexity"],
    dict(_B))
reg("price_change_estimate", C, "Price change for a yield move",
    "-modified duration x dy + 0.5 x convexity x dy^2", FI.price_change,
    {"modified_duration": 3.7908, "convexity": 19.3683, "current_price": 100, "bp": 100})
reg("current_yield", C, "Current yield", "annual coupon / price",
    lambda annual_coupon, price: _pct(annual_coupon, price), {"annual_coupon": 10, "price": 92.79})
reg("zero_coupon_price", C, "Zero-coupon bond price", "face / (1 + y)^years",
    lambda face, ytm_pct, years: face / (1 + ytm_pct / 100.0) ** years,
    {"face": 100, "ytm_pct": 10, "years": 5})
reg("accrued_interest", C, "Accrued interest (actual/actual)",
    "coupon per period x days since last coupon / days in period",
    lambda face, coupon_pct, freq, last_coupon, next_coupon, settle:
    FI.accrued_interest(face, coupon_pct, freq, dt.date.fromisoformat(str(last_coupon)),
                        dt.date.fromisoformat(str(next_coupon)), dt.date.fromisoformat(str(settle))),
    {"face": 100, "coupon_pct": 10, "freq": 2, "last_coupon": "2026-01-01",
     "next_coupon": "2026-07-01", "settle": "2026-04-01"})
reg("bill_price", C, "Bill price from yield", "100 / (1 + yield x days / basis)", FI.bill_price,
    {"yield_pct": 8.77, "days": 91, "basis": 364})
reg("bill_yield", C, "Bill yield from price", "(100 / price - 1) x basis / days",
    lambda price, days, basis=365: FI.bill_yield(price, days, basis), {"price": 97.8545, "days": 91, "basis": 364})
reg("discount_price", C, "Bill price from discount rate", "100 x (1 - discount x days / basis)",
    FI.discount_price, {"discount_pct": 16, "days": 182, "basis": 365})
reg("discount_to_yield", C, "Discount rate to true yield", "d / (1 - d x days / basis)",
    FI.discount_to_yield, {"discount_pct": 16, "days": 182, "basis": 365})
reg("yield_to_discount", C, "True yield to discount rate", "y / (1 + y x days / basis)",
    FI.yield_to_discount, {"yield_pct": 17.3871, "days": 182, "basis": 365})
reg("real_yield", C, "Real yield (Fisher)", "(1 + nominal) / (1 + inflation) - 1", FI.real_yield,
    {"nominal_pct": 17, "inflation_pct": 12})

# ------------------------------------------------------------ derivatives
C = "derivatives"
_O = {"spot": 100, "strike": 100, "years": 1, "rate_pct": 5, "vol_pct": 20}
reg("black_scholes", C, "Black-Scholes-Merton option price",
    "call: S e^-qT N(d1) - K e^-rT N(d2); put: K e^-rT N(-d2) - S e^-qT N(-d1)",
    D.black_scholes, dict(_O, kind="call"))
reg("greeks", C, "Option greeks", "delta, gamma, vega, theta, rho", D.greeks, dict(_O, kind="call"))
reg("implied_vol", C, "Implied volatility", "the volatility at which the model price equals the market price",
    D.implied_vol, {"price": 10.4506, "spot": 100, "strike": 100, "years": 1, "rate_pct": 5, "kind": "call"})
reg("binomial_option", C, "Binomial option price (CRR)",
    "u = e^(s sqrt dt), p = (e^((r - q) dt) - d) / (u - d), backward induction",
    D.binomial, dict(_O, steps=200, kind="put", american=True), "American options exercise early where it pays.")
reg("put_call_parity", C, "Put-call parity", "C - P = S e^-qT - K e^-rT", D.put_call_parity,
    {"spot": 100, "strike": 100, "years": 1, "rate_pct": 5, "call": 10.4506})
reg("option_payoff", C, "Option payoff at expiry", "max(S - K, 0) or max(K - S, 0), less premium",
    D.option_payoff, {"kind": "call", "price_at_expiry": 115, "strike": 100, "premium": 10.45, "long": True})
reg("forward_price", C, "Forward price (cost of carry)", "S x e^((r - q + storage) x T)", D.forward_price,
    {"spot": 100, "rate_pct": 5, "years": 1, "dividend_yield_pct": 2})

# --------------------------------------------------------------------- fx
C = "fx"
reg("fx_forward", C, "FX forward (covered interest parity)",
    "spot x (1 + domestic rate x T) / (1 + foreign rate x T)", D.fx_forward,
    {"spot": 129, "domestic_rate_pct": 9, "foreign_rate_pct": 4, "years": 1},
    "The higher-rate currency trades at a forward discount.")
reg("forward_points", C, "Forward points", "forward - spot", D.forward_points, {"spot": 129, "forward": 135.2})
reg("forward_premium", C, "Forward premium", "forward / spot - 1", D.forward_premium,
    {"spot": 129, "forward": 135.2})
reg("cross_rate", C, "Cross rate through the dollar", "quote per USD / base per USD", D.cross_rate,
    {"base_per_usd": 129, "quote_per_usd": 1500})

# ------------------------------------------------------- cost and break-even
C = "cost and break-even"
reg("contribution_margin_ratio", C, "Contribution margin ratio", "(price - variable cost) / price",
    TV.contribution_margin_ratio, {"price": 50, "variable_cost": 30})
reg("breakeven_units", C, "Break-even units", "fixed costs / (price - variable cost)", TV.breakeven_units,
    {"fixed_costs": 10000, "price": 50, "variable_cost": 30})
reg("breakeven_revenue", C, "Break-even revenue", "fixed costs / contribution margin ratio",
    TV.breakeven_revenue, {"fixed_costs": 10000, "contribution_margin_pct": 40})
reg("margin_of_safety_sales", C, "Margin of safety (sales)", "(sales - break-even sales) / sales",
    TV.margin_of_safety_sales, {"sales": 30000, "breakeven_sales": 25000})
reg("degree_operating_leverage", C, "Degree of operating leverage", "% change in EBIT / % change in revenue",
    lambda ebit_change_pct, revenue_change_pct: _div(ebit_change_pct, revenue_change_pct),
    {"ebit_change_pct": 50, "revenue_change_pct": 25})
reg("degree_total_leverage", C, "Degree of total leverage", "operating leverage x financial leverage",
    lambda dol, dfl: dol * dfl, {"dol": 2, "dfl": 1.5})


# ------------------------------------------------------------------ access
def get(fid):
    return REGISTRY.get(str(fid).strip().lower().replace("-", "_"))


def params(entry):
    """[(name, required)] in call order."""
    return [(n, p.default is inspect.Parameter.empty)
            for n, p in inspect.signature(entry["fn"]).parameters.items()]


def search(query=None, category=None):
    q = (query or "").lower()
    out = []
    for e in REGISTRY.values():
        if category and category.lower() not in e["category"]:
            continue
        hay = " ".join((e["id"], e["name"], e["formula"], e["category"])).lower()
        if q and q not in hay:
            continue
        out.append(e)
    return out


def parse_value(text, like):
    """Read a command-line value the way the example's value is typed."""
    if isinstance(like, bool):
        return text.strip().lower() in ("1", "true", "yes", "y")
    if isinstance(like, (list, tuple)):
        if like and isinstance(like[0], (list, tuple)):
            rows = []
            for part in text.split(";"):
                if not part.strip():
                    continue
                d, _, amount = part.rpartition(":")
                rows.append((dt.date.fromisoformat(d.strip()), float(amount)))
            return rows
        return [float(x) for x in text.split(",") if x.strip()]
    if isinstance(like, str):
        return text
    if isinstance(like, int):
        v = float(text)
        return int(v) if v.is_integer() else v
    try:
        return float(text)
    except ValueError:
        return text


def format_input(v):
    if isinstance(v, (list, tuple)):
        if v and isinstance(v[0], (list, tuple)):
            return ";".join("%s:%g" % (d, a) for d, a in v)
        return ",".join("%g" % x for x in v)
    return str(v)


def example_args(entry):
    return " ".join("%s=%s" % (k, format_input(v)) for k, v in entry["example"].items())


def run_example(entry):
    return entry["fn"](**entry["example"])
