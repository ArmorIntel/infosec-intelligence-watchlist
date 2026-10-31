#!/usr/bin/env python3
"""Propose fixes for the problems found by check_feeds.py.

- dead feed, or feed unreachable for --persist-months months in a row (blocked,
  empty or unreadable for the checker): look for a replacement on the same website (feed autodiscovery
  links of the site pages, then common feed paths). A candidate is accepted
  only if it is a valid RSS/Atom feed that published within --max-age-days
  and is not already in the watchlist. The feed URL is updated in place.
- abandoned feed (nothing published for more than 24 months): removed.

The watchlist file is edited in place (one outline per line, so the diff stays
minimal), the --json results are annotated with the fix of each feed, a
pull request description is written to --pr-body and, with --commit-message, a
commit message with one `- <feed URL>: <reason>` line per fix (shown on the
website's Changes page).

Usage:
    python3 scripts/autofix_feeds.py --json results.json --pr-body pr.md --commit-message commit.txt
"""
import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.sax.saxutils import quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_feeds import EXCEPTIONS, SOURCE, UA, fetch, load_exceptions  # noqa: E402

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/rdf+xml")
COMMON_PATHS = ["feed/", "feed", "rss/", "rss", "rss.xml", "feed.xml", "atom.xml", "index.xml",
                "feeds/posts/default", "blog/feed/", "blog/rss.xml", "news/feed/"]
MAX_CANDIDATES = 25


class LinkParser(HTMLParser):
    """Collect <link rel="alternate" type="application/rss+xml" href="..."> tags."""

    def __init__(self):
        super().__init__()
        self.feeds = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "").lower() \
                and (a.get("type") or "").lower() in FEED_TYPES and a.get("href"):
            self.feeds.append(a["href"])


def norm(url):
    url = re.sub(r"^https?://", "", url.strip().lower())
    return re.sub(r"^www\.", "", url).rstrip("/")


def fetch_page(url, timeout):
    """Return (curl exit code, HTML of the page)."""
    p = subprocess.run(["curl", "-sS", "-g", "-L", "--compressed", "--http1.1", "--max-time", str(timeout),
                        "-A", UA, url], capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace")


UNREACHABLE = {6, 7, 28}  # curl: DNS failure, connection refused, timeout


def candidates(feed, timeout):
    """Candidate replacement URLs for a dead feed, most likely first."""
    old = feed["url"]
    parts = urlsplit(old)
    root = f"{parts.scheme}://{parts.netloc}/"
    pages = [feed.get("html") or "", root]
    # the old feed's parent path, e.g. /actualites/feed -> /actualites/
    parent = urljoin(old, "../" if old.endswith("/") else "./")
    if parent != root:
        pages.insert(1, parent)

    found = []
    for page in dict.fromkeys(p for p in pages if p):
        code, html = fetch_page(page, timeout)
        if page == root and code in UNREACHABLE:
            found = []  # the website itself is down: no point guessing paths on it
            break
        parser = LinkParser()
        try:
            parser.feed(html)
        except Exception:
            pass
        found += [urljoin(page, href) for href in parser.feeds]
    else:
        for base in dict.fromkeys([parent, root]):
            found += [urljoin(base, path) for path in COMMON_PATHS]
    # follow where the dead feed redirects to, if it moved to another site
    final = feed.get("final_url")
    if final and urlsplit(final).netloc != parts.netloc:
        final_root = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}/"
        found += [urljoin(final_root, path) for path in COMMON_PATHS]

    seen, out = {norm(old)}, []
    for url in found:
        if url.startswith(("http://", "https://")) and norm(url) not in seen:
            seen.add(norm(url))
            out.append(url)
    return out[:MAX_CANDIDATES]


def find_replacement(feed, known, max_age, timeout):
    """First valid, active candidate in order of likelihood (checked in parallel)."""
    urls = [u for u in candidates(feed, timeout) if norm(u) not in known]
    with ThreadPoolExecutor(8) as ex:
        checked = list(ex.map(lambda u: fetch(u, timeout), urls))
    for url, res in zip(urls, checked):
        if res["status"] != "ok" or not res.get("latest"):
            continue
        if datetime.now(timezone.utc) - datetime.fromisoformat(res["latest"]) > timedelta(days=max_age):
            continue
        final = res.get("final_url") or url
        if norm(final) in known:
            continue
        return final, res
    return None, None


