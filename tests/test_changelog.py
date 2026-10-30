import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import changelog  # noqa: E402
from fixtures import git_repo, opml  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "changelog.py"

OLD = opml({
    "Cat > One": [("Alpha", "https://alpha.com/feed"), ("Blog B", "https://b.com/rss"),
                  ("Gone", "https://gone.com/feed"), ("Delta old name", "https://www.delta.com/old/")],
    "Cat > Two": [("Stay", "https://stay.com/feed")],
})
NEW = opml({
    "Cat > One": [("Blog B", "https://b2.com/rss"), ("Delta", "https://delta.com/new"),
                  ("Fresh", "https://fresh.com/feed")],
    "Cat > Two": [("Alpha", "https://alpha.com/feed"), ("Stay", "http://stay.com/feed/")],
})

# Output of `changelog.py --from <old> --to <new>` captured before diff_feeds was extracted.
EXPECTED = """Watchlist changes since `{old}`: **5 → 5 feeds** (1 added, 1 removed, 1 moved, 2 URL updates).

### Added (1)

**Cat > One**
- Fresh

### Removed (1)

**Cat > One**
- Gone

### Moved to another folder (1)

**Cat > Two**
- Alpha (from Cat > One)

### Feed URL updated (2)

**Cat > One**
- Blog B
- Delta
"""


class DiffFeedsTest(unittest.TestCase):
    def test_diff_feeds(self):
        old = {
            "alpha.com/feed": ("Alpha", "Cat > One"),
            "b.com/rss": ("Blog B", "Cat > One"),
            "gone.com/feed": ("Gone", "Cat > One"),
            "delta.com/old": ("Delta old name", "Cat > One"),
            "stay.com/feed": ("Stay", "Cat > Two"),
        }
        new = {
            "alpha.com/feed": ("Alpha", "Cat > Two"),
            "b2.com/rss": ("blog b", "Cat > Two"),
            "delta.com/new": ("Delta", "Cat > One"),
            "fresh.com/feed": ("Fresh", "Cat > One"),
            "stay.com/feed": ("Stay", "Cat > Two"),
        }
        d = changelog.diff_feeds(old, new)
        self.assertEqual(d["added"], ["fresh.com/feed"])
        self.assertEqual(d["removed"], ["gone.com/feed"])
        self.assertEqual(sorted(d["updated"]), [("b.com/rss", "b2.com/rss"), ("delta.com/old", "delta.com/new")])
        # a moved pair may also be a URL update (Blog B changed folder and URL)
        self.assertEqual(sorted(d["moved"]), [("alpha.com/feed", "alpha.com/feed"), ("b.com/rss", "b2.com/rss")])

    def test_diff_feeds_duplicate_titles_deterministic(self):
        # two old feeds share a title: the pairing must not depend on the hash seed
        old = {"y.com/a": ("Dup", "F"), "x.com/a": ("Dup", "F")}
        new = {"z.com/a": ("Dup", "F")}
        d = changelog.diff_feeds(old, new)
        self.assertEqual(d["updated"], [("x.com/a", "z.com/a")])
        self.assertEqual(d["removed"], ["y.com/a"])

    def test_diff_feeds_empty_old(self):
        d = changelog.diff_feeds({}, {"a.com/f": ("A", "X > Y")})
        self.assertEqual(d, {"added": ["a.com/f"], "removed": [], "moved": [], "updated": []})


class MainOutputTest(unittest.TestCase):
    def test_main_output_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = git_repo(tmp, [(OLD, "old", "2026-01-01T00:00:00Z"), (NEW, "new", "2026-02-01T00:00:00Z")])
            out = subprocess.run([sys.executable, str(SCRIPT), "--from", old, "--to", new],
                                 cwd=tmp, check=True, capture_output=True, text=True).stdout
        self.assertEqual(out, EXPECTED.format(old=old))


if __name__ == "__main__":
    unittest.main()
