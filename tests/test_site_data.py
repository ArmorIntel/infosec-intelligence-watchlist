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


if __name__ == "__main__":
    unittest.main()
