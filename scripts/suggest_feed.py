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
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import autofix_feeds  # noqa: E402
import check_feeds  # noqa: E402

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
