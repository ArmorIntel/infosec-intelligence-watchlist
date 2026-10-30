import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import site_data  # noqa: E402

OPML = """<?xml version="1.0"?>
<opml version="2.0"><head><title>t</title></head><body>
  <outline text="Threat Intelligence" title="Threat Intelligence">
    <outline text="Vendors" title="Vendors">
      <outline type="rss" text="A" title="Feed A" xmlUrl="https://a.com/feed" htmlUrl="https://a.com"/>
      <outline type="rss" text="B" title="Feed B" xmlUrl="https://b.com/feed" htmlUrl="https://b.com"/>
    </outline>
    <outline text="Empty" title="Empty"/>
  </outline>
  <outline text="Security News" title="Security News">
    <outline text="Media &amp; Blogs" title="Media &amp; Blogs">
      <outline type="rss" text="C" title="Feed C" xmlUrl="https://c.com/feed" htmlUrl="https://c.com"/>
      <outline type="rss" text="D" title="Feed D" xmlUrl="https://d.com/feed" htmlUrl="https://d.com"/>
    </outline>
  </outline>
</body></opml>
"""

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def item(n, days_ago, title=None):
    return {"title": title or f"t{n}", "link": f"https://x.com/{n}",
            "date": iso(days_ago) if days_ago is not None else None}


def watchlist_fixture():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "w.xml"
        p.write_text(OPML, encoding="utf-8")
        return site_data.load_watchlist(p)


class WatchlistTest(unittest.TestCase):
    def test_load_watchlist(self):
        wl = watchlist_fixture()
        self.assertEqual([c["slug"] for c in wl], ["threat-intelligence", "security-news"])
        self.assertEqual([c["name"] for c in wl], ["Threat Intelligence", "Security News"])
        self.assertEqual(len(wl[0]["subcategories"]), 1)  # empty one skipped
        sub = wl[0]["subcategories"][0]
        self.assertEqual(sub["slug"], "vendors")
        self.assertEqual(sub["opml"], "opml/threat-intelligence/vendors.opml")
        self.assertEqual(sub["feeds"][0], {"title": "Feed A", "url": "https://a.com/feed", "html": "https://a.com"})
        sub2 = wl[1]["subcategories"][0]
        self.assertEqual((sub2["name"], sub2["slug"]), ("Media & Blogs", "media-and-blogs"))
        self.assertEqual(sub2["opml"], "opml/security-news/media-and-blogs.opml")

    def test_missing_descriptions(self):
        wl = watchlist_fixture()
        both = {"en": "x", "fr": "y"}
        desc = {
            "categories": {"threat-intelligence": both, "vendors": {"en": "x"}, "security-news": both},
            "feeds": {"https://a.com/feed": {"en": "x"}, "https://b.com/feed": both,
                      "https://c.com/feed": both, "https://d.com/feed": both},
        }
        self.assertEqual(site_data.missing_descriptions(wl, desc), sorted([
            "Feed A (https://a.com/feed)", "category vendors", "category media-and-blogs"]))

    def test_load_descriptions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "d.json"
            p.write_text(json.dumps({"categories": {}, "feeds": {}}))
            self.assertEqual(site_data.load_descriptions(p), {"categories": {}, "feeds": {}})


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.wl = watchlist_fixture()

    def merge(self, fresh, previous=None):
        return site_data.merge_state(self.wl, fresh, previous or {}, NOW)

    def test_merge_fresh(self):
        items = [item(1, 10), item(2, 1), item(3, 3), item(4, None)]
        st = self.merge({"https://a.com/feed": {"status": "ok", "items": items}})["https://a.com/feed"]
        self.assertEqual(st["latest"], items[1])
        self.assertEqual([i["link"] for i in st["items"]], ["https://x.com/2", "https://x.com/3"])
        self.assertEqual(st["fetched"], NOW.isoformat())
        self.assertIsNotNone(st["rate"])

    def test_latest_falls_back_to_first(self):
        items = [item(1, None), item(2, None)]
        st = self.merge({"https://a.com/feed": {"status": "ok", "items": items}})["https://a.com/feed"]
        self.assertEqual(st["latest"], items[0])
        self.assertEqual(st["items"], [])

    def test_old_item_can_be_latest(self):
        items = [item(1, 30)]
        st = self.merge({"https://a.com/feed": {"status": "ok", "items": items}})["https://a.com/feed"]
        self.assertEqual(st["latest"], items[0])
        self.assertEqual(st["items"], [])

    def test_merge_failed_keeps_previous(self):
        prev = {"latest": item(1, 2), "items": [item(1, 2)], "rate": 1.0, "fetched": iso(1)}
        out = self.merge({"https://a.com/feed": {"status": "dead", "error": "x"}}, {"https://a.com/feed": prev})
        self.assertEqual(out["https://a.com/feed"], prev)

    def test_merge_failed_without_previous(self):
        out = self.merge({"https://a.com/feed": {"status": "check", "error": "x"}})
        self.assertEqual(out["https://a.com/feed"],
                         {"latest": None, "items": [], "rate": None, "fetched": None})

    def test_merge_drops_removed_feed(self):
        out = self.merge({}, {"https://gone.com/feed": {"latest": None, "items": [], "rate": None, "fetched": None}})
        self.assertNotIn("https://gone.com/feed", out)
        self.assertEqual(set(out), {"https://a.com/feed", "https://b.com/feed",
                                    "https://c.com/feed", "https://d.com/feed"})

    def test_future_dates_ignored_for_rate(self):
        items = [item(1, -5), item(2, 2), item(3, 4)]
        st = self.merge({"https://a.com/feed": {"status": "ok", "items": items}})["https://a.com/feed"]
        self.assertEqual(st["latest"], items[0])
        ref = site_data.feed_items.posting_rate(
            [datetime.fromisoformat(i["date"]) for i in items[1:]], NOW)
        self.assertEqual(st["rate"], ref)

    def test_failure_ratio(self):
        fresh = {"a": {"status": "ok", "items": []}, "b": {"status": "dead"},
                 "c": {"status": "check"}, "d": {"status": "dead"}}
        self.assertEqual(site_data.failure_ratio(fresh), 0.75)
        self.assertEqual(site_data.failure_ratio({}), 0.0)


