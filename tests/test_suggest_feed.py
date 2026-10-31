import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import autofix_feeds  # noqa: E402
import check_feeds  # noqa: E402
import suggest_feed  # noqa: E402

FORM = ("### Link to an article or page of the source\n\nhttps://blog.example.com/2026/10/post\n\n"
        "### Why is it useful? (optional)\n\n_No response_")


class ParseIssueTest(unittest.TestCase):
    def test_parse_issue_form(self):
        self.assertEqual(suggest_feed.parse_issue(FORM), ("https://blog.example.com/2026/10/post", ""))
        body = FORM.replace("_No response_", "Great CTI research")
        self.assertEqual(suggest_feed.parse_issue(body)[1], "Great CTI research")

    def test_parse_issue_rejects_bad_links(self):
        for value in ["", "not a link", "ftp://x.com/a", "javascript:alert(1)",
                      "https://a.com/x https://b.com/y"]:
            body = FORM.replace("https://blog.example.com/2026/10/post", value)
            self.assertIsNone(suggest_feed.parse_issue(body)[0], value)

    def test_parse_issue_without_headings(self):
        self.assertEqual(suggest_feed.parse_issue("Please add <https://a.com/post> thanks")[0], "https://a.com/post")
        self.assertIsNone(suggest_feed.parse_issue("https://a.com/1 and https://b.com/2")[0])

    def test_md_text_neutralises_markup(self):
        out = suggest_feed.md_text("@everyone <img src=x> [x](https://e.vil) a|b `c`\n" + "z" * 300)
        self.assertNotIn("@everyone", out)  # mention broken by a zero-width space
        for ch in "<>[]|`\n":
            self.assertNotIn(ch, out.replace("\\" + ch, ""))  # only escaped occurrences left
        self.assertLessEqual(len(out), 121)  # limit + ellipsis


class DiscoverTest(unittest.TestCase):
    def test_discover_declared_links_first(self):
        page = '<link rel="alternate" type="application/rss+xml" href="/security/feed/">'
        pages = {"https://a.com/security/2026/post": (0, page), "https://a.com/security/2026/": (0, ""),
                 "https://a.com/": (0, "")}
        with mock.patch.object(autofix_feeds, "fetch_page", side_effect=lambda u, t: pages.get(u, (0, ""))), \
                mock.patch.object(check_feeds, "fetch", return_value={"status": "dead"}):
            found = suggest_feed.discover_feeds("https://a.com/security/2026/post", 5)
        self.assertEqual(found, [{"url": "https://a.com/security/feed/", "guess": False}])

    def test_discover_falls_back_to_common_paths(self):
        with mock.patch.object(autofix_feeds, "fetch_page", return_value=(0, "<html></html>")), \
                mock.patch.object(check_feeds, "fetch", return_value={"status": "dead"}):
            found = suggest_feed.discover_feeds("https://a.com/news/post", 5)
        self.assertTrue(found and all(c["guess"] for c in found))
        self.assertIn({"url": "https://a.com/feed/", "guess": True}, found)
        self.assertLessEqual(len(found), autofix_feeds.MAX_CANDIDATES)

    def test_discover_direct_feed(self):
        with mock.patch.object(check_feeds, "fetch", return_value={"status": "ok", "latest": None}):
            found = suggest_feed.discover_feeds("https://a.com/rss.xml", 5)
        self.assertEqual(found, [{"url": "https://a.com/rss.xml", "guess": False}])


if __name__ == "__main__":
    unittest.main()