def edit_opml(path, replacements, removals):
    """Apply URL replacements and removals line by line, keeping the file layout."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    out = []
    for line in lines:
        m = re.search(r'xmlUrl=("[^"]*"|\'[^\']*\')', line)
        if m:
            url = ET.fromstring(f"<x u={m.group(1)}/>").get("u")
            if url in removals:
                continue
            if url in replacements:
                line = line.replace(m.group(0), f"xmlUrl={quoteattr(replacements[url])}")
        out.append(line)
    Path(path).write_text("\n".join(out), encoding="utf-8")


def drop_exceptions(path, urls):
    """Remove exception lines of feeds that were removed or got a new URL."""
    if not path.exists() or not urls:
        return
    lines = path.read_text(encoding="utf-8").split("\n")
    kept = [l for l in lines if l.partition("#")[0].strip() not in urls]
    if len(kept) != len(lines):
        path.write_text("\n".join(kept), encoding="utf-8")


def replaced_reason(new_url):
    return f"dead feed, replaced by {new_url}"


def abandoned_reason(latest, now):
    months = (now - datetime.fromisoformat(latest)).days // 30
    return f"nothing published for {months} months"


def commit_message(fixes, now):
    """Commit message for the fixes, a list of (feed URL, reason)."""
    lines = [f"Fix dead and abandoned feeds (automatic, {now:%Y-%m})", ""]
    lines += [f"- {url}: {reason}" for url, reason in fixes]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", required=True, help="results of check_feeds.py --json (annotated in place)")
    p.add_argument("--opml", default=str(SOURCE))
    p.add_argument("--pr-body", required=True, help="where to write the pull request description")
    p.add_argument("--commit-message", help="where to write the commit message of the fixes")
    p.add_argument("--max-age-days", type=int, default=183)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--persist-months", type=int, default=3,
                   help="also look for a replacement for feeds unreachable this many months in a row")
    args = p.parse_args()

    results = json.loads(Path(args.json).read_text(encoding="utf-8"))
    exceptions = load_exceptions(EXCEPTIONS)
    known = {norm(r["url"]) for r in results}
    replacements, removals, body, fixes = {}, set(), [], []
    now = datetime.now(timezone.utc)

    for r in results:
        if r["url"] in exceptions and r["class"] != "abandoned":
            continue
        persistent = r["class"] == "check" and r.get("failing_months", 0) >= args.persist_months
        if r["class"] == "dead" or persistent:
            new_url, res = find_replacement(r, known, args.max_age_days, args.timeout)
            if new_url:
                replacements[r["url"]] = new_url
                known.add(norm(new_url))
                r["fix"] = f"URL replaced by {new_url}"
                fixes.append((r["url"], replaced_reason(new_url)))
                body.append(f"- **{r['title']}** ({r['folder']}): `{r['url']}` → `{new_url}` "
                            f"({r.get('error', 'dead')}; replacement has {res['items']} items, last on {res['latest'][:10]})")
                print(f"replace {r['url']} -> {new_url}")
            else:
                print(f"no replacement found for {r['url']}")
        elif r["class"] == "abandoned":
            removals.add(r["url"])
            r["fix"] = "Removed (abandoned)"
            fixes.append((r["url"], abandoned_reason(r["latest"], now)))
            body.append(f"- **{r['title']}** ({r['folder']}): removed, last item on {r['latest'][:10]}")
            print(f"remove {r['url']}")

    Path(args.json).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    if not body:
        Path(args.pr_body).write_text("")
        if args.commit_message:
            Path(args.commit_message).write_text("")
        print("Nothing to fix automatically.")
        return 0

    edit_opml(args.opml, replacements, removals)
    drop_exceptions(EXCEPTIONS, removals | set(replacements))
    Path(args.pr_body).write_text("\n".join([
        "Automatic fixes proposed by the monthly feed health check.", "",
        "Dead or persistently unreachable feeds get a replacement found on the same website (valid RSS/Atom, published within "
        f"the last {args.max_age_days} days, not already listed); abandoned feeds are removed.", "",
        *body, "",
        "Check the replacements before merging: the new feed should be the same source. "
        "Close the pull request to reject the fixes; the next run proposes them again if the problem remains.",
    ]) + "\n", encoding="utf-8")
    if args.commit_message:
        Path(args.commit_message).write_text(commit_message(fixes, now), encoding="utf-8")
    print(f"{len(replacements)} replacement(s), {len(removals)} removal(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