class NewsTest(unittest.TestCase):
    def setUp(self):
        self.wl = watchlist_fixture()

    def state(self, a_items, c_items=()):
        empty = {"latest": None, "items": [], "rate": None, "fetched": None}
        st = {u: dict(empty) for sub in (s for c in self.wl for s in c["subcategories"]) for u in
              (f["url"] for f in sub["feeds"])}
        st["https://a.com/feed"] = {**empty, "items": list(a_items)}
        st["https://c.com/feed"] = {**empty, "items": list(c_items)}
        return st

    def test_news_window_and_caps(self):
        a = [item(i, 0.001 * i + 0.5) for i in range(60)]
        a += [item(900, 8), item(901, None), item(902, -1)]
        c = [item(1000 + i, 1 + 0.001 * i) for i in range(60)]
        out = site_data.news(self.wl, self.state(a, c), NOW)
        self.assertEqual(set(out), {"vendors", "media-and-blogs", "all"})
        self.assertEqual(len(out["vendors"]), 50)
        self.assertEqual(len(out["media-and-blogs"]), 50)
        self.assertEqual(len(out["all"]), 100)
        links = {i["link"] for k in out for i in out[k]}
        self.assertTrue({"https://x.com/900", "https://x.com/901", "https://x.com/902"}.isdisjoint(links))
        dates = [i["date"] for i in out["all"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        first = out["vendors"][0]
        self.assertEqual((first["source"], first["source_url"]), ("Feed A", "https://a.com"))

    def test_news_dedup(self):
        a = [item(1, 1), item(1, 2)]
        c = [item(1, 1)]
        out = site_data.news(self.wl, self.state(a, c), NOW)
        self.assertEqual(len(out["vendors"]), 1)
        self.assertEqual(len(out["all"]), 1)


if __name__ == "__main__":
    unittest.main()
