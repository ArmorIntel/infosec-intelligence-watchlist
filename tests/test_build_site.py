import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_site  # noqa: E402
import site_changes  # noqa: E402
import feed_items  # noqa: E402

OPML = """<?xml version="1.0"?>
<opml version="2.0"><head><title>t</title></head><body>
  <outline text="Threat Intelligence" title="Threat Intelligence">
    <outline text="Security News" title="Security News">
      <outline type="rss" text="A" title="A" xmlUrl="https://a.com/feed" htmlUrl="https://a.com"/>
      <outline type="rss" text="B" title="B" xmlUrl="https://b.com/feed" htmlUrl="https://b.com"/>
      <outline type="rss" text="C" title="C" xmlUrl="https://c.com/feed" htmlUrl="https://c.com"/>
      <outline type="rss" text="D" title="D" xmlUrl="https://d.com/feed" htmlUrl="https://d.com"/>
    </outline>
  </outline>
</body></opml>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = json.dumps({"generated": "x", "feeds": {"u": {"latest": None}}}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/missing":
            self.send_response(404)
            self.end_headers()
        else:
            self.send_response(500)
            self.end_headers()

    def log_message(self, *args):
        pass


class LoadPreviousTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_previous_404_is_empty(self):
        self.assertEqual(build_site.load_previous(self.base + "/missing", None), {})

    def test_previous_500_exits(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            build_site.load_previous(self.base + "/boom", None)
        self.assertEqual(cm.exception.code, 1)

    def test_previous_ok(self):
        self.assertEqual(build_site.load_previous(self.base + "/ok", None), {"u": {"latest": None}})

    def test_previous_none(self):
        self.assertEqual(build_site.load_previous(None, None), {})


class BuildTest(unittest.TestCase):
    def run_main(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return build_site.main(list(args))

    def test_guard_trips(self):
        def fake(url, timeout):
            if url.startswith("https://a.com"):
                return {"status": "ok", "items": []}
            return {"status": "dead", "error": "HTTP 404"}

        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "w.xml"
            opml.write_text(OPML, encoding="utf-8")
            out = Path(tmp) / "out"
            with mock.patch.object(feed_items, "fetch_items", fake):
                code = self.run_main("--opml", str(opml), "--out", str(out), "--retry-delay", "0")
            self.assertEqual(code, 1)
            self.assertFalse((out / "index.html").exists())

    def test_build_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            code = self.run_main("--offline", "--out", str(out))
            self.assertEqual(code, 0)
            data = json.loads((out / "data.json").read_text(encoding="utf-8"))
            self.assertIn("generated", data)
            self.assertIsInstance(data["feeds"], dict)
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "fr" / "index.html").exists())
            self.assertTrue((out / ".nojekyll").exists())
            self.assertTrue((out / "infosec-intelligence-watchlist.xml").exists())
            self.assertTrue(any((out / "opml").rglob("*.opml")))

    def build(self, fake, *extra, previous=None):
        with tempfile.TemporaryDirectory() as tmp:
            opml = Path(tmp) / "w.xml"
            opml.write_text(OPML, encoding="utf-8")
            out = Path(tmp) / "out"
            args = ["--opml", str(opml), "--out", str(out), "--retry-delay", "0", *extra]
            if previous is not None:
                prev = Path(tmp) / "prev.json"
                prev.write_text(json.dumps({"generated": "x", "feeds": previous}), encoding="utf-8")
                args += ["--previous-file", str(prev)]
            with mock.patch.object(feed_items, "fetch_items", fake):
                code = self.run_main(*args)
            data = json.loads((out / "data.json").read_text(encoding="utf-8")) if (out / "data.json").exists() else None
            return code, data

    def test_build_passes_changes(self):
        fake_changes = [{"date": "2026-10-29T10:00:00+00:00", "commit": "abc1234", "subject": "S", "kind": "added",
                         "title": "Unique change title", "folder": "X > Y", "previous_folder": None,
                         "url": "https://x.com/feed", "reason": "why"}]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(site_changes, "collect_changes", return_value=fake_changes) as collect:
            out = Path(tmp) / "out"
            self.assertEqual(self.run_main("--offline", "--out", str(out)), 0)
            self.assertIn("Unique change title", (out / "changes" / "index.html").read_text(encoding="utf-8"))
        repo, since = collect.call_args[0]
        self.assertEqual(repo, build_site.ROOT)
        self.assertAlmostEqual((datetime.now(timezone.utc) - since).days, 365, delta=1)

    def test_build_without_git_history(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(site_changes, "collect_changes",
                                  side_effect=site_changes.HistoryUnavailable("shallow clone")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            out = Path(tmp) / "out"
            self.assertEqual(build_site.main(["--offline", "--out", str(out)]), 0)
            self.assertTrue((out / "changes" / "index.html").exists())
        self.assertIn("shallow clone", err.getvalue())

    def test_build_fetches_all_feeds(self):
        code, data = self.build(lambda url, timeout: {"status": "ok", "items": []})
        self.assertEqual(code, 0)
        self.assertEqual(len(data["feeds"]), 4)

    def test_retry_recovers_failed_feed(self):
        calls = {}

        def fake(url, timeout):
            calls[url] = calls.get(url, 0) + 1
            if url.startswith("https://b.com") and calls[url] == 1:
                return {"status": "dead", "error": "HTTP 500"}
            return {"status": "ok", "items": [{"title": "T", "link": "https://b.com/1",
                                               "date": "2020-01-01T00:00:00+00:00"}]}

        code, data = self.build(fake)
        self.assertEqual(code, 0)
        self.assertEqual(calls["https://b.com/feed"], 2)
        self.assertEqual(calls["https://a.com/feed"], 1)
        self.assertIsNotNone(data["feeds"]["https://b.com/feed"]["latest"])

    def test_retry_keeps_first_check_result(self):
        calls = {}

        def fake(url, timeout):
            calls[url] = calls.get(url, 0) + 1
            if url.startswith("https://b.com"):
                return {"status": "check" if calls[url] == 1 else "dead", "error": "x"}
            return {"status": "ok", "items": []}

        failures = []
        real = build_site.fetch_all
        with mock.patch.object(build_site, "fetch_all",
                               lambda *a: failures.append(real(*a)) or failures[-1]):
            code, _ = self.build(fake)
        self.assertEqual(code, 0)
        self.assertEqual(calls["https://b.com/feed"], 2)
        self.assertEqual(failures[0]["https://b.com/feed"]["status"], "check")

    def test_failing_feed_keeps_previous_state(self):
        prev_state = {"latest": {"title": "Old", "link": "https://b.com/old", "date": "2020-01-01T00:00:00+00:00"},
                      "items": [], "rate": 1.5, "fetched": "2020-01-02T00:00:00+00:00"}

        def fake(url, timeout):
            if url.startswith("https://b.com"):
                return {"status": "dead", "error": "HTTP 500"}
            return {"status": "ok", "items": []}

        code, data = self.build(fake, previous={"https://b.com/feed": prev_state})
        self.assertEqual(code, 0)
        self.assertEqual(data["feeds"]["https://b.com/feed"], prev_state)


if __name__ == "__main__":
    unittest.main()
