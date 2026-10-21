# Watch Desk

`watch-desk.html` is a single self-contained file (double-click to open). Data is embedded at build time, because browsers block `fetch()` of local files over `file://`.

## Files
- `template.html` – the page design with a `/*__DATA__*/` placeholder. Edit UI here, not in watch-desk.html.
- `data/deals.json` – array of deals: brand, model, ref, ask (incl. shipping), buy (target cap), sell (expected resale), source, url, found (YYYY-MM-DD), kind (buy/auction/pass), why, redFlags[]. Optional: compRef (ref to use for comps), sellRange (text).
- `data/comps.json` – `{ "<ref>": [{date, price, source, title, url}] }`. Real sold rows only, every row has a source.
- `build.py` – injects the JSON and writes `watch-desk.html`.

## Daily update (after the ~8 AM CT deal check)
1. Append each new find to `data/deals.json` with today's `found` date (only real listings, no invented numbers).
2. Add any new real sold rows to `data/comps.json` under the model ref.
3. Run `python3 build.py`. It drops deals older than 14 days from the output, sorts newest first, and stamps "Data updated".
4. Send Daniel the fresh `watch-desk.html`.

## GitHub Pages
Phone URL: https://torelldan.github.io/watch-desk/

`build.py` writes `watch-desk.html` and `index.html`. Pages serves `index.html` from the `main` branch root. `.github/workflows/pages.yml` deploys that root on each push to `main`. The site still has to be turned on under Settings → Pages (source: GitHub Actions). On GitHub Free that only works if this repository is public.
