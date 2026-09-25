"""Smoke-test the bot's data logic without a token."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot  # noqa: E402

stocks = bot.listings()
print("total stocks loaded:", len(stocks))
by_ex = {}
for s in stocks:
    by_ex[s["ex"]] = by_ex.get(s["ex"], 0) + 1
print("by exchange:", by_ex)

for q in ["SCOM", "EABL", "INFI", "4SI.JO", "4SI", "ZENITHBANK", "ABSA", "DANGSUGAR"]:
    s = bot._find_stock(q)
    print(f"  find {q!r}:", (s["ticker"] + " [" + s["ex"] + "]") if s else "NOT FOUND")

fs = bot.financials_summary(bot._find_stock("EABL"))
print("EABL financials periods:", fs["periods"] if fs else None)
print("EABL revenue:", fs["rows"].get("revenue") if fs else None)
print("EABL netProfit:", fs["rows"].get("netProfit") if fs else None)
print("EABL currency:", fs["currency"] if fs else None)

print("indices count:", len(bot.indices()))
for e in bot.indices()[:4]:
    print("  idx:", e.get("label"), e.get("price"), e.get("changePct"))

# movers scope test
up = [s for s in stocks if isinstance(s.get("chgPct"), (int, float))]
up.sort(key=lambda s: s["chgPct"], reverse=True)
print("top gainer overall:", up[0]["ticker"], up[0]["chgPct"], "on", up[0]["ex"])

print("fmt tests:", bot.fmt_num(54100000000, "KES"), bot.fmt_num(157.03, "EGP"), bot.fmt_pct(-1.29))
