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


if __name__ == "__main__":
    unittest.main()
