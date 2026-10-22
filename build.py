#!/usr/bin/env python3
"""Build watch-desk.html from template.html + data/*.json (data is embedded; no fetch needed)."""
import json, datetime, pathlib
from zoneinfo import ZoneInfo
CT = ZoneInfo("America/Chicago")
D = pathlib.Path(__file__).resolve().parent
deals = json.loads((D / "data/deals.json").read_text())
comps = json.loads((D / "data/comps.json").read_text())
tp = D / "data/trends.json"
trends = json.loads(tp.read_text()) if tp.exists() else {}
bp = D / "data/book.json"
book = json.loads(bp.read_text()) if bp.exists() else []
now = datetime.datetime.now(CT)
qp = D / "data/bcv_quotes.json"
quotes = json.loads(qp.read_text()) if qp.exists() else []
# Fee constants (see README). Grailzee figures checked Oct 22, 2026.
SELL_FEE = 0.10
GRAILZEE_SELLER_FEE_FLAT = 49
GRAILZEE_BUYER_PREMIUM = 0.05
GRAILZEE_BUYER_PREMIUM_MIN = 250
GRAILZEE_BUYER_PREMIUM_MAX = 5000
q30 = (now.date() - datetime.timedelta(days=30)).isoformat()
# Bottom Cash Value: keep an explicit bcv; otherwise derive = lowest real sold comp (comps.json) in last 6 months
six = (now.date() - datetime.timedelta(days=183)).isoformat()
cutoff = (now.date() - datetime.timedelta(days=14)).isoformat()
deals = [d for d in deals if d.get("found", "") >= cutoff]  # drop stale > 14 days
deals.sort(key=lambda d: d.get("found", ""), reverse=True)

def grailzee_buyer_premium(amount):
    return min(GRAILZEE_BUYER_PREMIUM_MAX, max(GRAILZEE_BUYER_PREMIUM_MIN, GRAILZEE_BUYER_PREMIUM * amount))

for d in deals:
    refs = {d.get("ref"), d.get("compRef")} - {None}
    mq = sorted([q for q in quotes if q.get("ref") in refs and q.get("amount") and q.get("date", "") >= q30], key=lambda q: q["date"], reverse=True)
    if mq:
        q = mq[0]; src = str(q.get("source", "dealer quote")).lower()
        d["bcv"] = q["amount"]; d["bcv_source"] = "1916 quote" if "1916" in src else "dealer quote"
        d["bcvNote"] = f"Manual quote {q['date']}" + (f" · {q['note']}" if q.get("note") else "")
    elif d.get("bcv") is not None:
        d.setdefault("bcv_source", "dealer quote")
    if d.get("bcv") is None:
        recent = [c["price"] for c in comps.get(d.get("compRef") or d.get("ref"), []) if c.get("date", "") >= six and c.get("price")]
        if recent:
            d["bcv"] = min(recent); d["bcv_source"] = "auction comp"; d["bcvNote"] = f"Derived: lowest of {len(recent)} real sold comp(s), last 6 months"
    buy = d.get("buy")
    if buy is not None and "grailzee" in str(d.get("source") or "").lower():
        premium = grailzee_buyer_premium(float(buy))
        d["buyerPremium"] = round(premium, 2)
        d["buyAllIn"] = round(float(buy) + premium, 2)
    elif buy is not None:
        d["buyAllIn"] = buy
updated = now.strftime("%b %-d, %Y %-I:%M %p CT")
js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
fees = {
    "sell": SELL_FEE,
    "grailzeeFlat": GRAILZEE_SELLER_FEE_FLAT,
    "grailzeeBuyerPremium": GRAILZEE_BUYER_PREMIUM,
    "grailzeeBuyerPremiumMin": GRAILZEE_BUYER_PREMIUM_MIN,
    "grailzeeBuyerPremiumMax": GRAILZEE_BUYER_PREMIUM_MAX,
}
blob = f"const deals = {js(deals)};\nconst comps = {js(comps)};\nconst trends = {js(trends)};\nconst book = {js(book)};\nconst FEES = {js(fees)};\nconst DATA_UPDATED = {js(updated)};"
tpl = (D / "template.html").read_text()
assert "/*__DATA__*/" in tpl, "template placeholder missing"
(D / "watch-desk.html").write_text(tpl.replace("/*__DATA__*/", blob))
print(f"wrote watch-desk.html: {len(deals)} deals, {sum(map(len, comps.values()))} comps, {sum(len(v)>=2 for v in trends.values())} trend series, {sum(1 for d in deals if d.get('image_url'))} images, {len(book)} book rows, {sum(1 for d in deals if d.get('bcv') is not None)} with BCV ({len(quotes)} manual quotes), updated {updated}")
