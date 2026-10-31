#!/usr/bin/env python3
"""Check a source suggested by a visitor through the "Suggest a source" issue form.

From the link pasted in the issue (an article or any page of the site, or the
feed itself), find the site's feeds (autodiscovery links of the page, its
parent path and the site root, then common feed paths), check them with the
same rules as check_feeds.py, and write the answer posted on the issue.

Statuses:
- ready: a valid feed, new to the watchlist, published within 6 months
- duplicate: the feed is already in the watchlist
- no-feed: no feed found from the link
- inactive: the feed found has published nothing for more than 6 months
- needs-review: a feed declared by the site, but blocked to scripts or undated
- invalid: the issue has no single http(s) link
- limit: the author already has too many open suggestions
- skip: nothing to do (closed issue, or the link did not change on an edit)

Usage:
    python3 scripts/suggest_feed.py --issue issue.json --open-suggestions 0 \\
        --json result.json --comment comment.md
"""
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autofix_feeds  # noqa: E402
import check_feeds  # noqa: E402
import feed_items  # noqa: E402
import site_data  # noqa: E402

MAX_AGE_DAYS = 183
ABANDONED_DAYS = 730
TIMEOUT = 20
SAMPLE_TITLES = 10
MARKER = "<!-- feed-suggestion-bot -->"
LINK_HEADING = "Link to an article"
WHY_HEADING = "Why is it useful"
URL_RE = re.compile(r"https?://[^\s<>]+")
MD_SPECIAL = set("\\`*_[]<>|#")


def _sections(body):
    """{heading: text} of an issue form body (### headings)."""
    out = {}
    for block in re.split(r"(?m)^###\s+", body)[1:]:
        heading, _, text = block.partition("\n")
        out[heading.strip()] = text.strip()
    return out


def _field(sections, prefix):
    return next((text for heading, text in sections.items() if heading.startswith(prefix)), None)


def parse_issue(body):
    """(link, why) from an issue body; link is None unless there is exactly one http(s) URL."""
    body = body or ""
    sections = _sections(body)
    link_text = _field(sections, LINK_HEADING)
    if link_text is None:
        link_text = body  # blank issue, or form headings removed
    urls = URL_RE.findall(link_text)
    link = urls[0] if len(urls) == 1 else None
    why = _field(sections, WHY_HEADING) or ""
    if why == "_No response_":
        why = ""
    return link, why


def md_text(text, limit=120):
    """One line of Markdown-safe text: markup escaped, mentions broken, cut to `limit`."""
    out = ""
    for ch in " ".join(str(text or "").split()):
        piece = "\\" + ch if ch in MD_SPECIAL else "@​" if ch == "@" else ch
        if len(out) + len(piece) > limit:
            return out + "…"
        out += piece
    return out


def discover_feeds(url, timeout):
    """Candidate feeds for a page, most likely first: [{"url", "guess"}]."""
    if check_feeds.fetch(url, timeout).get("status") == "ok":
        return [{"url": url, "guess": False}]
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}/"
    parent = urljoin(url, "./")
    found = []
    for page in dict.fromkeys([url, parent, root]):
        _, html = autofix_feeds.fetch_page(page, timeout)
        parser = autofix_feeds.LinkParser()
        try:
            parser.feed(html)
        except Exception:
            pass
        found += [(urljoin(page, href), False) for href in parser.feeds]
    if not found:
        for base in dict.fromkeys([parent, root]):
            found += [(urljoin(base, path), True) for path in autofix_feeds.COMMON_PATHS]
    seen, out = set(), []
    for candidate, guess in found:
        key = autofix_feeds.norm(candidate)
        if candidate.startswith(("http://", "https://")) and key not in seen:
            seen.add(key)
            out.append({"url": candidate, "guess": guess})
    return out[:autofix_feeds.MAX_CANDIDATES]


def host(url):
    return re.sub(r"^www\.", "", urlsplit(url or "").netloc.lower())


