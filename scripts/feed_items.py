#!/usr/bin/env python3
"""Extract article items (title, link, date) from a feed for the website.

Only the title, link and date of each item are kept, never its content.
"""
import html
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from urllib.parse import urljoin, urlparse

import check_feeds
from check_feeds import html_entities_to_numeric, local, parse_date

MAX_ITEMS = 50
MAX_TITLE = 200
ITEM_DATE_TAGS = ("pubdate", "published", "date", "issued", "updated", "modified")


def clean_title(text):
    text = re.sub(r"<[^>]*>", "", text or "")
    text = " ".join(html.unescape(text).split())
    return text if len(text) <= MAX_TITLE else text[:MAX_TITLE - 1] + "\u2026"


def item_link(item, base_url):
    candidates = []
    for child in item:
        if local(child.tag) != "link":
            continue
        href = (child.get("href") or child.text or "").strip()
        if href:
            rel = child.get("rel", "alternate")
            candidates.append((rel != "alternate", href))
    for _, href in sorted(candidates, key=lambda c: c[0]):  # stable: alternate first
        url = urljoin(base_url, href)
        if urlparse(url).scheme in ("http", "https"):
            return url
        break
    return None


def item_date(item):
    found = {}
    for child in item:
        name = local(child.tag)
        if name in ITEM_DATE_TAGS and name not in found:
            found[name] = parse_date(child.text)
    for name in ITEM_DATE_TAGS:
        if found.get(name):
            return found[name].astimezone(timezone.utc).isoformat()
    return None


def parse_items(body, base_url):
    """Return up to 50 {"title", "link", "date"} dicts, in feed order."""
    body = body.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        root = ET.fromstring(html_entities_to_numeric(body))
    if local(root.tag) not in ("rss", "feed", "rdf", "channel"):
        raise ValueError(f"not a feed (root element <{local(root.tag)}>)")
    items = []
    for e in root.iter():
        if local(e.tag) not in ("item", "entry"):
            continue
        link = item_link(e, base_url)
        if not link:
            continue
        title = ""
        for child in e:
            if local(child.tag) == "title":
                title = clean_title("".join(child.itertext()))
                break
        items.append({"title": title or link, "link": link, "date": item_date(e)})
        if len(items) == MAX_ITEMS:
            break
    return items


def posting_rate(dates, now):
    """Posts per week over the span of the dated items, or None with fewer than 2."""
    if len(dates) < 2:
        return None
    span_days = max((now - min(dates)).days, 1)
    return round(len(dates) / span_days * 7, 1)


def fetch_items(url, timeout):
    """Download a feed and return {"status": "ok", "items": [...]} or {"status", "error"}."""
    res, body = check_feeds.download(url, timeout)
    if "status" in res:
        return {"status": res["status"], "error": res.get("error", "")}
    if not body.strip():
        return {"status": "check", "error": f"empty response (HTTP {res.get('_code', 200)})"}
    try:
        items = parse_items(body, res.get("final_url") or url)
    except Exception as e:
        status, error = check_feeds.classify_failure(body, e)
        return {"status": status, "error": error}
    return {"status": "ok", "items": items}
