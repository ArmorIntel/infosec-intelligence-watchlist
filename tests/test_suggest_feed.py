import sys
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import autofix_feeds  # noqa: E402
import check_feeds  # noqa: E402
import suggest_feed  # noqa: E402
from fixtures import VALID_RSS  # noqa: E402

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


NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)
KNOWN = [{"title": "Main", "url": "https://a.com/feed/", "html": "https://a.com/",
          "folder": "Threat Intelligence > Security News"}]


def rss(days_ago):
    """VALID_RSS whose two items are `days_ago` and `days_ago + 1` days old."""
    newest, older = (format_datetime(NOW - timedelta(days=d)).encode() for d in (days_ago, days_ago + 1))
    return (VALID_RSS.replace(b"Tue, 06 Jan 2026 10:00:00 +0000", newest)
            .replace(b"Mon, 05 Jan 2026 10:00:00 +0000", older))


RECENT, OLD = rss(3), rss(400)


def declares(*hrefs):
    return (0, "".join(f'<link rel="alternate" type="application/rss+xml" href="{h}">' for h in hrefs))


class AnalyseTest(unittest.TestCase):
    def run_analyse(self, link, pages=None, feeds=None, redirects=None, blocked=(), blocked_all=False):
        """analyse() with a fake network: `feeds` serve bodies, `blocked` URLs answer 403, the rest 404."""
        pages, feeds, redirects = pages or {}, feeds or {}, redirects or {}

        def download(url, timeout):
            if blocked_all or url in blocked:
                return {"url": url, "final_url": url, "status": "check", "error": "HTTP 403"}, b""
            final = redirects.get(url, url)
            if final in feeds:
                return {"url": url, "final_url": final, "_code": 200}, feeds[final]
            return {"url": url, "final_url": url, "status": "dead", "error": "HTTP 404"}, b""

        with mock.patch.object(check_feeds, "download", side_effect=download), \
                mock.patch.object(check_feeds, "NOW", NOW), \
                mock.patch.object(autofix_feeds, "fetch_page", side_effect=lambda u, t: pages.get(u, (0, ""))):
            return suggest_feed.analyse(link, KNOWN, 5, NOW)

    def test_ready_new_feed(self):
        r = self.run_analyse("https://b.com/post", pages={"https://b.com/post": declares("https://b.com/feed")},
                             feeds={"https://b.com/feed": RECENT})
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["feed"]["url"], "https://b.com/feed")
        self.assertEqual(r["feed"]["title"], "Example feed")
        self.assertEqual(r["feed"]["language"], "en")
        self.assertEqual(r["feed"]["samples"][:2], ["First", "Second"])
        self.assertEqual(r["same_site"], [])

    def test_same_site_other_feed_is_ready_with_notice(self):
        r = self.run_analyse("https://a.com/security/post",
                             pages={"https://a.com/security/post": declares("https://a.com/security/feed")},
                             feeds={"https://a.com/security/feed": RECENT})
        self.assertEqual(r["status"], "ready")
        self.assertEqual([k["url"] for k in r["same_site"]], ["https://a.com/feed/"])

    def test_duplicate(self):
        r = self.run_analyse("https://a.com/post", pages={"https://a.com/post": declares("http://www.a.com/feed")},
                             feeds={"http://www.a.com/feed": RECENT})
        self.assertEqual(r["status"], "duplicate")
        self.assertEqual(r["existing"]["title"], "Main")

    def test_redirect_to_known_feed_is_duplicate(self):
        r = self.run_analyse("https://a.com/rss", feeds={"https://a.com/feed/": RECENT},
                             redirects={"https://a.com/rss": "https://a.com/feed/"})
        self.assertEqual(r["status"], "duplicate")

    def test_direct_feed_link(self):
        r = self.run_analyse("https://c.com/rss.xml", feeds={"https://c.com/rss.xml": RECENT})
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["feed"]["url"], "https://c.com/rss.xml")

    def test_inactive(self):
        r = self.run_analyse("https://f.com/post", pages={"https://f.com/post": declares("/feed")},
                             feeds={"https://f.com/feed": OLD})
        self.assertEqual(r["status"], "inactive")
        self.assertEqual(r["feed"]["latest"][:10], "2025-09-26")

    def test_needs_review_declared_but_blocked(self):
        r = self.run_analyse("https://e.com/post", pages={"https://e.com/post": declares("https://e.com/feed")},
                             blocked={"https://e.com/feed"})
        self.assertEqual(r["status"], "needs-review")
        self.assertEqual(r["feed"]["error"], "HTTP 403")

    def test_blocked_guesses_are_not_needs_review(self):
        r = self.run_analyse("https://g.com/post", blocked_all=True)
        self.assertEqual(r["status"], "no-feed")
        self.assertGreater(r["tried"], 0)

    def test_prefers_feed_closest_to_the_article(self):
        r = self.run_analyse("https://d.com/security/post",
                             pages={"https://d.com/security/post": declares("/feed", "/security/feed")},
                             feeds={"https://d.com/feed": RECENT, "https://d.com/security/feed": RECENT})
        self.assertEqual(r["feed"]["url"], "https://d.com/security/feed")
        self.assertEqual(r["alternatives"], ["https://d.com/feed"])


if __name__ == "__main__":
    unittest.main()