def channel_info(body):
    """(title, site URL) declared by an RSS or Atom feed, empty strings when missing."""
    body = body.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        root = ET.fromstring(check_feeds.html_entities_to_numeric(body))
    channel = next((e for e in root.iter() if check_feeds.local(e.tag) == "channel"), root)
    title = site = ""
    for child in channel:
        name = check_feeds.local(child.tag)
        if name == "title" and not title:
            title = " ".join("".join(child.itertext()).split())
        elif name == "link" and not site:
            if child.get("href") and child.get("rel", "alternate") == "alternate":
                site = child.get("href")
            elif (child.text or "").strip():
                site = child.text.strip()
    return title, site


def describe(url, timeout, now):
    """What the comment shows about one feed, from a single download."""
    res, body = check_feeds.download(url, timeout)
    final = res.get("final_url") or url
    parts = urlsplit(final)
    feed = {"url": final, "title": host(final), "site": f"{parts.scheme}://{parts.netloc}/", "latest": None,
            "items": 0, "rate": None, "language": None, "samples": [], "error": res.get("error")}
    if "status" in res:
        return feed
    try:
        items = feed_items.parse_items(body, final)
        latest, feed["items"] = check_feeds.parse_feed(body)
        title, site = channel_info(body)
    except Exception as e:
        feed["error"] = check_feeds.classify_failure(body, e)[1]
        return feed
    feed["title"] = title or feed["title"]
    if site.startswith(("http://", "https://")):
        feed["site"] = site
    feed["latest"] = latest.isoformat() if latest else None
    dates = [datetime.fromisoformat(it["date"]) for it in items if it.get("date")]
    feed["rate"] = feed_items.posting_rate(dates, now)
    feed["language"] = site_data.feed_language(items)
    feed["samples"] = [it["title"] for it in items[:SAMPLE_TITLES]]
    return feed


def _shared_segments(a, b):
    """Number of leading path segments two URLs share."""
    n = 0
    for x, y in zip(urlsplit(a).path.strip("/").split("/"), urlsplit(b).path.strip("/").split("/")):
        if x != y:
            break
        n += 1
    return n


def analyse(link, known, timeout, now):
    """Find, check and describe the feed behind a suggested link (see the statuses above)."""
    candidates = discover_feeds(link, timeout)
    with ThreadPoolExecutor(8) as ex:
        checked = list(ex.map(lambda c: check_feeds.fetch(c["url"], timeout), candidates))
    by_key = {}
    for k in known:
        by_key.setdefault(autofix_feeds.norm(k["url"]), k)
    rows = []
    for c, res in zip(candidates, checked):
        final = res.get("final_url") or c["url"]
        rows.append({"url": c["url"], "guess": c["guess"], "res": res,
                     "class": check_feeds.classify(res, MAX_AGE_DAYS, ABANDONED_DAYS),
                     "known": by_key.get(autofix_feeds.norm(c["url"])) or by_key.get(autofix_feeds.norm(final))})
    result = {"status": "no-feed", "link": link, "feed": None, "alternatives": [], "existing": None,
              "same_site": [], "tried": len(candidates)}

    new_ok = [r for r in rows if r["class"] == "ok" and not r["known"]]
    if new_ok:
        # sorted() is stable: equally close feeds keep their discovery order
        new_ok = sorted(new_ok, key=lambda r: -_shared_segments(link, r["url"]))
        feed = describe(new_ok[0]["url"], timeout, now)
        h = host(feed["url"])
        result.update(status="ready", feed=feed, alternatives=[r["url"] for r in new_ok[1:]],
                      same_site=[k for k in known if h in (host(k["url"]), host(k.get("html")))])
        return result
    dup = next((r for r in rows if r["known"]), None)
    if dup:
        result.update(status="duplicate", existing=dup["known"])
        return result
    review = next((r for r in rows if not r["guess"] and r["class"] in ("check", "undated")), None)
    if review:
        result.update(status="needs-review", feed=describe(review["url"], timeout, now))
        return result
    stale = [r for r in rows if r["class"] in ("inactive", "abandoned")]
    if stale:
        newest = max(stale, key=lambda r: r["res"]["latest"])
        result.update(status="inactive", feed=describe(newest["url"], timeout, now))
    return result
