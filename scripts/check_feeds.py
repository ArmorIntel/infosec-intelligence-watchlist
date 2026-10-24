#!/usr/bin/env python3
"""Check the health of every feed in the watchlist.

Each feed is fetched with curl; failures are retried once after a delay.
Feeds are then classified using the review criteria documented in the README:

- dead: fails twice (DNS error, HTTP 404/410/5xx, timeout, invalid
  certificate, or not a valid RSS/Atom document)
- check: answers 401/403/418/419/429, has an incomplete TLS certificate chain
  or an unsupported encoding; usually anti-bot protection or a server quirk,
  the feed often still works in RSS readers
- inactive: nothing published for more than --max-age-days (default 6 months)
- abandoned: nothing published for more than --abandoned-days (default 24 months)
- undated: valid feed whose items carry no date

Feeds listed in scripts/feed-exceptions.txt (agreed low-frequency, high-value
sources, known server quirks) are reported separately instead of being flagged,
unless they are abandoned.

Usage:
    python3 scripts/check_feeds.py --markdown report.md --json report.json
    python3 scripts/check_feeds.py --urls-file new.txt --fail-on dead,inactive
"""
import argparse
import html.entities
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "infosec-intelligence-watchlist.xml"
EXCEPTIONS = ROOT / "scripts" / "feed-exceptions.txt"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
CHECK_CODES = {401, 403, 418, 419, 429}
DATE_TAGS = {"pubdate", "published", "updated", "date", "issued", "modified"}
XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
NOW = datetime.now(timezone.utc)
META = b"\n__CHECK_FEEDS__"


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        d = None
    if d is None:
        m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?", text)
        if not m:
            return None
        try:
            d = datetime.fromisoformat(m.group(1) + ("T" + m.group(2) if m.group(2) else ""))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    # ignore dates in the future (bad metadata)
    return d if d <= NOW + timedelta(days=2) else None


def local(tag):
    return tag.rsplit("}", 1)[-1].lower()


def html_entities_to_numeric(body):
    """Many feeds use HTML entities (&nbsp;, &eacute;...) that strict XML rejects."""
    def repl(m):
        name = m.group(1).decode()
        if name in XML_ENTITIES or name not in html.entities.name2codepoint:
            return m.group(0)
        return f"&#{html.entities.name2codepoint[name]};".encode()
    return re.sub(rb"&([A-Za-z][A-Za-z0-9]*);", repl, body)


def parse_feed(body):
    """Return (latest item date or None, item count); raise if not a feed."""
    body = body.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        root = ET.fromstring(html_entities_to_numeric(body))
    if local(root.tag) not in ("rss", "feed", "rdf", "channel"):
        raise ValueError(f"not a feed (root element <{local(root.tag)}>)")
    items = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    best = None
    for item in items:
        for child in item:
            if local(child.tag) in DATE_TAGS:
                d = parse_date(child.text)
                if d and (best is None or d > best):
                    best = d
    if best is None:  # undated items: fall back to the channel build date
        for e in root.iter():
            if local(e.tag) in ("lastbuilddate", "updated", "pubdate"):
                d = parse_date(e.text)
                if d and d.year > 2000 and (best is None or d > best):
                    best = d
    return best, len(items)


def fetch(url, timeout):
    res = {"url": url}
    cmd = ["curl", "-sS", "-L", "--compressed", "--http1.1", "--max-time", str(timeout), "--max-filesize", "20000000",
           "-A", UA, "-H", "Accept: application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
           "-w", META.decode() + "%{http_code} %{url_effective}", url]
    p = subprocess.run(cmd, capture_output=True)
    body, _, meta = p.stdout.rpartition(META)
    code, _, final = meta.decode(errors="replace").partition(" ")
    res["final_url"] = final or url
    if p.returncode:
        err = p.stderr.decode(errors="replace").strip().splitlines()
        err = err[0] if err else f"curl exit {p.returncode}"
        incomplete_chain = p.returncode == 60 and "local issuer" in err
        bad_encoding = p.returncode == 61 or (p.returncode == 56 and "encoding" in err)
        res["status"] = "check" if incomplete_chain or bad_encoding else "dead"
        res["error"] = err[:160]
        return res
    code = int(code) if code.isdigit() else 0
    if code >= 400:
        res["status"] = "check" if code in CHECK_CODES else "dead"
        res["error"] = f"HTTP {code}"
        return res
    if not body.strip():
        res["status"], res["error"] = "check", f"empty response (HTTP {code})"
        return res
    try:
        latest, count = parse_feed(body)
    except Exception as e:
        # anti-bot challenge pages are HTML served with a 200
        challenge = re.search(rb"(?i)incapsula|cloudflare|captcha|challenge-platform", body[:5000])
        # slightly malformed feeds are usually tolerated by RSS readers
        looks_like_feed = re.search(rb"<(rss|feed|rdf:RDF)[\s>]", body[:2000])
        res["status"] = "check" if challenge or looks_like_feed else "dead"
        if challenge:
            res["error"] = "anti-bot challenge page"
        elif looks_like_feed:
            res["error"] = f"malformed XML, readers usually tolerate it: {e}"[:160]
        else:
            res["error"] = f"invalid feed: {e}"[:160]
        return res
    res["status"] = "ok"
    res["items"] = count
    res["latest"] = latest.isoformat() if latest else None
    return res


def classify(res, max_age, abandoned):
    if res["status"] != "ok":
        return res["status"]
    if not res.get("latest"):
        return "undated"
    age = NOW - datetime.fromisoformat(res["latest"])
    if age > timedelta(days=abandoned):
        return "abandoned"
    if age > timedelta(days=max_age):
        return "inactive"
    return "ok"


