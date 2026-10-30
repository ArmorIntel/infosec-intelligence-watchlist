import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_feeds  # noqa: E402
import feed_items  # noqa: E402
from fixtures import (ATOM_LINKS, HTML_TITLE_RSS, NO_LINK_RSS, RDF_FEED,  # noqa: E402
                      RELATIVE_LINK_RSS, UNDATED_RSS, VALID_RSS)

BASE = "https://ex.com/feed"


class ParseItemsTest(unittest.TestCase):
    def test_rss_items(self):
        items = feed_items.parse_items(VALID_RSS, "https://example.com/feed")
        self.assertEqual(items, [
            {"title": "First", "link": "https://example.com/1", "date": "2026-01-05T10:00:00+00:00"},
            {"title": "Second", "link": "https://example.com/2", "date": "2026-01-06T10:00:00+00:00"},
        ])

    def test_atom_alternate_link(self):
        items = feed_items.parse_items(ATOM_LINKS, BASE)
        self.assertEqual([i["link"] for i in items], ["https://ex.com/b", "https://ex.com/c"])

    def test_rdf_items(self):
        items = feed_items.parse_items(RDF_FEED, BASE)
        self.assertEqual([i["title"] for i in items], ["RDF one", "RDF two"])
        self.assertEqual(items[0]["date"], "2026-01-07T10:00:00+00:00")

    def test_relative_link_and_scheme(self):
        items = feed_items.parse_items(RELATIVE_LINK_RSS, BASE)
        self.assertEqual([i["link"] for i in items], ["https://ex.com/posts/1"])

    def test_title_cleanup(self):
        items = feed_items.parse_items(HTML_TITLE_RSS, BASE)
        self.assertEqual(items[0]["title"], "Patch & fix now")
        self.assertEqual(items[1]["title"], "alert(1)Hi")
        long = b"<rss><channel><item><title>" + b"x" * 300 + b"</title><link>https://e.com/</link></item></channel></rss>"
        title = feed_items.parse_items(long, BASE)[0]["title"]
        self.assertEqual(len(title), 200)
        self.assertTrue(title.endswith("…"))

    def test_item_without_link_dropped(self):
        items = feed_items.parse_items(NO_LINK_RSS, BASE)
        self.assertEqual([i["link"] for i in items], ["https://example.com/untitled"])

    def test_item_without_title_uses_link(self):
        items = feed_items.parse_items(NO_LINK_RSS, BASE)
        self.assertEqual(items[0]["title"], "https://example.com/untitled")

    def test_undated_item(self):
        items = feed_items.parse_items(UNDATED_RSS, BASE)
        self.assertIsNone(items[0]["date"])

    def test_max_50_items(self):
        body = b"<rss><channel>" + b"".join(
            b"<item><title>t%d</title><link>https://e.com/%d</link></item>" % (i, i) for i in range(80)
        ) + b"</channel></rss>"
        items = feed_items.parse_items(body, BASE)
        self.assertEqual(len(items), 50)
        self.assertEqual(items[0]["title"], "t0")


class PostingRateTest(unittest.TestCase):
    def test_posting_rate(self):
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        dates = [now - timedelta(days=d) for d in range(1, 15)]
        self.assertEqual(feed_items.posting_rate(dates, now), 7.0)
        self.assertIsNone(feed_items.posting_rate([], now))
        self.assertIsNone(feed_items.posting_rate(dates[:1], now))


class FetchItemsTest(unittest.TestCase):
    def test_fetch_items_failure(self):
        u = "https://example.com/feed"
        failed = {"url": u, "final_url": u, "status": "check", "error": "HTTP 403"}
        with mock.patch.object(check_feeds, "download", return_value=(failed, b"<rss/>")):
            res = feed_items.fetch_items(u, 5)
        self.assertEqual(res["status"], "check")
        self.assertNotIn("items", res)

        ok = {"url": u, "final_url": u, "_code": 200}
        with mock.patch.object(check_feeds, "download", return_value=(ok, b"not a feed at all")):
            res = feed_items.fetch_items(u, 5)
        self.assertEqual(res["status"], "dead")
        with mock.patch.object(check_feeds, "download", return_value=(dict(ok), b"  ")):
            self.assertEqual(feed_items.fetch_items(u, 5)["status"], "check")

    def test_fetch_items_ok(self):
        u = "https://example.com/feed"
        ok = {"url": u, "final_url": u, "_code": 200}
        with mock.patch.object(check_feeds, "download", return_value=(ok, VALID_RSS)):
            res = feed_items.fetch_items(u, 5)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(res["items"]), 2)


if __name__ == "__main__":
    unittest.main()
