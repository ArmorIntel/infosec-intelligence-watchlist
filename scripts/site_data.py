"""Data model for the website: watchlist, descriptions, feed state and news.

Standard library only. `infosec-intelligence-watchlist.xml` stays the single
source of truth; slugs and OPML paths match the ones generated in `opml/`.
"""
import json
import re
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


NEWS_DAYS = 7
NEWS_PER_CATEGORY = 50
NEWS_ALL = 100

EMPTY_STATE = {"latest": None, "items": [], "rate": None, "fetched": None}


def _parse(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def merge_state(watchlist, fresh, previous, now):
    cutoff = now - timedelta(days=NEWS_DAYS)
    state = {}
    for cat in watchlist:
        for sub in cat["subcategories"]:
            for feed in sub["feeds"]:
                url = feed["url"]
                result = fresh.get(url)
                if result and result.get("status") == "ok":
                    dated = [(d, i) for i in result.get("items", []) if (d := _parse(i.get("date")))]
                    items = result.get("items", [])
                    latest = max(dated, key=lambda p: p[0])[1] if dated else (items[0] if items else None)
                    state[url] = {
                        "latest": latest,
                        "items": [i for d, i in dated if d >= cutoff],
                        "rate": feed_items.posting_rate([d for d, _ in dated if d <= now], now),
                        "fetched": now.isoformat(),
                    }
                elif url in previous:
                    state[url] = previous[url]
                else:
                    state[url] = {**EMPTY_STATE, "items": []}
    return state


def failure_ratio(fresh):
    if not fresh:
        return 0.0
    return sum(1 for r in fresh.values() if r.get("status") != "ok") / len(fresh)


def _select(candidates, cap, now):
    cutoff = now - timedelta(days=NEWS_DAYS)
    dated = []
    for it in candidates:
        d = _parse(it.get("date"))
        if d and cutoff <= d <= now:
            dated.append((d, it))
    dated.sort(key=lambda p: p[0], reverse=True)
    seen, out = set(), []
    for _, it in dated:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        out.append(it)
        if len(out) == cap:
            break
    return out


def news(watchlist, state, now):
    result, everything = {}, []
    for cat in watchlist:
        for sub in cat["subcategories"]:
            cands = []
            for feed in sub["feeds"]:
                for it in state.get(feed["url"], EMPTY_STATE)["items"]:
                    cands.append({**it, "source": feed["title"], "source_url": feed["html"]})
            result[sub["slug"]] = _select(cands, NEWS_PER_CATEGORY, now)
            everything.extend(cands)
    result["all"] = _select(everything, NEWS_ALL, now)
    return result


# The home page ticker shows cyber news only (AI Security included), in the
# page's language. General AI press and automated alert feeds are left out:
# they read as noise in a one-line headline ticker.
TICKER_CATEGORY = "threat-intelligence"
TICKER_EXCLUDED = {"alerts-and-monitoring"}
TICKER_PER_FEED = 2  # so one busy feed can't fill the ticker

_FR_WORDS = set("le la les des du une un pour est et dans sur avec par au aux pas qui que ses son sa ce cette plus".split())
_EN_WORDS = set("the of and to for in on with is are from by how what new your this at".split())


def feed_language(items):
    """"fr" or "en", guessed from the item titles (feeds don't declare it reliably)."""
    fr = en = 0
    for it in items:
        title = (it.get("title") or "").lower()
        words = re.findall(r"[a-zà-ÿ]+", title)
        fr += sum(w in _FR_WORDS for w in words) + 2 * len(re.findall(r"[éèêàçù]", title))
        en += sum(w in _EN_WORDS for w in words)
    return "fr" if fr > en else "en"


def ticker(watchlist, state, now, lang, cap):
    """The newest articles of the cyber feeds written in `lang`, at most
    TICKER_PER_FEED per feed, newest first."""
    cands = []
    for cat in watchlist:
        for sub in cat["subcategories"]:
            if cat["slug"] != TICKER_CATEGORY or sub["slug"] in TICKER_EXCLUDED:
                continue
            for feed in sub["feeds"]:
                items = state.get(feed["url"], EMPTY_STATE)["items"]
                if items and feed_language(items) == lang:
                    newest = _select(items, TICKER_PER_FEED, now)
                    cands.extend({**it, "source": feed["title"], "source_url": feed["html"]} for it in newest)
    return _select(cands, cap, now)
