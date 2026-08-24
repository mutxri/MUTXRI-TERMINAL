"""
/api/ratings — Analyst ratings aggregation for AFRI Terminal (spec 9.3, P2).
HONEST SCOPE (read first): real analyst consensus (verified broker
ratings + price targets) requires licensed data — Refinitiv, Bloomberg,
FactSet. None of that is free. What IS obtainable is *mentions* of broker
actions in public news (Google News RSS queries like
"TICKER broker rating target price"). So this module extracts INDICATIVE
rating signals from news headlines and tallies them into a rough lean —
clearly labeled as news-derived and indicative, NOT a licensed consensus.
It never fabricates a rating. If no rating language is found in the news,
it returns "no rating signal" — it does not invent Buy/Hold/Sell.
Python stdlib ONLY. The news items come from whatever RSS the server
already fetches (see reg_api.py for the pattern). This module only does
the extraction + tally, which is the testable part. Wire in:
    from ratings_api import aggregate_ratings
    if parsed.path == "/api/ratings":
        items = fetch_news_for(symbol)          # [{headline, link, date}]
        return self._send_json(aggregate_ratings(symbol, items))
"""
import re
from typing import List, Optional
# Rating vocabulary -> normalized bucket + a numeric lean (-2..+2) so we
# can compute an average tilt. Order matters for matching specificity.
RATING_TERMS = [
    ("strong buy", "Buy", 2),
    ("outperform", "Buy", 1),
    ("overweight", "Buy", 1),
    ("accumulate", "Buy", 1),
    ("buy", "Buy", 2),
    ("add", "Buy", 1),
    ("hold", "Hold", 0),
    ("neutral", "Hold", 0),
    ("equal-weight", "Hold", 0),
    ("equalweight", "Hold", 0),
    ("market perform", "Hold", 0),
    ("underperform", "Sell", -1),
    ("underweight", "Sell", -1),
    ("reduce", "Sell", -1),
    ("strong sell", "Sell", -2),
    ("sell", "Sell", -2),
]
# Price target patterns: "target price of 250", "PT 250", "price target: 250",
# "raises target to 1,200", "cuts PT to 98.5"
TARGET_PATTERNS = [
    re.compile(r"(?:price target|target price|pt)[^0-9]{0,12}([0-9][0-9,]*\.?[0-9]*)", re.I),
    re.compile(r"target[^0-9]{0,8}(?:to|of|at)\s+([0-9][0-9,]*\.?[0-9]*)", re.I),
    # Bare "target 58" — 'target' followed closely by a number with no
    # connecting word. Kept last so the more specific patterns win first.
    re.compile(r"target\s+([0-9][0-9,]*\.?[0-9]*)", re.I),
]
def _extract_rating(text):
    """Return (bucket, lean) for the first rating term found, else None."""
    t = (text or "").lower()
    for term, bucket, lean in RATING_TERMS:
        # word-ish boundary so "buy" doesn't match "buyer"/"buyout" loosely;
        # allow the term as a standalone-ish token.
        if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", t):
            return bucket, lean
    return None
def _extract_target(text):
    for pat in TARGET_PATTERNS:
        m = pat.search(text or "")
        if m:
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
                if val > 0:
                    return val
            except ValueError:
                continue
    return None
def aggregate_ratings(symbol: str, news_items: List[dict]) -> dict:
    """
    news_items: [{headline, link, date}]. Extract indicative rating signals
    and price targets; tally into a rough lean. Never invents a rating.
    """
    signals = []
    buckets = {"Buy": 0, "Hold": 0, "Sell": 0}
    lean_sum = 0
    targets = []
    for item in news_items or []:
        headline = item.get("headline") or ""
        rating = _extract_rating(headline)
        target = _extract_target(headline)
        if rating is None and target is None:
            continue  # not a rating-bearing item; skip, don't force one
        if rating is not None:
            bucket, lean = rating
            buckets[bucket] += 1
            lean_sum += lean
        if target is not None:
            targets.append(target)
        signals.append({
            "headline": headline,
            "rating": rating[0] if rating else None,
            "target": target,
            "date": item.get("date"),
            "link": item.get("link"),
        })
    total = buckets["Buy"] + buckets["Hold"] + buckets["Sell"]
    if total == 0:
        consensus = None
        confidence = "none"
    else:
        avg_lean = lean_sum / total
        if avg_lean >= 0.6:
            consensus = "Buy (lean)"
        elif avg_lean <= -0.6:
            consensus = "Sell (lean)"
        else:
            consensus = "Hold (lean)"
        # Confidence is deliberately conservative: news-derived signal.
        if total >= 5:
            confidence = "moderate"
        elif total >= 2:
            confidence = "low"
        else:
            confidence = "very low"
    avg_target = round(sum(targets) / len(targets), 2) if targets else None
    return {
        "symbol": symbol,
        "consensus": consensus,          # None if no signal — never faked
        "confidence": confidence,
        "tally": buckets,
        "signal_count": total,
        "avg_target": avg_target,
        "target_count": len(targets),
        "signals": signals[:20],
        # Prominent, non-negotiable honesty label:
        "disclaimer": "Indicative only — derived from public news mentions, "
                      "NOT a licensed analyst consensus. Full consensus and "
                      "verified price targets require Refinitiv/Bloomberg/FactSet.",
    }