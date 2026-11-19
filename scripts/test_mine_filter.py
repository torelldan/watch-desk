#!/usr/bin/env python3
"""Titles the miner must drop, and complete watches it must keep."""
import unittest

import mine


DROP_PARTS = [
    "OMEGA CROWN 4.5x 7mm 2.8mm FEMALE STEM DYNAMIC DE VILLE DYNAMIC seamaster (C16)",
    "OMEGA 562 565 SEAMASTER DE VILLE DIAL *",
    "seiko skx007 dial",
    "Seiko Sumo Spb103/Sbdc081  Genuine Green Sunburst Hulk Dial",
    "Steel Links & Clasp for Omega De Ville & Seamaster, Men & Women",
    "Lot of 4 piece of TISSOT PRX 40MM T137.407.11.041.00 links only",
    "SEIKO Genuine Stainless Steel Bracelet 22mm for 44G1JZ  SKX007  SKX009  SKX011",
    "CITIZEN 59-S54496 Watch Band Strap for NY0040-09E NY0040-09W NY0040-33L",
    "Seiko D385AG-LK00 Watch Bracelet Link SARB033 SARB035 SARB037 Excellent JAPAN",
    "Bell Ross Genuine BR 03-92 Leather Watch Presentation Box Case",
    "Omega Constellation Seamaster De Ville ORIGINAL Red Box 60s/70s",
    "Vintage 1960's Mens OMEGA Seamaster De Ville 560  Watch Movement, Runs Good.",
    "Omega Ladies Two Tone Quartz De Ville Dial Seamaster Caseback G1205",
    "Omega Seamaster De Ville Stainless Steel Ladies Watch Case Ref. 535.004",
    "VINTAGE OMEGA SEAMASTER DE VILLE DATE DAY GOLD TONE ORIGINAL DIAL  # 619",
    "SEIKO BLACK DIAL Seiko SKX009 7S26-0020 series",
    "Seiko SARB033 SARB035 SARB037 Spare Watch Band Link Stainless Steel Part",
    "Tudor Black Bay 58 79030N Protective Film Seal EP24 From JAPAN",
]

DROP_NOT_WORKING = [
    "Omega Seamaster De Ville 535.002 Vintage Women’s Watch Case For Parts BRG668ALI2",
    "For Parts",
    "NOT WORKING",
    "1960's Omega Seamaster De Ville Automatic Watch NOT WORKING Lot. H35",
    "FOR REPAIR - Bell & Ross Men's White Ceramic Watch BR03-92 Swiss Automatic MOP",
    "Omega Automatic Seamaster De Ville Cal 552 Running For Parts Repair",
    "Vintage 1960s Omega Seamaster De Ville Mens Automatic Watch 14K Gold Bezel AS IS",
    "Omega Seamaster as-is",
    "Seiko SKX007 not running",
    "Lot spares and repair",
]

KEEP = [
    "Tudor Black Bay 41 Self-Winding Stainless Silver Dial Bracelet #79540",
    "Excellent condition Tudor I914902 79540 men's watch with 2 original links, s",
    "Tudor Black Bay Heritage 41 Blue Dial 79540 Automatic No Box Or Papers",
    "eLive- Tudor Black Bay GMT 41mm Pepsi Black Dial 79830RB w/Card 2024",
    "eLive-Tudor Black Bay GMT 41mm Pepsi White Dial 79830RB B&P 2026",
    "*NEAR MINT w/BOX* Vintage OMEGA Seamaster De Ville Cal.630 Silver Women Watch",
    "Vtg 1977 MINT OMEGA Seamaster De Ville Cal.1342 Quartz Push Crown Gold 36mm Mens",
    "[N MINT] Vintage OMEGA De Ville Cal.1365 Quartz Gold Push Crown 29mm Mens Watch",
    "Vintage 1960s Omega Seamaster De Ville Mens Automatic Watch 14K Gold Bezel",
    "1966's OMEGA CONSTELLATION 168.004 S/S AUTOMATIC MEN'S WATCH Nice Leather Strap",
    "SEIKO SKX009 STAINLESS STEEL CASE AUTOMATIC MENS DIVER WATCH ON RUBBER STRAP",
    "[Overhauled] Omega Seamaster De Ville Ladies Manual winding 3 hands Made in",
    "TUDOR Black Bay 79540 Blue - 3 Bracelets BB41",
    "Bell & Ross BR03-92 Black Steel 42mm Automatic Box OEM Leather & Canvas Straps",
    "Bell & Ross BR03-92-S SS SS & Rubber AT black dial",
    "1960's Omega Seamaster De Ville Automatic Original Dial SeaHorse Stainless RUNS",
    "Omega Constellation 36mm SS 168.004 Custom Band",
    "Omega Seamaster repaired men's automatic watch",
]


