import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import autofix_feeds  # noqa: E402

NOW = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)


class CommitMessageTest(unittest.TestCase):
    def test_autofix_commit_message(self):
        fixes = [
            ("https://a.com/feed", autofix_feeds.replaced_reason("https://a.com/rss")),
            ("https://b.com/feed", autofix_feeds.abandoned_reason("2024-09-15T00:00:00+00:00", NOW)),
        ]
        self.assertEqual(autofix_feeds.commit_message(fixes, NOW), (
            "Fix dead and abandoned feeds (automatic, 2026-11)\n"
            "\n"
            "- https://a.com/feed: dead feed, replaced by https://a.com/rss\n"
            "- https://b.com/feed: nothing published for 25 months\n"))


if __name__ == "__main__":
    unittest.main()
