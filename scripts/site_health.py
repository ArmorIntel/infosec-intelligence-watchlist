"""Feed health history for the website: one state per feed per UTC day.

Standard library only. The history is stored in the published data.json and
carried from one deploy to the next, like the feed items:

    {"start": "YYYY-MM-DD",   # day of the first character of every string
     "since": "YYYY-MM-DD",   # first day ever recorded, kept when the window moves
     "feeds": {url: "oo-ffc..."},           # WINDOW_DAYS characters, oldest first
     "errors": {url: {"date", "error"}}}    # last failure of each feed

Day codes, from worst to best for merging two runs of the same day:
"-" no run, "c" collection issue (blocked or unreadable for our runner, usually
fine in readers), "f" failing, "i" inactive (fetched, nothing new for
INACTIVE_DAYS), "o" ok.
"""
from datetime import date, timedelta, timezone

import site_data

WINDOW_DAYS = 90
INACTIVE_DAYS = 183  # same as the monthly health check's --max-age-days
UNSTABLE_DAYS = 30
UNSTABLE_MIN_OBSERVED = 7
UNSTABLE_BELOW = 0.8
RANK = {"-": 0, "c": 1, "f": 2, "i": 3, "o": 4}


def _day(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def run_states(fresh, now, exceptions=()):
    """Day code of each feed for this run; `fresh`: url -> feed_items.fetch_items result."""
    states = {}
    for url, r in fresh.items():
        status = r.get("status")
        if status == "ok":
            dates = [d for i in r.get("items", []) if (d := site_data._parse(i.get("date"))) and d <= now]
            stale = dates and now - max(dates) > timedelta(days=INACTIVE_DAYS)
            states[url] = "i" if stale and url not in exceptions else "o"
        else:
            states[url] = "c" if status == "check" else "f"
    return states


def record(previous, fresh, states, urls, now):
    """The history `previous` with this run's `states` merged into today's cell.

    Only the feeds in `urls` are kept; new ones start with "-" days. Anything
    malformed in `previous` is dropped rather than failing the build. A
    previous window ahead of `now` (clock gone backwards) is kept unchanged.
    """
    if not isinstance(previous, dict):
        previous = {}
    today = now.astimezone(timezone.utc).date()
    start = today - timedelta(days=WINDOW_DAYS - 1)
    old_start = _day(previous.get("start"))
    if old_start and old_start > start:
        return previous
    old_feeds = previous.get("feeds")
    old_feeds = old_feeds if isinstance(old_feeds, dict) else {}
    shift = (start - old_start).days if old_start else None
    feeds = {}
    for url in urls:
        old = old_feeds.get(url)
        old = old if isinstance(old, str) else ""
        days = [
            old[i + shift] if shift is not None and 0 <= i + shift < len(old) and old[i + shift] in RANK else "-"
            for i in range(WINDOW_DAYS)
        ]
        code = states.get(url)
        if code and RANK[code] > RANK[days[-1]]:
            days[-1] = code
        feeds[url] = "".join(days)

    errors = {}
    old_errors = previous.get("errors")
    for url, err in (old_errors if isinstance(old_errors, dict) else {}).items():
        if not isinstance(err, dict):
            continue
        when = site_data._parse(err.get("date") if isinstance(err.get("date"), str) else None)
        if url in feeds and when and when.date() >= start:
            errors[url] = err
    for url in urls:
        r = fresh.get(url)
        if r and r.get("status") != "ok":
            errors[url] = {"date": now.isoformat(), "error": r.get("error") or r.get("status") or ""}

    # first day ever recorded; when lost, the oldest day still in the window
    since = previous.get("since") if _day(previous.get("since")) else None
    if since is None and old_start and any(set(d) - {"-"} for d in feeds.values()):
        since = max(old_start, start).isoformat()
    return {"start": start.isoformat(), "since": since or today.isoformat(), "feeds": feeds, "errors": errors}


def availability(days):
    """(share of observed days the feed worked, number of observed days); None without any.

    Collection-issue days are left out: they say nothing about the feed itself.
    """
    good = sum(days.count(c) for c in "oi")
    observed = good + days.count("f")
    return (good / observed if observed else None), observed


def unstable(days):
    ratio, observed = availability(days[-UNSTABLE_DAYS:])
    return observed >= UNSTABLE_MIN_OBSERVED and ratio < UNSTABLE_BELOW


def summary(days):
    """Which group of the Health page the feed belongs to."""
    if "f" in days or "i" in days:
        return "incident"
    if "c" in days:
        return "collection"
    return "clean" if "o" in days else "empty"


def day_dates(health):
    """The date of each character of the strings in `health`."""
    start = _day(health.get("start"))
    if start is None:
        return []
    return [start + timedelta(days=i) for i in range(WINDOW_DAYS)]
