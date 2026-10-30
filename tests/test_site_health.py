import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import site_health  # noqa: E402
from site_health import WINDOW_DAYS  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
START = (NOW.date() - timedelta(days=WINDOW_DAYS - 1)).isoformat()


def items(*days_ago):
    return [{"title": "t", "link": "https://x", "date": (NOW - timedelta(days=d)).isoformat()} for d in days_ago]


def history(**feeds):
    return {"start": START, "since": "2026-08-01", "feeds": feeds, "errors": {}}


class RunStates(unittest.TestCase):
    def test_codes(self):
        fresh = {
            "ok": {"status": "ok", "items": items(1)},
            "undated": {"status": "ok", "items": [{"title": "t", "link": "l", "date": None}]},
            "stale": {"status": "ok", "items": items(200)},
            "kept": {"status": "ok", "items": items(200)},
            "blocked": {"status": "check", "error": "HTTP 403"},
            "down": {"status": "dead", "error": "HTTP 500"},
        }
        self.assertEqual(site_health.run_states(fresh, NOW, {"kept": ""}), {
            "ok": "o", "undated": "o", "stale": "i", "kept": "o", "blocked": "c", "down": "f"})

    def test_future_dates_do_not_hide_inactivity(self):
        fresh = {"u": {"status": "ok", "items": items(200, -30)}}
        self.assertEqual(site_health.run_states(fresh, NOW), {"u": "i"})


class Record(unittest.TestCase):
    def test_first_run(self):
        h = site_health.record({}, {"u": {"status": "ok"}}, {"u": "o"}, ["u"], NOW)
        self.assertEqual(h["start"], START)
        self.assertEqual(h["since"], "2026-10-30")
        self.assertEqual(h["feeds"]["u"], "-" * (WINDOW_DAYS - 1) + "o")
        self.assertEqual(h["errors"], {})

    def test_same_day_success_wins(self):
        h = history(u="-" * WINDOW_DAYS)
        for code in ("c", "f", "o", "f", "c"):
            h = site_health.record(h, {}, {"u": code}, ["u"], NOW)
        self.assertEqual(h["feeds"]["u"][-1], "o")

    def test_failure_beats_collection_issue(self):
        h = history(u="-" * WINDOW_DAYS)
        for code in ("c", "f", "c"):
            h = site_health.record(h, {}, {"u": code}, ["u"], NOW)
        self.assertEqual(h["feeds"]["u"][-1], "f")

    def test_window_moves_and_gap_days_are_blank(self):
        h = history(u="o" * WINDOW_DAYS)
        later = NOW + timedelta(days=3)
        h = site_health.record(h, {}, {"u": "f"}, ["u"], later)
        self.assertEqual(h["start"], (date.fromisoformat(START) + timedelta(days=3)).isoformat())
        self.assertEqual(h["feeds"]["u"], "o" * (WINDOW_DAYS - 3) + "--f")
        self.assertEqual(h["since"], "2026-08-01")

    def test_new_and_removed_feeds(self):
        h = history(old="o" * WINDOW_DAYS, kept="o" * WINDOW_DAYS)
        h["errors"] = {"old": {"date": NOW.isoformat(), "error": "x"}}
        h = site_health.record(h, {}, {"kept": "o", "new": "o"}, ["kept", "new"], NOW)
        self.assertEqual(sorted(h["feeds"]), ["kept", "new"])
        self.assertEqual(h["feeds"]["new"], "-" * (WINDOW_DAYS - 1) + "o")
        self.assertEqual(h["errors"], {})

    def test_errors_kept_until_out_of_window(self):
        h = history(a="o" * WINDOW_DAYS, b="o" * WINDOW_DAYS)
        h["errors"] = {"a": {"date": (NOW - timedelta(days=10)).isoformat(), "error": "old"},
                       "b": {"date": (NOW - timedelta(days=200)).isoformat(), "error": "gone"}}
        fresh = {"c": {"status": "dead", "error": "HTTP 500"}}
        h = site_health.record(h, fresh, {"c": "f"}, ["a", "b", "c"], NOW)
        self.assertEqual(h["errors"]["a"]["error"], "old")
        self.assertNotIn("b", h["errors"])
        self.assertEqual(h["errors"]["c"], {"date": NOW.isoformat(), "error": "HTTP 500"})

    def test_malformed_previous_is_ignored(self):
        h = site_health.record({"start": "nope", "feeds": {"u": "zz"}}, {}, {"u": "o"}, ["u"], NOW)
        self.assertEqual(h["feeds"]["u"], "-" * (WINDOW_DAYS - 1) + "o")


class Availability(unittest.TestCase):
    def test_collection_days_left_out(self):
        self.assertEqual(site_health.availability("oooofcc--"), (0.8, 5))
        self.assertEqual(site_health.availability("cc--"), (None, 0))
        self.assertEqual(site_health.availability("ii"), (1.0, 2))

    def test_unstable(self):
        self.assertTrue(site_health.unstable("-" * 83 + "oooooff"))  # 5/7
        self.assertFalse(site_health.unstable("-" * 84 + "ooooff"))   # 6 observed days only
        self.assertFalse(site_health.unstable("f" * 60 + "o" * 30))   # old failures don't count
        self.assertFalse(site_health.unstable("c" * 90))
        self.assertFalse(site_health.unstable("o" * 60 + "o" * 24 + "f" * 6))  # exactly 80%

    def test_summary(self):
        self.assertEqual(site_health.summary("oof"), "incident")
        self.assertEqual(site_health.summary("ooi"), "incident")
        self.assertEqual(site_health.summary("ooc"), "collection")
        self.assertEqual(site_health.summary("oo-"), "clean")
        self.assertEqual(site_health.summary("---"), "empty")


if __name__ == "__main__":
    unittest.main()
