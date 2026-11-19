#!/usr/bin/env python3
"""Pull active eBay listings for the watch list. Read-only: no bidding, buying, or messaging.

Uses the official eBay Browse API (client-credentials). Chrono24 search pages are
optional and fail soft. Listings and prices are written only when a response
actually contains them. Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET logs a notice
and exits 0 without writing files.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WATCHLIST_PATH = Path(__file__).resolve().parent / "watchlist.json"
LISTINGS_PATH = DATA / "mined_listings.json"
META_PATH = DATA / "mined_meta.json"
HISTORY_PATH = DATA / "price_history.json"

EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_US"
CATEGORY_WRISTWATCH = "31387"
MAX_ITEMS_PER_QUERY = 100
PAGE_LIMIT = 50

# A listing is a part when the title is selling the part, not when a complete
# watch mentions a dial color, a strap, a box, or extra links.
NOT_WORKING_RE = re.compile(
    r"\b(for parts|for repair|not working|not running|as is|spares|repair)\b"
)
PART_ONLY_RE = re.compile(
    r"\b(bezel insert|insert only|hands only|dial only|movement only|box only|empty box|"
    r"papers only|straps? only|bracelets? only|clasp only|spring bars?|links? only|"
    r"bands? only|buckles? only|cases? only|empty cases?|crystals? only|crowns? only)\b"
)
PART_FOR_RE = re.compile(
    r"\b(?:bracelets?|straps?|bands?|clasps?|buckles?|links?|dials?|crowns?|bezels?|"
    r"inserts?|movements?|crystals?|hands|case ?backs?)\b(?:\s+\w+){0,8}\s+for\b"
)
GENUINE_PART_RE = re.compile(
    r"\bgenuine\b(?:\s+\w+){0,6}\s+"
    r"(dial|dials|bracelet|bracelets|strap|straps|band|bands|link|links|clasp|clasps|"
    r"crown|bezel|insert)s?\b"
)
COLOR_WORD = (
    r"black|blue|white|green|silver|gold|grey|gray|champagne|ivory|roman|sunburst|"
    r"gilt|brown|orange|navy|red|cream|salmon|panda|tropical|matte|dark|light|hulk|pepsi|lume"
)
WATCH_WORD_RE = re.compile(
    r"\b(watch|wristwatch|watches|timepiece|automatic|quartz|manual|self winding|"
    r"hand winding|winding|chronometer|diver|divers|mens|ladies|womens|womans)\b"
)
CASE_MM_RE = re.compile(r"\b\d{2}\s*mm\b")
# Used only by the price backstop. A cheap title that says these is a watch on
# sale, not a part the wording missed.
COMPLETE_WATCH_RE = re.compile(
    r"\b(watch|wristwatch|watches|automatic|self winding|chronometer|diver|divers)\b"
)
EXCLUDE_RE = re.compile(r"\b(homage|replica|aftermarket|modded|fake|franken)\b", re.I)
PRICE_FLOOR_RATIO = 0.33
BUY_CAP_FLOOR_RATIO = 0.35
MIN_LISTINGS_FOR_PRICE_FLOOR = 3
FILTER_REASONS = ("part", "not_working", "excluded", "below_cap", "below_median")
# An auction that merely ends on a part word, with none of these, is the part.
AUCTION_KEEP_CONTEXT_RE = re.compile(r"\b(watch|wristwatch|watches|automatic)\b|\d+\s*mm\b")
AUCTION_END_PART_RE = re.compile(
    r"\b(bracelets?|straps?|belts?|bands?|links?|clasps?)\b(?:\s+#?\s*\d+[a-z0-9]*)*$"
)
CHRONO_BLOCK_RE = re.compile(
    r"cf-browser-verification|cf-challenge|just a moment|captcha|access denied",
    re.I,
)


class EbayError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def stamp(now=None):
    now = now or datetime.now(CT)
    return now.strftime("%b %-d, %Y %-I:%M %p CT"), now.isoformat(timespec="seconds")


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def money_value(obj):
    """Return (amount, currency) from an eBay amount object, or (None, None)."""
    if not isinstance(obj, dict):
        return None, None
    raw = obj.get("value")
    cur = obj.get("currency")
    if raw is None or raw == "":
        return None, cur
    try:
        return round(float(raw), 2), cur
    except (TypeError, ValueError):
        return None, cur


def token_in(hay, token):
    t = token.casefold()
    if not t:
        return False
    if len(t) >= 5 or "." in t or re.search(r"[a-z]", t):
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay) is not None
    return re.search(r"(?<![a-z0-9])" + re.escape(t), hay) is not None


def title_matches(title, groups):
    hay = (title or "").casefold()
    for group in groups or []:
        if group and all(token_in(hay, str(tok)) for tok in group):
            return True
    return False


def normalize_title(title):
    text = (title or "").casefold()
    text = text.replace("&", " and ")
    for ch in ("'", "’", "‘", "`"):
        text = text.replace(ch, "")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def empty_filter_counts():
    return {key: 0 for key in FILTER_REASONS}


def note_reject(bucket, reason):
    if bucket is not None and reason:
        bucket[reason] = bucket.get(reason, 0) + 1


def _dial_is_the_item(text):
    if not re.search(r"\bdials?\b", text):
        return False
    if re.search(r"\bdial only\b", text):
        return True
    # "BLACK DIAL ... series" is a dial for sale. A watch that merely says
    # "black dial" does not.
    if re.search(r"\bseries\b", text) and not WATCH_WORD_RE.search(text):
        return True
    ends = re.search(r"\bdials?(?:\s+\d+){0,4}$", text)
    color_end = re.search(rf"\b(?:{COLOR_WORD})\s+dials?(?:\s+\d+){{0,4}}$", text)
    if ends and not color_end:
        return True
    if re.search(r"\boriginal dials?\b", text) and not re.search(
        r"\b(watch|wristwatch|watches|automatic|mens|ladies)\b", text
    ):
        return True
    context = WATCH_WORD_RE.search(text) or CASE_MM_RE.search(text)
    if not context and not re.search(rf"\b(?:{COLOR_WORD})\s+dials?\b", text):
        return True
    return False


def _box_is_the_item(text):
    if re.search(r"\bpresentation box\b", text):
        return True
    if not re.search(r"\bbox\b", text):
        return False
    if re.search(r"\b(no box|with box|w box|box and papers|box or papers)\b", text):
        return False
    if WATCH_WORD_RE.search(text) or CASE_MM_RE.search(text):
        return False
    return True


def _strap_is_the_item(text):
    if re.search(r"\bbracelet links?\b", text):
        return True
    if not re.search(r"\b(bracelets?|straps?|bands?|clasps?|buckles?)\b", text):
        return False
    # "3 bracelets" and "on rubber strap" describe the watch. "custom band" does too.
    if re.search(r"\b\d+\s+bracelets\b", text):
        return False
    if re.search(r"\bcustom band\b", text):
        return False
    if re.search(r"\bon\b(?:\s+\w+){0,3}\s+(?:strap|band|bracelet)\b", text):
        return False
    if WATCH_WORD_RE.search(text):
        return False
    return bool(re.search(r"\b(bracelet|strap|band|clasp|buckle)\b", text))


def _is_part_title(text):
    if PART_ONLY_RE.search(text) or PART_FOR_RE.search(text) or GENUINE_PART_RE.search(text):
        return True
    # Japanese sellers use "belt" for a strap sold on its own, often with the
    # watch name after it. "with belt" or "on belt" is still the watch.
    if re.search(r"\bbelts?\b", text) and not re.search(r"\b(with|on)\s+belts?\b", text):
        return True
    if re.search(r"\bspare\b", text) or re.search(r"\blot of\b", text):
        return True
    if re.search(r"\b(female|male) stem\b", text):
        return True
    if re.search(r"\bcrown\b", text) and re.search(r"\bstem\b", text):
        return True
    if re.search(r"\bmovements?\b", text):
        return True
    if re.search(r"\bcase ?backs?\b", text) or re.search(r"\bwatch cases?\b", text):
        return True
    if re.search(r"\bfor cal(?:iber)?\b", text):
        return True
    if re.search(r"\b(protection film|protective film|chapter ring)\b", text):
        return True
    if re.search(r"\bplexi\b", text) and not re.search(r"\b(watch|wristwatch|automatic|quartz)\b", text):
        return True
    if _dial_is_the_item(text) or _box_is_the_item(text) or _strap_is_the_item(text):
        return True
    return False


def title_reject_reason(title):
    """Why this title is not a complete working watch, or None to keep it.

    `part` is a dial, bracelet, box, or other piece sold alone.
    `not_working` is for parts, for repair, not working, or as-is.
    `excluded` is a replica, homage, or similar, which was already skipped.
    """
    raw = title or ""
    if EXCLUDE_RE.search(raw):
        return "excluded"
    text = normalize_title(raw)
    if not text:
        return None
    # "(READ)" and "read description" are the seller's warning that it is not
    # a working watch. A bare "read" inside another word is left alone.
    if re.search(r"\(\s*read\s*\)", raw, re.I) or re.search(r"\bread description\b", text):
        return "not_working"
    if NOT_WORKING_RE.search(text):
        return "not_working"
    if _is_part_title(text):
        return "part"
    return None


def looks_like_parts(title):
    return title_reject_reason(title) is not None


def is_auction(row):
    if str(row.get("format") or "").casefold() == "auction":
        return True
    # A $1 eLive auction is a real watch even if the format field is missing.
    if row.get("end_time") and "elive" in normalize_title(row.get("title")):
        return True
    return False


def reads_as_complete_watch(title):
    return bool(COMPLETE_WATCH_RE.search(normalize_title(title)))


def auction_ends_as_part(title):
    """True when an auction title ends on bracelet, strap, links, or belt.

    A low bid stays when the title says watch, automatic, or a case size in mm.
    "Self-winding" and a bare "41" do not count: those still show up on straps.
    """
    text = normalize_title(title)
    if not text or AUCTION_KEEP_CONTEXT_RE.search(text):
        return False
    return bool(AUCTION_END_PART_RE.search(text))


def row_reject_reason(row):
    reason = title_reject_reason(row.get("title") if isinstance(row, dict) else row)
    if reason:
        return reason
    if isinstance(row, dict) and is_auction(row) and auction_ends_as_part(row.get("title")):
        return "part"
    return None


def median(values):
    vals = sorted(values)
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2


def drop_below_buy_cap(rows, ratio=BUY_CAP_FLOOR_RATIO):
    """Drop fixed-price listings under about 35% of that model's buy cap.

    This catches a $288 bracelet on a $2,250 watch even when the model has
    too few listings for a median. Auctions are left to the title rules,
    because a $1 bid on a real watch is still a real watch.
    """
    drop = set()
    for index, row in enumerate(rows):
        if is_auction(row):
            continue
        cap = row.get("buy_cap")
        total = row.get("total")
        if not isinstance(cap, (int, float)) or not isinstance(total, (int, float)) or cap <= 0:
            continue
        if total < cap * ratio:
            drop.add(index)
    kept = [row for index, row in enumerate(rows) if index not in drop]
    return kept, len(drop)


def drop_price_outliers(rows, ratio=PRICE_FLOOR_RATIO):
    """Drop fixed-price listings priced like a part next to the model's other listings.

    Auctions stay, including a $1 eLive bid. A buy-it-now title that reads as a
    whole watch stays too: that is a cheap watch, not a missed dial or bracelet.
    The floor is one third of the model's median, and only when the model has
    at least three listings left to compare.
    """
    grouped = {}
    for index, row in enumerate(rows):
        grouped.setdefault(row.get("model_id"), []).append(index)
    drop = set()
    for indexes in grouped.values():
        priced = [i for i in indexes if isinstance(rows[i].get("total"), (int, float))]
        if len(priced) < MIN_LISTINGS_FOR_PRICE_FLOOR:
            continue
        med = median(rows[i]["total"] for i in priced)
        if med <= 0:
            continue
        floor = med * ratio
        for i in priced:
            row = rows[i]
            if is_auction(row) or reads_as_complete_watch(row.get("title")):
                continue
            if row["total"] < floor:
                drop.add(i)
    kept = [row for i, row in enumerate(rows) if i not in drop]
    return kept, len(drop)


def effective_cap(model, max_price):
    cap = model.get("buy_cap")
    if not isinstance(cap, (int, float)) or cap <= 0:
        return None
    cap = round(float(cap), 2)
    if max_price is not None:
        cap = min(cap, max_price)
    return cap


def shipping_of(item):
    """Return (amount, known). Unknown shipping stays None. Never treat unknown as 0."""
    options = item.get("shippingOptions") if isinstance(item, dict) else None
    if not isinstance(options, list):
        return None, False
    fallback = None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        amt, cur = money_value(opt.get("shippingCost"))
        if amt is None or (cur not in (None, "USD")):
            continue
        kind = str(opt.get("shippingCostType") or "").upper()
        if kind == "FIXED" or kind == "":
            return amt, True
        if fallback is None:
            fallback = amt
    if fallback is not None:
        return fallback, True
    return None, False


def listing_price(item):
    """Pick the amount a buyer would pay now, plus BIN vs auction.

    FIXED_PRICE uses the BIN price. AUCTION uses the current bid when eBay sends
    one, otherwise the price field. A listing with both uses the BIN price,
    because that is what Buy It Now charges.
    """
    options = {str(x).upper() for x in (item.get("buyingOptions") or [])}
    bin_amt, bin_cur = money_value(item.get("price"))
    bid_amt, bid_cur = money_value(item.get("currentBidPrice"))
    has_bin = "FIXED_PRICE" in options or "BEST_OFFER" in options
    has_auc = "AUCTION" in options
    if has_bin and not has_auc:
        return "BIN", bin_amt, bin_cur
    if has_auc and not has_bin:
        if bid_amt is not None:
            return "auction", bid_amt, bid_cur
        return "auction", bin_amt, bin_cur
    if has_bin:
        return "BIN", bin_amt, bin_cur
    if bid_amt is not None:
        return "auction", bid_amt, bid_cur
    return "BIN", bin_amt, bin_cur


def location_of(item):
    loc = item.get("itemLocation") if isinstance(item, dict) else None
    if not isinstance(loc, dict):
        return None
    bits = [loc.get("city"), loc.get("stateOrProvince"), loc.get("country")]
    bits = [str(b).strip() for b in bits if b]
    return ", ".join(bits) if bits else None


def feedback_of(item):
    seller = item.get("seller") if isinstance(item, dict) else None
    if not isinstance(seller, dict):
        return None
    pct = seller.get("feedbackPercentage")
    score = seller.get("feedbackScore")
    parts = []
    if pct is not None and pct != "":
        try:
            parts.append(f"{float(pct):g}%")
        except (TypeError, ValueError):
            parts.append(str(pct))
    if score is not None and score != "":
        try:
            parts.append(f"{int(score):,}")
        except (TypeError, ValueError):
            parts.append(str(score))
    return " · ".join(parts) if parts else None


def image_of(item):
    image = item.get("image") if isinstance(item, dict) else None
    if isinstance(image, dict):
        url = image.get("imageUrl") or ""
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""


def listing_from_ebay(model, item, cap, rejected=None):
    """Build one listing dict, or None when the item is not a real under-cap watch."""
    if not isinstance(item, dict):
        return None
    title = item.get("title") or ""
    if not title:
        return None
    groups = model.get("title_any") or [[model.get("ref") or ""]]
    if not title_matches(title, groups):
        return None
    url = item.get("itemWebUrl") or ""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    fmt, price, cur = listing_price(item)
    if price is None or cur != "USD":
        return None
    ship, known = shipping_of(item)
    total = round(price + ship, 2) if known else price
    if total > cap:
        return None
    reason = title_reject_reason(title)
    if reason:
        note_reject(rejected, reason)
        return None
    end = item.get("itemEndDate")
    if end is not None and not isinstance(end, str):
        end = None
    return {
        "model_id": model["id"],
        "brand": model.get("brand") or "",
        "model": model.get("model") or "",
        "ref": model.get("ref") or "",
        "source": "eBay",
        "format": fmt,
        "title": title,
        "price": price,
        "currency": "USD",
        "shipping": ship if known else None,
        "shipping_known": known,
        "total": total,
        "url": url,
        "image_url": image_of(item),
        "end_time": end,
        "seller_feedback": feedback_of(item),
        "location": location_of(item),
        "buy_cap": cap,
        "item_id": item.get("itemId") or "",
    }


def walk_jsonld(node, out):
    if isinstance(node, list):
        for item in node:
            walk_jsonld(item, out)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("@graph"), list):
        walk_jsonld(node["@graph"], out)
    if isinstance(node.get("itemListElement"), list):
        walk_jsonld(node["itemListElement"], out)
    item = node.get("item")
    if isinstance(item, dict):
        walk_jsonld(item, out)
    offers = node.get("offers")
    name = node.get("name") or node.get("title")
    url = node.get("url")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict) and name and isinstance(url, str):
        price = offers.get("price")
        if price is None and isinstance(offers.get("priceSpecification"), dict):
            price = offers["priceSpecification"].get("price")
        currency = offers.get("priceCurrency")
        image = node.get("image")
        if isinstance(image, list):
            image = image[0] if image else ""
        if isinstance(image, dict):
            image = image.get("url") or image.get("contentUrl") or ""
        out.append({
            "title": name,
            "url": url,
            "price": price,
            "currency": currency,
            "image": image if isinstance(image, str) else "",
        })


def listing_from_chrono(model, raw, cap, rejected=None):
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "")
    url = str(raw.get("url") or "")
    if url.startswith("/"):
        url = "https://www.chrono24.com" + url
    if "chrono24.com" not in url or not url.startswith("http"):
        return None
    if not title:
        return None
    groups = model.get("title_any") or [[model.get("ref") or ""]]
    if not title_matches(title, groups):
        return None
    currency = str(raw.get("currency") or "").upper()
    if currency not in ("USD", "US DOLLAR"):
        return None
    try:
        price = round(float(str(raw.get("price")).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None
    if price > cap:
        return None
    reason = title_reject_reason(title)
    if reason:
        note_reject(rejected, reason)
        return None
    image = raw.get("image") or ""
    if not isinstance(image, str) or not image.startswith("http"):
        image = ""
    return {
        "model_id": model["id"],
        "brand": model.get("brand") or "",
        "model": model.get("model") or "",
        "ref": model.get("ref") or "",
        "source": "Chrono24",
        "format": "BIN",
        "title": title,
        "price": price,
        "currency": "USD",
        "shipping": None,
        "shipping_known": False,
        "total": price,
        "url": url,
        "image_url": image,
        "end_time": None,
        "seller_feedback": None,
        "location": None,
        "buy_cap": cap,
        "item_id": "",
    }


def parse_chrono24(html, model, cap, rejected=None):
    """Parse a Chrono24 search page. Returns (listings, error).

    A page that contains JSON-LD but no under-cap USD matches is a real empty
    result. A short or challenge page is blocked. A long page with no JSON-LD
    is unparseable, which is not the same as zero listings.
    """
    if not html:
        return [], "empty response"
    if CHRONO_BLOCK_RE.search(html[:8000] or ""):
        return [], "blocked"
    found = []
    saw_ld = False
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    ):
        saw_ld = True
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        raws = []
        walk_jsonld(payload, raws)
        for raw in raws:
            row = listing_from_chrono(model, raw, cap, rejected)
            if row:
                found.append(row)
    if found:
        return dedupe_rows(found), None
    if saw_ld:
        return [], None
    if len(html) < 5000:
        return [], "blocked"
    return [], "unparseable"


def dedupe_rows(rows):
    seen = set()
    out = []
    for row in rows:
        key = (row.get("source"), row.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def history_point(rows):
    """Daily low from real rows only. Prefer all-in totals when shipping is known."""
    if not rows:
        return None
    known = [r for r in rows if r.get("shipping_known") and isinstance(r.get("total"), (int, float))]
    pool = known or [r for r in rows if isinstance(r.get("total"), (int, float))]
    if not pool:
        return None
    winner = min(pool, key=lambda r: (r["total"], r.get("url") or ""))
    return {
        "low": winner["total"],
        "currency": "USD",
        "n": len(rows),
        "basis": "price+shipping" if known else "item price only; shipping was not in the response",
        "source": winner.get("source") or "",
        "url": winner.get("url") or "",
    }


def append_history(history, model, point, day):
    key = model["id"]
    entry = history.get(key)
    if not isinstance(entry, dict):
        if not point:
            return
        entry = {}
    entry["brand"] = model.get("brand") or ""
    entry["model"] = model.get("model") or ""
    entry["ref"] = model.get("ref") or ""
    points = [p for p in entry.get("points") or [] if isinstance(p, dict) and p.get("date") != day]
    if point:
        points.append({"date": day, **point})
        points.sort(key=lambda p: p.get("date") or "")
    entry["points"] = points
    history[key] = entry


def select_models(models, filt):
    if not filt:
        return list(models)
    tokens = [t.strip().casefold() for t in filt.split(",") if t.strip()]
    if not tokens:
        return list(models)
    chosen = []
    for model in models:
        blob = " ".join([
            str(model.get("id") or ""),
            str(model.get("ref") or ""),
            str(model.get("brand") or ""),
            str(model.get("model") or ""),
        ]).casefold()
        ident = str(model.get("id") or "").casefold()
        ref = str(model.get("ref") or "").casefold()
        if any(tok == ident or tok == ref or (len(tok) >= 3 and tok in blob) for tok in tokens):
            chosen.append(model)
    return chosen


def load_watchlist():
    data = json.loads(WATCHLIST_PATH.read_text())
    models = data.get("models")
    if not isinstance(models, list) or not models:
        raise SystemExit("scripts/watchlist.json has no models")
    seen = set()
    for model in models:
        mid = model.get("id")
        if not mid or mid in seen:
            raise SystemExit(f"watchlist model id missing or duplicated: {mid!r}")
        seen.add(mid)
        for key in ("brand", "model", "ref", "query"):
            if not model.get(key):
                raise SystemExit(f"watchlist model {mid} is missing {key}")
        cap = model.get("buy_cap")
        if not isinstance(cap, (int, float)) or cap <= 0:
            raise SystemExit(f"watchlist model {mid} has no positive buy_cap")
    return models


def http_json(url, headers, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}, resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:400]
        raise EbayError(exc.code, body) from exc


def fetch_token(client_id, client_secret):
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": EBAY_SCOPE,
    }).encode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        body, _status = http_json(EBAY_TOKEN_URL, headers, data=payload, method="POST")
    except EbayError as exc:
        print(
            f"ERROR: eBay rejected the client-credentials token ({exc}). "
            "Check EBAY_CLIENT_ID and EBAY_CLIENT_SECRET. Use the app's Production keys.",
            flush=True,
        )
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"ERROR: could not reach the eBay token endpoint: {exc.reason}", flush=True)
        raise SystemExit(1) from exc
    token = body.get("access_token") if isinstance(body, dict) else None
    if not token:
        print("ERROR: eBay token response had no access_token. No listings were written.", flush=True)
        raise SystemExit(1)
    return token


def search_ebay(token, model, cap, rejected=None):
    """Return (rows, error). rows is None only when the call failed."""
    queries = [
        ("BIN", "buyingOptions:{FIXED_PRICE|BEST_OFFER}"),
        ("auction", "buyingOptions:{AUCTION}"),
    ]
    rows = []
    errors = []
    for _label, buying in queries:
        filt = f"{buying},price:[..{cap:.2f}],priceCurrency:USD"
        try:
            items = ebay_pages(token, model["query"], filt)
        except EbayError as exc:
            if exc.status == 400:
                try:
                    items = ebay_pages(token, model["query"], f"price:[..{cap:.2f}],priceCurrency:USD")
                except (EbayError, urllib.error.URLError) as retry_exc:
                    errors.append(str(retry_exc))
                    continue
            else:
                errors.append(str(exc))
                continue
        except urllib.error.URLError as exc:
            errors.append(str(getattr(exc, "reason", exc)))
            continue
        for item in items:
            row = listing_from_ebay(model, item, cap, rejected)
            if row:
                rows.append(row)
    if errors and not rows:
        return None, "; ".join(errors)
    if errors:
        return dedupe_rows(rows), "; ".join(errors)
    return dedupe_rows(rows), None


def ebay_pages(token, query, filt):
    try:
        return ebay_pages_once(token, query, filt, extended=True)
    except EbayError as exc:
        if exc.status != 400:
            raise
        return ebay_pages_once(token, query, filt, extended=False)


def ebay_pages_once(token, query, filt, extended):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
        "Accept": "application/json",
        "User-Agent": "WatchDesk/1.0",
    }
    items = []
    offset = 0
    while offset < MAX_ITEMS_PER_QUERY:
        params = {
            "q": query,
            "category_ids": CATEGORY_WRISTWATCH,
            "filter": filt,
            "limit": str(PAGE_LIMIT),
            "offset": str(offset),
            "sort": "price",
        }
        if extended:
            params["fieldgroups"] = "EXTENDED"
        url = EBAY_SEARCH_URL + "?" + urllib.parse.urlencode(params)
        body, _status = http_json(url, headers)
        page = body.get("itemSummaries") if isinstance(body, dict) else None
        if not isinstance(page, list) or not page:
            break
        items.extend(page)
        total = body.get("total") if isinstance(body, dict) else None
        offset += len(page)
        if isinstance(total, int) and offset >= total:
            break
        if len(page) < PAGE_LIMIT:
            break
        time.sleep(0.3)
    return items


def fetch_chrono_html(query):
    try:
        import requests
    except ImportError:
        return None, "requests is not installed"
    url = "https://www.chrono24.com/search/index.htm?" + urllib.parse.urlencode({
        "query": query,
        "dosearch": "true",
        "sortorder": "5",
    })
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WatchDesk/1.0; +https://github.com/torelldan/watch-desk)",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except requests.RequestException as exc:
        return None, str(exc)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    return resp.text, None


def chrono_for_model(model, cap, state, rejected=None):
    """Return (rows, error). state['blocked'] stops later calls after one block."""
    if state.get("blocked"):
        return [], state.get("reason") or "blocked"
    if state.get("unavailable"):
        return [], state["unavailable"]
    html, err = fetch_chrono_html(model["query"])
    if err:
        if err == "requests is not installed" or err.startswith("HTTP ") or "blocked" in err.lower():
            state["blocked"] = True
            state["reason"] = err
        return [], err
    rows, parse_err = parse_chrono24(html, model, cap, rejected)
    if parse_err == "blocked":
        state["blocked"] = True
        state["reason"] = "blocked"
        return [], "blocked"
    return rows, parse_err


def merge_listings(previous, selected_ids, failed_ids, fresh_rows, known_ids=None):
    kept = []
    for row in previous:
        mid = row.get("model_id")
        if known_ids is not None and mid not in known_ids:
            continue
        if mid not in selected_ids or mid in failed_ids:
            kept.append(row)
    return dedupe_rows(kept + fresh_rows)


def sort_listings(rows):
    return sorted(rows, key=lambda r: (str(r.get("model_id")), float(r.get("total") or 0), str(r.get("url"))))


def without_rejected(rows, rejected):
    """Drop parts, non-working watches, and fixed-price outliers. Counts each drop."""
    kept = []
    for row in rows:
        reason = row_reject_reason(row)
        if reason:
            note_reject(rejected, reason)
            continue
        kept.append(row)
    kept, n_cap = drop_below_buy_cap(kept)
    rejected["below_cap"] = rejected.get("below_cap", 0) + n_cap
    kept, n_low = drop_price_outliers(kept)
    rejected["below_median"] = rejected.get("below_median", 0) + n_low
    return kept


def missing_secrets():
    client_id = os.environ.get("EBAY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return None
    print(
        "NOTICE: EBAY_CLIENT_ID and EBAY_CLIENT_SECRET are not set. "
        "Skipping the mine. Add them under Settings > Secrets and variables > Actions. "
        "Exiting without writing listings.",
        flush=True,
    )
    return True


def parse_max_price(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = round(float(raw), 2)
    except ValueError as exc:
        raise SystemExit(f"max price is not a number: {raw!r}") from exc
    if value <= 0:
        raise SystemExit("max price must be greater than 0")
    return value


def run_mine(models_filter, max_price):
    if missing_secrets():
        return 0
    models = load_watchlist()
    selected = select_models(models, models_filter)
    if models_filter and not selected:
        print(f"NOTICE: models filter {models_filter!r} matched nothing in scripts/watchlist.json. No files written.", flush=True)
        return 0
    token = fetch_token(os.environ["EBAY_CLIENT_ID"].strip(), os.environ["EBAY_CLIENT_SECRET"].strip())
    previous = load_json(LISTINGS_PATH, [])
    if not isinstance(previous, list):
        previous = []
    history = load_json(HISTORY_PATH, {})
    if not isinstance(history, dict):
        history = {}
    day = datetime.now(CT).date().isoformat()
    errors = []
    fresh = []
    failed = set()
    chrono_state = {}
    chrono_noted = False
    chrono_failed = set()
    rejected = empty_filter_counts()
    ok = 0
    for index, model in enumerate(selected):
        cap = effective_cap(model, max_price)
        if cap is None:
            errors.append({"model_id": model["id"], "ref": model.get("ref"), "source": "eBay", "error": "no buy cap"})
            failed.add(model["id"])
            continue
        ebay_rows, err = search_ebay(token, model, cap, rejected)
        if ebay_rows is None:
            errors.append({"model_id": model["id"], "ref": model.get("ref"), "source": "eBay", "error": err or "search failed"})
            failed.add(model["id"])
            print(f"{model['ref']}: eBay failed ({err})", flush=True)
            continue
        if err:
            errors.append({"model_id": model["id"], "ref": model.get("ref"), "source": "eBay", "error": err})
        chrono_rows, chrono_err = chrono_for_model(model, cap, chrono_state, rejected)
        published = list(ebay_rows)
        if chrono_err:
            if not (chrono_state.get("blocked") and chrono_noted):
                errors.append({"model_id": model["id"], "ref": model.get("ref"), "source": "Chrono24", "error": chrono_err})
            if chrono_state.get("blocked"):
                chrono_noted = True
            published.extend(
                row for row in previous
                if row.get("model_id") == model["id"] and row.get("source") == "Chrono24"
            )
        else:
            published.extend(chrono_rows)
        published = dedupe_rows(published)
        fresh.extend(published)
        if chrono_err:
            chrono_failed.add(model["id"])
        ok += 1
        print(
            f"{model['ref']}: {sum(1 for r in published if r.get('source') == 'eBay')} eBay, "
            f"{sum(1 for r in published if r.get('source') == 'Chrono24')} Chrono24, cap ${cap:.2f}",
            flush=True,
        )
        if index + 1 < len(selected):
            time.sleep(0.4)
    if ok == 0:
        print("NOTICE: no model succeeded. Left existing mined files untouched.", flush=True)
        for err in errors:
            print(f"  {err.get('source')} {err.get('ref')}: {err.get('error')}", flush=True)
        return 1
    selected_ids = {m["id"] for m in selected}
    known_ids = {m["id"] for m in models}
    merged = without_rejected(
        merge_listings(previous, selected_ids, failed, fresh, known_ids),
        rejected,
    )
    merged = sort_listings(merged)
    for model in selected:
        if model["id"] in failed:
            continue
        history_rows = [row for row in merged if row.get("model_id") == model["id"]]
        # A Chrono24 block keeps yesterday's rows on the page, but they are not
        # today's prices, so they do not set the daily low.
        if model["id"] in chrono_failed:
            history_rows = [row for row in history_rows if row.get("source") != "Chrono24"]
        append_history(history, model, history_point(history_rows), day)
    label, iso = stamp()
    meta = {
        "last_mined": label,
        "last_mined_iso": iso,
        "counts": {
            "models": len(selected),
            "models_ok": ok,
            "listings": len(merged),
            "ebay": sum(1 for r in merged if r.get("source") == "eBay"),
            "chrono24": sum(1 for r in merged if r.get("source") == "Chrono24"),
            "errors": len(errors),
        },
        "filtered": rejected,
        "errors": errors,
        "models_filter": models_filter or "",
        "max_price": max_price,
    }
    save_json(LISTINGS_PATH, merged)
    save_json(META_PATH, meta)
    save_json(HISTORY_PATH, history)
    print(
        f"Wrote {len(merged)} listings. Last mined {label}. {len(errors)} error(s). "
        f"Filtered part {rejected['part']}, not working {rejected['not_working']}, "
        f"below cap {rejected['below_cap']}, below median {rejected['below_median']}, "
        f"excluded {rejected['excluded']}.",
        flush=True,
    )
    return 0


def self_test():
    model = {
        "id": "skx007",
        "brand": "SEIKO",
        "model": "SKX007",
        "ref": "SKX007",
        "query": "Seiko SKX007",
        "buy_cap": 220,
        "title_any": [["SKX007"]],
    }
    item = {
        "itemId": "v1|1|0",
        "title": "Seiko SKX007 diver",
        "itemWebUrl": "https://www.ebay.com/itm/1",
        "price": {"value": "200.00", "currency": "USD"},
        "buyingOptions": ["FIXED_PRICE"],
        "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l400.jpg"},
        "itemEndDate": "2026-11-02T18:00:00.000Z",
        "seller": {"feedbackPercentage": "99.8", "feedbackScore": 1468},
        "itemLocation": {"city": "Stuart", "stateOrProvince": "FL", "country": "US"},
        "shippingOptions": [{"shippingCostType": "FIXED", "shippingCost": {"value": "6.43", "currency": "USD"}}],
    }
    row = listing_from_ebay(model, item, 220)
    assert row["total"] == 206.43, row
    assert row["shipping"] == 6.43
    assert row["image_url"].startswith("https://i.ebayimg.com/")
    assert row["seller_feedback"] == "99.8% · 1,468"
    assert row["location"] == "Stuart, FL, US"
    assert row["format"] == "BIN"
    assert listing_from_ebay(model, item, 206) is None
    item_unknown = dict(item)
    item_unknown.pop("shippingOptions")
    unknown = listing_from_ebay(model, item_unknown, 220)
    assert unknown["shipping"] is None and unknown["shipping_known"] is False and unknown["total"] == 200
    item_eur = json.loads(json.dumps(item))
    item_eur["price"] = {"value": "180", "currency": "EUR"}
    assert listing_from_ebay(model, item_eur, 220) is None
    item_parts = dict(item, title="Seiko SKX007 bezel insert only")
    rejected = empty_filter_counts()
    assert listing_from_ebay(model, item_parts, 220, rejected) is None
    assert rejected["part"] == 1
    assert title_reject_reason("Excellent Tudor 79540 men's watch with 2 original links") is None
    assert title_reject_reason("Omega Seamaster NOT WORKING") == "not_working"
    item_other = dict(item, title="Seiko SKX009 pepsi")
    assert listing_from_ebay(model, item_other, 220) is None
    auction = {
        "title": "Seiko SKX007",
        "itemWebUrl": "https://www.ebay.com/itm/2",
        "buyingOptions": ["AUCTION"],
        "currentBidPrice": {"value": "50", "currency": "USD"},
        "price": {"value": "50", "currency": "USD"},
        "itemEndDate": "2026-11-01T00:00:00.000Z",
    }
    auc = listing_from_ebay(model, auction, 220)
    assert auc["format"] == "auction" and auc["price"] == 50 and auc["image_url"] == ""
    no_image = listing_from_ebay(model, dict(item, image={}), 220)
    assert no_image["image_url"] == ""
    html = """
    <script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[{"@type":"ListItem","item":{
      "@type":"Product","name":"Seiko SKX007","url":"https://www.chrono24.com/seiko/skx007--id1.htm",
      "image":"https://img.chrono24.com/x.jpg",
      "offers":{"price":"199.00","priceCurrency":"USD"}}}]}
    </script>
    """
    rows, err = parse_chrono24(html, model, 220)
    assert err is None and len(rows) == 1 and rows[0]["price"] == 199 and rows[0]["shipping"] is None
    eur = html.replace("USD", "EUR")
    rows, err = parse_chrono24(eur, model, 220)
    assert rows == [] and err is None
    blocked, err = parse_chrono24("<html>Just a moment...</html>", model, 220)
    assert blocked == [] and err == "blocked"
    history = {}
    append_history(history, model, history_point(rows or [row]), "2026-10-28")
    append_history(history, model, {"low": 180, "currency": "USD", "n": 1, "basis": "price+shipping", "source": "eBay", "url": "https://www.ebay.com/itm/9"}, "2026-10-28")
    assert len(history["skx007"]["points"]) == 1 and history["skx007"]["points"][0]["low"] == 180
    append_history(history, model, None, "2026-10-28")
    assert history["skx007"]["points"] == []
    assert history_point([]) is None
    deals = json.loads((DATA / "deals.json").read_text())
    caps = {}
    for deal in deals:
        if isinstance(deal.get("buy"), (int, float)):
            caps.setdefault(deal.get("ref"), set()).add(deal["buy"])
    for entry in load_watchlist():
        assert entry["buy_cap"] in caps.get(entry["ref"], set()), entry["id"]
    chosen = select_models(load_watchlist(), "SKX007, SBGW231")
    assert {m["id"] for m in chosen} == {"skx007", "sbgw231"}
    print("self-test ok", flush=True)


def main(argv):
    parser = argparse.ArgumentParser(description="Mine watch listings into data/*.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--models", default=os.environ.get("MINE_MODELS", ""), help="Comma-separated refs, ids, or brands")
    parser.add_argument("--max-price", default=os.environ.get("MINE_MAX_PRICE", ""), help="Extra USD ceiling applied on top of each buy cap")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    max_price = parse_max_price(args.max_price)
    return run_mine(args.models.strip(), max_price)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
