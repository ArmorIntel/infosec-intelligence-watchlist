#!/usr/bin/env python3
"""Write a Markdown changelog of the watchlist between two git revisions.

Lists the feeds added, removed and moved to another folder. Feeds are matched
by URL (scheme, "www." and trailing slash ignored); a feed whose URL changed
appears as removed + added.

Usage:
    python3 scripts/changelog.py --from 2026.10 --to HEAD
"""
import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

FILE = "infosec-intelligence-watchlist.xml"


def norm(url):
    url = re.sub(r"^https?://", "", url.strip().lower())
    return re.sub(r"^www\.", "", url).rstrip("/")


def feeds_at(rev):
    """Return {normalised url: (title, folder)} for the watchlist at a revision."""
    try:
        data = subprocess.run(["git", "show", f"{rev}:{FILE}"], check=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return {}
    return parse_feeds(data)


def parse_feeds(data):
    """Return {normalised url: (title, folder)} for the watchlist XML `data`."""
    feeds = {}

    def walk(node, path):
        for o in node.findall("outline"):
            name = o.get("title") or o.get("text")
            if o.get("xmlUrl"):
                feeds[norm(o.get("xmlUrl"))] = (name, " > ".join(path))
            else:
                walk(o, path + [name])

    walk(ET.fromstring(data).find("body"), [])
    return feeds


def diff_feeds(old, new):
    """Compare two `feeds_at` results.

    Returns {"added": [new key], "removed": [old key], "moved": [(old key, new key)],
    "updated": [(old key, new key)]}. A feed whose URL changed but kept its title (or,
    failing that, the only old and new feed on the same host) is an URL update, not a
    removal + addition; it is also "moved" when its folder changed.
    """
    gone, fresh = old.keys() - new.keys(), new.keys() - old.keys()
    by_title = {}
    # sorted iterations: the pairing must not depend on set order (hash seed)
    for u in sorted(fresh):
        by_title.setdefault(new[u][0].casefold(), []).append(u)
    url_changed = {}
    for u in sorted(gone):
        candidates = by_title.get(old[u][0].casefold(), [])
        if len(candidates) == 1:
            url_changed[u] = candidates.pop()
    gone -= url_changed.keys()
    fresh -= set(url_changed.values())
    # second pass: same website, only one candidate on each side
    host = lambda u: u.split("/")[0]  # noqa: E731
    for h in sorted({host(u) for u in gone}):
        olds = [u for u in gone if host(u) == h]
        news = [u for u in fresh if host(u) == h]
        if len(olds) == 1 and len(news) == 1:
            url_changed[olds[0]] = news[0]
            gone.discard(olds[0])
            fresh.discard(news[0])
    pairs = [(u, u) for u in new.keys() & old.keys()] + list(url_changed.items())
    return {
        "added": sorted(fresh),
        "removed": sorted(gone),
        "moved": [(o, n) for o, n in pairs if old[o][1] != new[n][1]],
        "updated": list(url_changed.items()),
    }


def section(title, rows):
    if not rows:
        return []
    out = ["", f"### {title} ({len(rows)})", ""]
    current = None
    for folder, line in sorted(rows, key=lambda r: (r[0], r[1].casefold())):
        if folder != current:
            out.append(f"**{folder}**")
            current = folder
        out.append(f"- {line}")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="since", required=True, help="previous revision (tag, commit)")
    p.add_argument("--to", dest="until", default="HEAD")
    args = p.parse_args()

    old, new = feeds_at(args.since), feeds_at(args.until)
    if not new:
        sys.exit(f"{FILE} not found at {args.until}")
    d = diff_feeds(old, new)
    added = [(new[u][1], new[u][0]) for u in d["added"]]
    removed = [(old[u][1], old[u][0]) for u in d["removed"]]
    moved = [(new[n][1], f"{new[n][0]} (from {old[o][1]})") for o, n in d["moved"]]
    updated = [(new[n][1], new[n][0]) for o, n in d["updated"]]

    lines = [f"Watchlist changes since `{args.since}`: **{len(old)} → {len(new)} feeds** "
             f"({len(added)} added, {len(removed)} removed, {len(moved)} moved, {len(updated)} URL updates)."]
    lines += section("Added", added)
    lines += section("Removed", removed)
    lines += section("Moved to another folder", moved)
    lines += section("Feed URL updated", updated)
    if not (added or removed or moved or updated):
        lines += ["", "No feed added, removed or moved."]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
