#!/usr/bin/env python3
"""Build watch-desk.html from template.html + data/*.json (data is embedded; no fetch needed)."""
import json, datetime, pathlib
D = pathlib.Path(__file__).resolve().parent
deals = json.loads((D / "data/deals.json").read_text())
comps = json.loads((D / "data/comps.json").read_text())
cutoff = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
deals = [d for d in deals if d.get("found", "") >= cutoff]  # drop stale > 14 days
deals.sort(key=lambda d: d.get("found", ""), reverse=True)
updated = datetime.datetime.now().strftime("%b %-d, %Y %-I:%M %p CT")
js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
blob = f"const deals = {js(deals)};\nconst comps = {js(comps)};\nconst DATA_UPDATED = {js(updated)};"
tpl = (D / "template.html").read_text()
assert "/*__DATA__*/" in tpl, "template placeholder missing"
html = tpl.replace("/*__DATA__*/", blob)
(D / "watch-desk.html").write_text(html)
# GitHub Pages serves index.html from the repo root.
(D / "index.html").write_text(html)
print(f"wrote watch-desk.html and index.html: {len(deals)} deals, {sum(map(len, comps.values()))} comps, updated {updated}")
