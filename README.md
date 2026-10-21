# Watch Desk

`watch-desk.html` is a single self-contained file (double-click to open). Data is embedded at build time, because browsers block `fetch()` of local files over `file://`.

## Files
- `template.html` – the page design with a `/*__DATA__*/` placeholder. Edit UI here, not in watch-desk.html.
- `data/deals.json` – array of deals: brand, model, ref, ask (incl. shipping), buy (target cap), sell (expected resale), source, url, found (YYYY-MM-DD), kind (buy/auction/pass), why, redFlags[]. Optional: compRef (ref to use for comps), sellRange (text). `image_url`: a real listing photo URL (reddit `preview`/gallery/i.imgur.com, eBay `og:image` / i.ebayimg.com), or "" if none could be fetched. Never invent one; cards show a placeholder when it's empty.
- `data/comps.json` – `{ "<ref>": [{date, price, source, title, url}] }`. Real sold rows only, every row has a source.
- `data/trends.json` – `{ "<ref>": [{date, price, source, url}] }` dated USD price points for the Analyze chart (sold comps or fetched public price history). A chart needs 2+ points, otherwise it shows "No trend data yet". Convert non-USD prices only using a figure the source itself shows, and record the original currency.
- `build.py` – injects the JSON and writes `watch-desk.html`.
5. Budget filters: under $1,000, $1,500, $5,000, or All. The routine covers watches up to $5,000.

## Daily update (after the ~8 AM CT deal check)
1. Append each new find to `data/deals.json` with today's `found` date (only real listings, no invented numbers).
   Capture `image_url` for each deal: reddit = `<post url>.json` with a User-Agent header, then `preview.images[0].source.url` (HTML-unescape it) or the gallery/imgur link. eBay = `og:image` from the listing. If it's blocked, leave it "" and note that.
2. Add any new real sold rows to `data/comps.json` under the watch's *own* ref (don't file a 165.008 under 166.020), and add the same date/price to `data/trends.json`.
3. Run `python3 build.py`. It drops deals older than 14 days from the output, sorts newest first, and stamps "Data updated".
4. Send Daniel the fresh `watch-desk.html`.
