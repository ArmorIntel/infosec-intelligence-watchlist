#!/usr/bin/env python3
"""Validate the structure of the watchlist OPML.

Checks:
- the file is well-formed XML and an OPML document with a <body>
- the tree has exactly two folder levels (category > subcategory > feeds)
- no empty folder, no feed outside a subcategory
- every feed has a title and an http(s) xmlUrl
- no duplicate feed URL (scheme, "www." and trailing slash ignored)
- feeds are sorted alphabetically inside each subcategory

With --base, also writes the URLs added since that version of the file to
--new-urls, so they can be checked with check_feeds.py.

Usage:
    python3 scripts/validate_opml.py
    python3 scripts/validate_opml.py --base base.xml --new-urls new.txt
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "infosec-intelligence-watchlist.xml"


def norm(url):
    url = re.sub(r"^https?://", "", url.strip().lower())
    return re.sub(r"^www\.", "", url).rstrip("/")


def feed_urls(path):
    return {o.get("xmlUrl") for o in ET.parse(path).iter("outline") if o.get("xmlUrl")}


def validate(path):
    errors = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return [f"invalid XML: {e}"]
    if root.tag != "opml" or root.find("body") is None:
        return ["not an OPML document (missing <opml> or <body>)"]

    seen = {}
    for cat in root.find("body"):
        cat_name = cat.get("title") or cat.get("text") or "?"
        if cat.get("xmlUrl"):
            errors.append(f"feed '{cat_name}' is at the top level, it must be in a subcategory")
            continue
        subs = cat.findall("outline")
        if not subs:
            errors.append(f"category '{cat_name}' is empty")
        for sub in subs:
            sub_name = sub.get("title") or sub.get("text") or "?"
            where = f"{cat_name} > {sub_name}"
            if sub.get("xmlUrl"):
                errors.append(f"feed '{sub_name}' is directly under category '{cat_name}', it must be in a subcategory")
                continue
            feeds = sub.findall("outline")
            if not feeds:
                errors.append(f"subcategory '{where}' is empty")
            titles = []
            for feed in feeds:
                title, url = feed.get("title") or feed.get("text"), feed.get("xmlUrl")
                if not url:
                    errors.append(f"'{where}' contains a third folder level ('{title}'), only two are allowed")
                    continue
                if not title:
                    errors.append(f"feed {url} in '{where}' has no title")
                if not url.startswith(("http://", "https://")):
                    errors.append(f"feed '{title}' in '{where}' has a non-http URL: {url}")
                key = norm(url)
                if key in seen:
                    errors.append(f"duplicate feed '{title}' in '{where}' (already listed as '{seen[key]}'): {url}")
                seen[key] = title
                titles.append(title or "")
            if titles != sorted(titles, key=str.casefold):
                errors.append(f"feeds in '{where}' are not sorted alphabetically")
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("opml", nargs="?", default=str(SOURCE))
    p.add_argument("--base", help="previous version of the OPML, to list added feeds")
    p.add_argument("--new-urls", help="file where the added feed URLs are written")
    args = p.parse_args()

    errors = validate(args.opml)
    for e in errors:
        print(f"::error file={Path(args.opml).name}::{e}")
    if not errors:
        print(f"{Path(args.opml).name}: OK ({len(feed_urls(args.opml))} feeds)")

    if args.base:
        base = {norm(u) for u in feed_urls(args.base)} if Path(args.base).stat().st_size else set()
        added = sorted(u for u in feed_urls(args.opml) if norm(u) not in base)
        print(f"{len(added)} feed(s) added:")
        for u in added:
            print(f"  {u}")
        if args.new_urls:
            Path(args.new_urls).write_text("".join(f"{u}\n" for u in added))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
