#!/usr/bin/env python3
"""Build watch-desk.html from template.html + data/*.json (data is embedded; no fetch needed)."""
import json, datetime, pathlib
D = pathlib.Path(__file__).resolve().parent
deals = json.loads((D / "data/deals.json").read_text())
comps = json.loads((D / "data/comps.json").read_text())
tp = D / "data/trends.json"
trends = json.loads(tp.read_text()) if tp.exists() else {}
cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
deals = [d for d in deals if d.get("found", "") >= cutoff]  # drop stale > 14 days
deals.sort(key=lambda d: d.get("found", ""), reverse=True)
updated = datetime.datetime.now().strftime("%b %-d, %Y %-I:%M %p CT")
js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
blob = f"const deals = {js(deals)};\nconst comps = {js(comps)};\nconst trends = {js(trends)};\nconst DATA_UPDATED = {js(updated)};"
tpl = (D / "template.html").read_text()
assert "/*__DATA__*/" in tpl, "template placeholder missing"
(D / "watch-desk.html").write_text(tpl.replace("/*__DATA__*/", blob))
print(f"wrote watch-desk.html: {len(deals)} deals, {sum(map(len, comps.values()))} comps, {sum(len(v)>=2 for v in trends.values())} trend series, {sum(1 for d in deals if d.get('image_url'))} images, updated {updated}")
