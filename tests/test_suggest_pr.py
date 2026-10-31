import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import suggest_pr  # noqa: E402
import validate_opml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = (ROOT / "infosec-intelligence-watchlist.xml").read_text(encoding="utf-8")
READY = {"status": "ready", "link": "https://cyble.com/blog/", "author": "visitor", "why": "",
         "feed": {"url": "https://cyble.com/feed/", "title": "Cyble", "site": "https://cyble.com",
                  "latest": "2026-10-28T00:00:00+00:00", "items": 10, "rate": 1.6, "language": "en",
                  "samples": ["From Hijacked PBX to Stolen Trunk"], "error": None},
         "alternatives": [], "existing": None, "same_site": [], "tried": 3}
AI = {"subcategory": "research-and-labs", "title": "Cyble",
      "description_en": "Threat research blog of Cyble: ransomware, dark web monitoring and vulnerability write-ups.",
      "description_fr": "Blog de recherche de Cyble : rançongiciels, surveillance du dark web et analyses de vulnérabilités.",
      "assessment": "Vendor research blog, mostly original analysis, ~2 posts/week, some product mentions."}


BOT = {"isCrossRepository": False, "author": {"login": "app/github-actions"}}


class WatchlistEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.opml = Path(self.tmp.name) / "watchlist.xml"
        self.desc = Path(self.tmp.name) / "descriptions.json"
        shutil.copy(ROOT / "infosec-intelligence-watchlist.xml", self.opml)
        shutil.copy(ROOT / "site" / "descriptions.json", self.desc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_feed_escapes_and_sorts(self):
        suggest_pr.add_feed(self.opml, "security-news", 'Zeta & "Co" <News>', "https://z.com/feed?a=1&b=2", "https://z.com/")
        suggest_pr.add_feed(self.opml, "security-news", "aaa first", "https://a1.com/feed", "https://a1.com/")
        before, after = ORIGINAL.split("\n"), self.opml.read_text(encoding="utf-8").split("\n")
        self.assertEqual(len(after), len(before) + 2)  # two lines added, nothing else changed
        self.assertEqual([l for l in after if l not in before and "z.com" not in l and "a1.com" not in l], [])
        self.assertEqual(validate_opml.validate(self.opml), [])  # sorted, valid XML, no duplicate
        line = next(l for l in after if "z.com/feed" in l)
        self.assertRegex(line, r'^\s+<outline text=.* title=.* type="rss" xmlUrl=.* htmlUrl=.* />$')
        self.assertIn("&amp;", line)

    def test_add_feed_unknown_subcategory(self):
        with self.assertRaises(ValueError):
            suggest_pr.add_feed(self.opml, "nope", "T", "https://t.com/feed", "")

    def test_add_descriptions_keeps_format(self):
        suggest_pr.add_descriptions(self.desc, "https://z.com/feed", "English text.", "Texte français.")
        text = self.desc.read_text(encoding="utf-8")
        data = json.loads(text)
        self.assertEqual(data["feeds"]["https://z.com/feed"], {"en": "English text.", "fr": "Texte français."})
        self.assertEqual(text, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


class TextsTest(unittest.TestCase):
    def test_commit_message(self):
        self.assertEqual(suggest_pr.commit_message("Cyble", "https://cyble.com/feed/", "visitor", 12),
                         "Add Cyble (suggested in #12)\n\n- https://cyble.com/feed/: suggested by @visitor in #12\n")

    def test_pr_body_with_ai(self):
        body = suggest_pr.pr_body(READY, AI, "Research & Labs", 12)
        self.assertIn("Closes #12", body)
        self.assertIn("- https://cyble.com/feed/: suggested by @visitor in #12", body)
        self.assertIn("AI assessment", body)
        self.assertIn("written by an AI", body)  # descriptions need review

    def test_pr_body_without_ai(self):
        body = suggest_pr.pr_body(READY, None, "Security News", 12)
        self.assertIn("AI unavailable", body)
        self.assertIn("Security News", body)  # fallback placement flagged
        self.assertIn("descriptions.json", body)  # descriptions to write

    def test_find_open_pr_for_url(self):
        prs = [{"url": "https://github.com/o/r/pull/3", "headRefName": "suggestion/issue-9", **BOT,
                "body": "- https://cyble.com/feed/: suggested by @x in #9"},
               {"url": "https://github.com/o/r/pull/4", "headRefName": "feed-health/autofix", **BOT,
                "body": "https://cyble.com/feed/"}]
        self.assertEqual(suggest_pr.find_open_pr_for_url(prs, "https://cyble.com/feed/"), "https://github.com/o/r/pull/3")
        self.assertIsNone(suggest_pr.find_open_pr_for_url(prs, "https://other.com/feed"))

    def test_fork_or_human_prs_are_not_the_bots(self):
        fork = {"url": "https://github.com/o/r/pull/7", "headRefName": "suggestion/issue-9", "state": "OPEN",
                "isCrossRepository": True, "author": {"login": "app/github-actions"},
                "body": "- https://cyble.com/feed/: x"}
        human = {**fork, "url": "https://github.com/o/r/pull/8", "isCrossRepository": False, "author": {"login": "mallory"}}
        bot = {**fork, "url": "https://github.com/o/r/pull/9", **BOT}
        self.assertIsNone(suggest_pr.find_open_pr_for_url([fork, human], "https://cyble.com/feed/"))
        self.assertIsNone(suggest_pr.bot_pr_for_branch([fork, human], "suggestion/issue-9"))
        self.assertEqual(suggest_pr.bot_pr_for_branch([fork, human, bot], "suggestion/issue-9")["url"],
                         "https://github.com/o/r/pull/9")

    def test_safe_title(self):
        self.assertEqual(suggest_pr.safe_title("Foo fixes #3 @everyone"), "Foo fixes 3 everyone")
        self.assertEqual(suggest_pr.safe_title("  A\u202eB\n\tC  "), "AB C")  # bidi override and control chars
        self.assertEqual(len(suggest_pr.safe_title("x" * 2000)), 80)
        self.assertEqual(suggest_pr.safe_title("###"), "")


if __name__ == "__main__":
    unittest.main()
