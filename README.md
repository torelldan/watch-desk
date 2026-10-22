# Watch Desk

`watch-desk.html` is a single self-contained file (double-click to open). Data is embedded at build time, because browsers block `fetch()` of local files over `file://`.

## Files
- `template.html` – the page design with a `/*__DATA__*/` placeholder. Edit UI here, not in watch-desk.html.
- `data/deals.json` – array of deals: brand, model, ref, ask (incl. shipping), buy (target cap), sell (expected resale), source, url, found (YYYY-MM-DD), kind (buy/auction/pass), why, redFlags[]. Optional: compRef (ref to use for comps), sellRange (text). `image_url`: a real listing photo URL (reddit `preview`/gallery/i.imgur.com, eBay `og:image` / i.ebayimg.com), or "" if none could be fetched. Never invent one; cards show a placeholder when it's empty.
- `data/comps.json` – `{ "<ref>": [{date, price, source, title, url}] }`. Real sold rows only, every row has a source.
- `data/trends.json` – `{ "<ref>": [{date, price, source, url}] }` dated USD price points for the Analyze chart (sold comps or fetched public price history). A chart needs 2+ points, otherwise it shows "No trend data yet". Convert non-USD prices only using a figure the source itself shows, and record the original currency.
- Optional `bcv` (Bottom Cash Value, USD) per deal: the price you could dump the watch for fast. Never invent it. If absent, `build.py` derives it as the **lowest real sold comp in `comps.json` (deal's `compRef` or `ref`) dated within the last 6 months**, and sets `bcvNote` describing that. If no such comp exists, cards show `BCV —`. Buy ceiling = min(market-derived cap, BCV).
- `data/book.json` – array of purchases for the Book view: `{brand, model, ref, in, out (null until sold), fees, boughtDate, soldDate, notes}`. Days = boughtDate→soldDate (or today); ROI% = (out − in − fees) / in. Empty `[]` shows the empty state.
- `bcv_source` per deal: `'dealer quote' | '1916 quote' | 'auction comp'`, shown next to BCV. Set automatically by `build.py`.
- `data/bcv_quotes.json` – manual Bottom Cash Value quotes (start `[]`). **How to add a quote:** edit the file and append an object, e.g.
  `{"ref": "79230N", "amount": 2100, "source": "1916 quote", "date": "2026-10-22", "note": "phone quote, full set"}`
  (`source` = `"dealer quote"` or `"1916 quote"`; `date` = YYYY-MM-DD; `ref` matches the deal's `ref` or `compRef`). Then run `python3 build.py`. BCV priority: **most recent manual quote dated within 30 days** → explicit `bcv` in deals.json → auction-comp derivation (below). Use only real quotes you actually received.
- **NEEDS BCV**: a deal with `kind: "buy"` but no BCV renders an amber `NEEDS BCV` badge instead of BUY. The sidebar "Needs BCV (n)" view lists them.
- **ROI%** = (sell − buy − 10% fees on sell) / buy, on every card and in Analyze; amber when under 15%. Target ROI 15–20%, plus the $300 minimum profit. When the deal's `source` contains "Grailzee", `buy` in that formula is the all-in buy cost (target buy + buyer's premium). Book view shows ROI% per closed flip.
- Optional `exit`: `"marketplace"` (default) or `"grailzee"`. Analyze shows the Marketplace estimate (sell − 10%) and, when `comps.json` has sold rows whose `source` contains "Grailzee", a Grailzee estimate = median Grailzee sold comp − `GRAILZEE_SELLER_FEE_FLAT`. The preferred exit is starred.
- **Fee constants** (in `build.py`): `SELL_FEE = 0.10`; `GRAILZEE_SELLER_FEE_FLAT = 49`; `GRAILZEE_BUYER_PREMIUM = 0.05` with a $250 minimum and a $5,000 maximum. The Grailzee exit estimate is the median Grailzee sold comp minus $49. The buyer's premium is added to the all-in buy cost when the deal's `source` contains "Grailzee": premium = min(max(5% of the target buy, $250), $5,000). Classic seller fee is $49 per successful sale; Marketplace is $99; the published seller-fee range is $49–$149. Buyers pay a 5% premium (minimum $250, maximum $5,000). Checked Oct 22, 2026 on https://grailzee.com/apps/auctioneer/sell and https://grailzee.com/pages/grailzee-for-sellers. The exit estimate uses the Classic $49 fee.
- Optional `weak_listing` (bool) + `weak_listing_reason` (text): shows a `RELIST PLAY` chip (bad photos / thin description → buy, reshoot, relist).
- **Bankroll tracker** (Book view): starts at $1,500 and adds each closed flip's (out − in − fees) from `book.json` in soldDate order, plotted against a 20%-per-flip reinvested path over 12 flips, labeled "guide benchmark, not a forecast".
- Source filter keys (mapped from each deal's `source` text): eBay, Chrono24, Grailzee, Forums (WUS/RolexForums), Facebook/Marketplace, WatchPatrol, Reddit.
- `build.py` – injects the JSON (deals, comps, trends, book) and stamps "Data updated" in America/Chicago time (zoneinfo), labeled CT. It the JSON and writes `watch-desk.html`.
5. Budget filters: under $1,000, $1,500, $5,000, or All. The routine covers watches up to $5,000.

## Daily update (after the ~8 AM CT deal check)
1. Append each new find to `data/deals.json` with today's `found` date (only real listings, no invented numbers).
   Capture `image_url` for each deal: reddit = `<post url>.json` with a User-Agent header, then `preview.images[0].source.url` (HTML-unescape it) or the gallery/imgur link. eBay = `og:image` from the listing. If it's blocked, leave it "" and note that.
2. Add any new real sold rows to `data/comps.json` under the watch's *own* ref (don't file a 165.008 under 166.020), and add the same date/price to `data/trends.json`.
3. Run `python3 build.py`. It drops deals older than 14 days from the output, sorts newest first, and stamps "Data updated".
4. Send Daniel the fresh `watch-desk.html`.
