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
# Bottom Cash Value: keep an explicit bcv; otherwise derive = lowest real sold comp (comps.json) in last 6 months
six = (now.date() - datetime.timedelta(days=183)).isoformat()
cutoff = (now.date() - datetime.timedelta(days=14)).isoformat()
deals = [d for d in deals if d.get("found", "") >= cutoff]  # drop stale > 14 days
deals.sort(key=lambda d: d.get("found", ""), reverse=True)
for d in deals:
    if d.get("bcv") is None:
        recent = [c["price"] for c in comps.get(d.get("compRef") or d.get("ref"), []) if c.get("date", "") >= six and c.get("price")]
        if recent:
            d["bcv"] = min(recent); d["bcvNote"] = f"Derived: lowest of {len(recent)} real sold comp(s), last 6 months"
updated = now.strftime("%b %-d, %Y %-I:%M %p CT")
js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
blob = f"const deals = {js(deals)};\nconst comps = {js(comps)};\nconst trends = {js(trends)};\nconst book = {js(book)};\nconst DATA_UPDATED = {js(updated)};"
tpl = (D / "template.html").read_text()
assert "/*__DATA__*/" in tpl, "template placeholder missing"
(D / "watch-desk.html").write_text(tpl.replace("/*__DATA__*/", blob))
print(f"wrote watch-desk.html: {len(deals)} deals, {sum(map(len, comps.values()))} comps, {sum(len(v)>=2 for v in trends.values())} trend series, {sum(1 for d in deals if d.get('image_url'))} images, {len(book)} book rows, {sum(1 for d in deals if d.get('bcv') is not None)} with BCV, updated {updated}")