class TitleFilterTest(unittest.TestCase):
    def test_parts_and_accessories_are_dropped(self):
        for title in DROP_PARTS:
            self.assertEqual(mine.title_reject_reason(title), "part", title)

    def test_not_working_is_dropped(self):
        for title in DROP_NOT_WORKING:
            self.assertEqual(mine.title_reject_reason(title), "not_working", title)

    def test_complete_watches_are_kept(self):
        for title in KEEP:
            self.assertIsNone(mine.title_reject_reason(title), title)

    def test_listing_from_ebay_counts_a_part(self):
        model = {"id": "skx007", "ref": "SKX007", "title_any": [["SKX007"]]}
        item = {
            "title": "seiko skx007 dial",
            "itemWebUrl": "https://www.ebay.com/itm/9",
            "price": {"value": "40", "currency": "USD"},
            "buyingOptions": ["FIXED_PRICE"],
        }
        rejected = mine.empty_filter_counts()
        self.assertIsNone(mine.listing_from_ebay(model, item, 220, rejected))
        self.assertEqual(rejected["part"], 1)


class PriceFloorTest(unittest.TestCase):
    def test_low_auction_stays_and_cheap_bin_part_goes(self):
        rows = [
            row("m", "auction", "eLive- Tudor Black Bay GMT 41mm Pepsi Black Dial", 1, end="2026-11-22T00:00:00Z"),
            row("m", "BIN", "Tudor Black Bay GMT men's watch", 4000),
            row("m", "BIN", "Tudor Black Bay GMT automatic watch", 4200),
            row("m", "BIN", "Tudor Black Bay GMT diver watch", 4500),
            row("m", "BIN", "Tudor 79830RB accessory piece", 40),
        ]
        kept, n_low = mine.drop_price_outliers(rows)
        self.assertEqual(n_low, 1)
        titles = [item["title"] for item in kept]
        self.assertIn("eLive- Tudor Black Bay GMT 41mm Pepsi Black Dial", titles)
        self.assertNotIn("Tudor 79830RB accessory piece", titles)

    def test_cheap_complete_watch_is_not_a_price_outlier(self):
        rows = [
            row("m", "auction", "Tudor Black Bay 41 Self-Winding Stainless Silver Dial Bracelet #79540", 30.99, end="2026-11-22T00:00:00Z"),
            row("m", "BIN", "Excellent condition Tudor I914902 79540 men's watch with 2 original links, s", 288.73),
            row("m", "BIN", "TUDOR Black Bay 79540 Blue - 3 Bracelets BB41", 1950),
            row("m", "BIN", "Tudor Black Bay Heritage 41 Blue Dial 79540 Automatic No Box Or Papers", 1950),
        ]
        kept, n_low = mine.drop_price_outliers(rows)
        self.assertEqual(n_low, 0)
        self.assertEqual(len(kept), 4)

    def test_floor_needs_three_listings(self):
        rows = [
            row("m", "BIN", "mystery piece", 20),
            row("m", "BIN", "another piece", 400),
        ]
        kept, n_low = mine.drop_price_outliers(rows)
        self.assertEqual(n_low, 0)
        self.assertEqual(len(kept), 2)

    def test_without_rejected_counts_each_reason(self):
        rows = [
            row("m", "BIN", "seiko skx007 dial", 40),
            row("m", "BIN", "Seiko SKX007 NOT WORKING", 80),
            row("m", "BIN", "Seiko SKX007 diver watch", 180),
            row("m", "BIN", "Seiko SKX007 automatic mens watch", 200),
            row("m", "auction", "Seiko SKX007 automatic mens watch", 1, end="2026-11-22T00:00:00Z"),
        ]
        rejected = mine.empty_filter_counts()
        kept = mine.without_rejected(rows, rejected)
        self.assertEqual(rejected["part"], 1)
        self.assertEqual(rejected["not_working"], 1)
        self.assertEqual([item["total"] for item in kept], [180, 200, 1])


def row(model_id, fmt, title, total, end=None):
    return {
        "model_id": model_id,
        "format": fmt,
        "title": title,
        "total": total,
        "end_time": end,
    }


if __name__ == "__main__":
    unittest.main()
