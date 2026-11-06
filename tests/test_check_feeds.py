import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_feeds  # noqa: E402
from fixtures import VALID_RSS  # noqa: E402


class FetchTest(unittest.TestCase):
    def test_fetch_uses_download(self):
        u = "https://example.com/feed"
        with mock.patch.object(check_feeds, "download", return_value=({"url": u, "final_url": u}, VALID_RSS)):
            res = check_feeds.fetch(u, 5)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["items"], 2)

        failed = {"url": u, "final_url": u, "status": "dead", "error": "HTTP 404"}
        with mock.patch.object(check_feeds, "download", return_value=(failed, b"")):
            res = check_feeds.fetch(u, 5)
        self.assertEqual(res["status"], "dead")
        self.assertEqual(res["error"], "HTTP 404")


class ParseFeedTest(unittest.TestCase):
    def test_edit_of_an_old_item_does_not_make_the_feed_recent(self):
        body = b"""<rss version="2.0"><channel><title>t</title>
<item><title>a</title><pubDate>Wed, 25 Sep 2024 23:00:00 +0000</pubDate>
<atom:updated xmlns:atom="http://www.w3.org/2005/Atom">Thu, 16 Jul 2026 14:53:02 +0000</atom:updated></item>
<item><title>b</title><pubDate>Mon, 23 Sep 2024 10:00:00 +0000</pubDate></item>
</channel></rss>"""
        latest, count = check_feeds.parse_feed(body)
        self.assertEqual(count, 2)
        self.assertEqual(latest.date().isoformat(), "2024-09-25")

    def test_atom_entry_with_only_updated_still_dated(self):
        body = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>
<entry><title>a</title><updated>2026-10-01T00:00:00Z</updated></entry>
</feed>"""
        latest, _ = check_feeds.parse_feed(body)
        self.assertEqual(latest.date().isoformat(), "2026-10-01")


if __name__ == "__main__":
    unittest.main()
