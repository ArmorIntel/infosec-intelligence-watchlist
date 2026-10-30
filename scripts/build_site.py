#!/usr/bin/env python3
"""Build the static website from the watchlist.

Every feed is fetched (items are kept for the news pages), merged with the
state of the previous deploy, and the pages are rendered into --out. The
Changes page comes from the git history of the watchlist (last 12 months); without
a full history it is rendered empty, with a warning. If more
than --max-failure-ratio of the feeds fail, nothing is written and the exit
code is 1, so a broken run never replaces a good deploy.

Usage:
    python3 scripts/build_site.py --out _site
    python3 scripts/build_site.py --previous-url https://armorintel.github.io/infosec-intelligence-watchlist/data.json
    python3 scripts/build_site.py --offline --previous-file _site/data.json
    python3 scripts/build_site.py --check-descriptions
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feed_items
import site_changes
import site_data
import site_render

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "infosec-intelligence-watchlist.xml"
OPML_DIR = ROOT / "opml"
DESCRIPTIONS = ROOT / "site" / "descriptions.json"
STRINGS = ROOT / "site" / "strings.json"


def load_previous(url, path):
    """Return the `feeds` state of the previous deploy; {} on first deploy.

    HTTP 404 means the first deploy. Any other error exits with 1, so a flaky
    network never makes the site forget its history.
    """
    if not url and not path:
        return {}
    try:
        if path:
            text = Path(path).read_text(encoding="utf-8")
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "infosec-watchlist-site"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
        return json.loads(text)["feeds"]
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 404:
            return {}
        print(f"Previous data unreachable: HTTP {e.code} for {url}", file=sys.stderr)
    except Exception as e:
        print(f"Previous data unreachable: {e}", file=sys.stderr)
    raise SystemExit(1)


def fetch_all(urls, workers, timeout, retry_delay):
    """Fetch every url, retrying the failures once after retry_delay seconds."""
    def one(url):
        return feed_items.fetch_items(url, timeout)

    with ThreadPoolExecutor(workers) as ex:
        results = dict(zip(urls, ex.map(one, urls)))
        retry = [u for u, r in results.items() if r.get("status") != "ok"]
        if retry:
            print(f"Retrying {len(retry)} feeds in {retry_delay}s...", file=sys.stderr)
            time.sleep(retry_delay)
            for u, r in zip(retry, ex.map(one, retry)):
                if r.get("status") == "ok" or results[u].get("status") != "check":
                    results[u] = r
    return results


def report(missing, failures, total):
    lines = []
    if missing:
        lines += [f"### Feeds missing a description ({len(missing)})", ""] + [f"- {m}" for m in missing]
    if failures:
        lines += ["", f"### Feeds that failed to fetch ({len(failures)} of {total})", ""]
        lines += [f"- {u}: {r.get('status')} {r.get('error', '')}" for u, r in sorted(failures.items())]
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and text:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def load_changes(now):
    """Feed changes of the last 12 months; [] with a warning when they can't be read.

    The build never fails because of the Changes page. The warning is also
    printed as a GitHub Actions annotation, so it shows on the run page.
    """
    try:
        return site_changes.collect_changes(ROOT, now - timedelta(days=365))
    except (site_changes.HistoryUnavailable, ValueError) as e:  # no or malformed history
        message = f"Changes page left empty, git history unavailable: {e}"
    except Exception as e:  # a bug: say so, don't pass it off as missing history
        message = f"Changes page left empty, unexpected error: {type(e).__name__}: {e}"
    print(f"Warning: {message}", file=sys.stderr)
    print(f"::warning::{message}")
    return []


def copy_downloads(out):
    shutil.copy2(SOURCE, out / SOURCE.name)
    target = out / "opml"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(OPML_DIR, target)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="_site")
    p.add_argument("--opml", default=str(SOURCE))
    p.add_argument("--previous-url")
    p.add_argument("--previous-file")
    p.add_argument("--offline", action="store_true", help="don't fetch: build from the previous state only")
    p.add_argument("--check-descriptions", action="store_true",
                   help="only list the feeds missing a description; exit 1 if any")
    p.add_argument("--max-failure-ratio", type=float, default=0.5)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--retry-delay", type=int, default=30)
    args = p.parse_args(argv)

    now = datetime.now(timezone.utc)
    watchlist = site_data.load_watchlist(args.opml)
    descriptions = site_data.load_descriptions(DESCRIPTIONS)
    missing = site_data.missing_descriptions(watchlist, descriptions)

    if args.check_descriptions:
        report(missing, {}, 0)
        return 1 if missing else 0

    previous = load_previous(args.previous_url, args.previous_file)
    urls = [f["url"] for cat in watchlist for sub in cat["subcategories"] for f in sub["feeds"]]
    fresh = {}
    if not args.offline:
        fresh = fetch_all(urls, args.workers, args.timeout, args.retry_delay)
        ratio = site_data.failure_ratio(fresh)
        failures = {u: r for u, r in fresh.items() if r.get("status") != "ok"}
        print(f"{len(failures)} of {len(fresh)} feeds failed ({ratio:.1%})")
        report(missing, failures, len(fresh))
        if ratio > args.max_failure_ratio:
            print(f"Failure ratio above {args.max_failure_ratio:.0%}: nothing written.", file=sys.stderr)
            return 1
    else:
        report(missing, {}, 0)

    state = site_data.merge_state(watchlist, fresh, previous, now)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    site_render.render_site(watchlist, descriptions, state, strings, out, now, changes=load_changes(now))
    (out / "data.json").write_text(
        json.dumps({"generated": now.isoformat(), "feeds": state}, ensure_ascii=False), encoding="utf-8")
    copy_downloads(out)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
