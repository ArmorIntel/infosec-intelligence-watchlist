import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import site_changes  # noqa: E402
from fixtures import git_repo, opml  # noqa: E402

V1 = opml({"Cat > One": [("Alpha", "https://alpha.com/feed"), ("Beta", "https://beta.com/rss")]})
V2 = opml({"Cat > One": [("Alpha", "https://alpha.com/feed"), ("Beta", "https://beta.com/rss"),
                         ("Gamma <g>", "https://www.Gamma.com/feed/")]})
V3 = opml({"Cat > One": [("Beta", "https://beta.com/rss"), ("Gamma <g>", "https://www.Gamma.com/feed/")],
           "Cat > Two": [("Alpha", "https://alpha.com/feed")]})

MSG2 = """Add Gamma

Some prose that is not a reason: really.
- https://gamma.com/feed: Strong CTI source
- https://other.com/x: Not in this commit
"""


class ParseReasonsTest(unittest.TestCase):
    def test_parse_reasons(self):
        msg = ("Subject\n\nWhy we did this - https://x.com: no\n"
               "- https://www.Example.com/feed/: dead feed, replaced by https://example.com/rss\n"
               "- http://b.org/rss: nothing published for 25 months  \n"
               "-https://c.org/rss: missing space\n")
        self.assertEqual(site_changes.parse_reasons(msg), {
            "example.com/feed": "dead feed, replaced by https://example.com/rss",
            "b.org/rss": "nothing published for 25 months",
        })


class CollectChangesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name)
        cls.shas = git_repo(cls.repo, [
            (V1, "Initial watchlist", "2026-01-10T09:00:00Z"),
            (V2, MSG2, "2026-03-05T10:00:00Z"),
            (V3, "Move Alpha to Two", "2026-04-01T08:30:00Z"),
        ])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_collect_changes(self):
        got = site_changes.collect_changes(self.repo, datetime(2025, 1, 1, tzinfo=timezone.utc))
        s1, s2, s3 = self.shas
        self.assertEqual([(c["kind"], c["title"], c["commit"]) for c in got], [
            ("moved", "Alpha", s3),
            ("added", "Gamma <g>", s2),
            ("added", "Alpha", s1),
            ("added", "Beta", s1),
        ])
        moved, gamma, alpha, beta = got
        self.assertEqual(moved["folder"], "Cat > Two")
        self.assertEqual(moved["previous_folder"], "Cat > One")
        self.assertEqual(moved["reason"], "Move Alpha to Two")
        self.assertEqual(moved["subject"], "Move Alpha to Two")
        self.assertEqual(moved["url"], "https://alpha.com/feed")
        self.assertEqual(gamma["reason"], "Strong CTI source")
        self.assertEqual(gamma["subject"], "Add Gamma")
        self.assertEqual(gamma["url"], "https://www.Gamma.com/feed/")
        self.assertIsNone(gamma["previous_folder"])
        self.assertEqual(gamma["folder"], "Cat > One")
        self.assertEqual(datetime.fromisoformat(gamma["date"]), datetime(2026, 3, 5, 10, tzinfo=timezone.utc))
        self.assertEqual(alpha["reason"], "Initial watchlist")

    def test_since_filter(self):
        got = site_changes.collect_changes(self.repo, datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual([c["kind"] for c in got], ["moved", "added"])

    def test_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(site_changes.HistoryUnavailable):
            site_changes.collect_changes(Path(d), datetime(2025, 1, 1, tzinfo=timezone.utc))


class ChangesFromDiffTest(unittest.TestCase):
    def test_url_update_reason_matched_on_old_url(self):
        old = b'<opml><body><outline text="C"><outline text="S"><outline title="F" xmlUrl="https://f.com/old"/></outline></outline></body></opml>'
        new = b'<opml><body><outline text="C"><outline text="S"><outline title="F" xmlUrl="https://f.com/new"/></outline></outline></body></opml>'
        got = site_changes.changes_between(old, new, {"f.com/old": "dead feed, replaced by https://f.com/new"},
                                           {"commit": "abc", "date": "2026-01-01T00:00:00+00:00", "subject": "Fix"})
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "updated")
        self.assertEqual(got[0]["url"], "https://f.com/new")
        self.assertEqual(got[0]["previous_url"], "https://f.com/old")
        self.assertEqual(got[0]["reason"], "dead feed, replaced by https://f.com/new")


if __name__ == "__main__":
    unittest.main()