def load_feeds(opml, urls_file=None):
    feeds = []

    def walk(node, path):
        for o in node.findall("outline"):
            if o.get("xmlUrl"):
                feeds.append({"title": o.get("title") or o.get("text"), "url": o.get("xmlUrl"),
                              "folder": " > ".join(path)})
            else:
                walk(o, path + [o.get("title") or o.get("text")])

    walk(ET.parse(opml).getroot().find("body"), [])
    if urls_file:
        wanted = {u.strip() for u in Path(urls_file).read_text().splitlines() if u.strip()}
        known = {f["url"] for f in feeds}
        feeds = [f for f in feeds if f["url"] in wanted]
        feeds += [{"title": u, "url": u, "folder": ""} for u in sorted(wanted - known)]
    return feeds


def load_exceptions(path):
    """URL -> reason, from lines like 'https://... # reason'."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        url, _, reason = line.partition("#")
        if url.strip():
            out[url.strip()] = reason.strip()
    return out


SECTIONS = [
    ("dead", "Dead feeds", "Failed twice. Update the URL if the source moved, otherwise remove the feed."),
    ("abandoned", "Abandoned feeds", "Nothing published for more than {abandoned} days. Remove, even for high-value sources."),
    ("inactive", "Inactive feeds", "Nothing published for more than {max_age} days. Remove, or add it to `scripts/feed-exceptions.txt` if it is a low-frequency high-value source (CERT, government, research lab, recognised researcher, primary source)."),
    ("check", "To check manually", "Anti-bot protection, incomplete TLS certificate chain or unsupported encoding: these feeds usually still work in RSS readers. Check in your reader before acting."),
    ("undated", "Feeds without dates", "Valid feeds whose items carry no date: check manually."),
]


def table(rows, show_reason=False):
    lines = ["| Feed | Folder | Detail |", "|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["folder"], r["title"].casefold())):
        detail = r.get("error") or (f"last item {r['latest'][:10]}" if r.get("latest") else "")
        if show_reason and r.get("exception"):
            detail = f"{detail} ({r['exception']})" if detail else r["exception"]
        moved = r.get("final_url")
        if r["class"] == "dead" and moved and moved.rstrip("/") != r["url"].rstrip("/"):
            detail += f" (redirects to {moved})"
        title = r["title"].replace("|", "\\|")
        lines.append(f"| [{title}]({r['url']}) | {r['folder']} | {detail.replace('|', '/')} |")
    return lines


def markdown(results, args):
    flagged = [r for r in results if r["class"] != "ok" and not r.get("exception")]
    known = [r for r in results if r["class"] != "ok" and r.get("exception")]
    counts = {k: sum(1 for r in flagged if r["class"] == k) for k, *_ in SECTIONS}
    lines = [f"Feed health check of **{len(results)} feeds** run on {NOW:%Y-%m-%d}: "
             f"**{len(results) - len(flagged) - len(known)} healthy**, {len(flagged)} to review, "
             f"{len(known)} known exceptions.", "",
             "| Status | Feeds |", "|---|---:|"]
    lines += [f"| {title} | {counts[k]} |" for k, title, _ in SECTIONS]
    for key, title, help_text in SECTIONS:
        rows = [r for r in flagged if r["class"] == key]
        if rows:
            lines += ["", f"### {title} ({len(rows)})", "",
                      help_text.format(max_age=args.max_age_days, abandoned=args.abandoned_days), ""]
            lines += table(rows)
    if known:
        lines += ["", f"<details><summary>Known exceptions ({len(known)})</summary>", "",
                  "Listed in `scripts/feed-exceptions.txt`.", ""]
        lines += table(known, show_reason=True)
        lines += ["", "</details>"]
    if not flagged:
        lines += ["", "Nothing to review this month."]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--opml", default=str(SOURCE))
    p.add_argument("--urls-file", help="only check these URLs (one per line)")
    p.add_argument("--max-age-days", type=int, default=183)
    p.add_argument("--abandoned-days", type=int, default=730)
    p.add_argument("--retry-delay", type=int, default=60, help="seconds before retrying failed feeds")
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--markdown", help="write a Markdown report to this file")
    p.add_argument("--json", help="write the raw results to this file")
    p.add_argument("--fail-on", default="", help="comma-separated classes that make the script exit 1, e.g. dead,inactive")
    args = p.parse_args()

    feeds = [f for f in load_feeds(args.opml, args.urls_file) if f["url"].startswith(("http://", "https://"))]
    if not feeds:
        print("No feed to check.")
        return 0

    def fetch_one(feed):
        return {**feed, **fetch(feed["url"], args.timeout)}

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(fetch_one, feeds))
        retry = [i for i, r in enumerate(results) if r["status"] != "ok"]
        if retry:
            print(f"Retrying {len(retry)} feeds in {args.retry_delay}s...", file=sys.stderr)
            time.sleep(args.retry_delay)
            for i, r in zip(retry, ex.map(fetch_one, [feeds[i] for i in retry])):
                # dead only if both attempts are dead; "check" on either attempt wins
                if r["status"] == "ok" or results[i]["status"] != "check":
                    results[i] = r

    exceptions = load_exceptions(EXCEPTIONS)
    for r in results:
        r["class"] = classify(r, args.max_age_days, args.abandoned_days)
        if r["url"] in exceptions and r["class"] != "abandoned":
            r["exception"] = exceptions[r["url"]] or "known exception"

    report = markdown(results, args)
    if args.markdown:
        Path(args.markdown).write_text(report, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(report)

    fail_on = {c.strip() for c in args.fail_on.split(",") if c.strip()}
    failing = [r for r in results if r["class"] in fail_on and not r.get("exception")]
    for r in failing:
        print(f"::error title=Feed check failed::{r['title']} ({r['url']}): {r['class']} {r.get('error', '')}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
