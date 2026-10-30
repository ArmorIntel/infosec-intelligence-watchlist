"""Data model for the website: watchlist, descriptions, feed state and news.

Standard library only. `infosec-intelligence-watchlist.xml` stays the single
source of truth; slugs and OPML paths match the ones generated in `opml/`.
"""
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feed_items
from build_category_opml import RAW_BASE, slugify  # noqa: F401  (RAW_BASE re-exported)


def _name(node):
    return node.get("title") or node.get("text") or ""


def load_watchlist(opml_path):
    root = ET.parse(opml_path).getroot()
    watchlist = []
    for cat in root.find("body").findall("outline"):
        cat_name = _name(cat)
        cat_slug = slugify(cat_name)
        subs = []
        for sub in cat.findall("outline"):
            feeds = [
                {"title": _name(o), "url": o.get("xmlUrl"), "html": o.get("htmlUrl") or ""}
                for o in sub.findall("outline") if o.get("xmlUrl")
            ]
            if not feeds:
                continue
            sub_name = _name(sub)
            sub_slug = slugify(sub_name)
            subs.append({
                "name": sub_name,
                "slug": sub_slug,
                "opml": f"opml/{cat_slug}/{sub_slug}.opml",
                "feeds": feeds,
            })
        watchlist.append({"name": cat_name, "slug": cat_slug, "subcategories": subs})
    return watchlist


def load_descriptions(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _complete(entry):
    return bool(entry) and bool(entry.get("en")) and bool(entry.get("fr"))


def missing_descriptions(watchlist, descriptions):
    cats = descriptions.get("categories", {})
    feeds = descriptions.get("feeds", {})
    missing = []
    for cat in watchlist:
        if not _complete(cats.get(cat["slug"])):
            missing.append(f"category {cat['slug']}")
        for sub in cat["subcategories"]:
            if not _complete(cats.get(sub["slug"])):
                missing.append(f"category {sub['slug']}")
            for feed in sub["feeds"]:
                if not _complete(feeds.get(feed["url"])):
                    missing.append(f"{feed['title']} ({feed['url']})")
    return sorted(set(missing))
