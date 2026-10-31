#!/usr/bin/env python3
"""Prepare the pull request that adds a feed suggested by a visitor.

From the result of suggest_feed.py (status "ready"), ask the AI configured in
the environment (see suggest_ai.py) for the subcategory, title and EN/FR
descriptions, then:
- insert the feed in the watchlist, in its subcategory at its alphabetical
  place (one new line, the rest of the file untouched)
- add its descriptions to site/descriptions.json
- write the commit message (fixed text: the site's Changes page shows it),
  the pull request title and description, and the new feed URL (for
  check_feeds.py --urls-file)

When the AI is unavailable, the feed keeps its own title, goes to
FALLBACK_SUBCATEGORY and gets no description: the pull request says so.

Usage:
    python3 scripts/suggest_pr.py --result result.json --issue 12 --title-file title.txt \\
        --commit-message commit.txt --pr-body pr.md --new-urls new.txt
"""
import argparse
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_feeds  # noqa: E402
import site_data  # noqa: E402
import suggest_ai  # noqa: E402
from build_category_opml import slugify  # noqa: E402
from suggest_feed import LANGUAGES, _code, md_text  # noqa: E402

DESCRIPTIONS = Path(__file__).resolve().parent.parent / "site" / "descriptions.json"
FALLBACK_SUBCATEGORY = "security-news"
TITLE_MAX = 80
BOT_LOGINS = {"app/github-actions", "github-actions[bot]"}  # author of PRs opened with GITHUB_TOKEN


def safe_title(title):
    """Feed title fit for the OPML, the commit subject and the PR title.

    No # or @ (a "fixes #3" would close issue 3, a mention would ping someone), no control or
    invisible formatting characters (bidi overrides), one line, at most TITLE_MAX characters."""
    text = "".join(ch for ch in str(title or "") if ch not in "#@" and (ch.isspace() or unicodedata.category(ch) not in ("Cc", "Cf")))
    return " ".join(text.split())[:TITLE_MAX].strip()


def is_bot_pr(pr):
    """True for a pull request the bot opened in this repository (not from a fork, not by a person)."""
    return not pr.get("isCrossRepository") and (pr.get("author") or {}).get("login") in BOT_LOGINS


def bot_pr_for_branch(prs, branch):
    """The bot's latest pull request for a branch (gh lists newest first), or None."""
    return next((pr for pr in prs if pr.get("headRefName") == branch and is_bot_pr(pr)), None)


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def add_feed(opml_path, sub_slug, title, url, html):
    """Insert one feed line in a subcategory, at its case-insensitive alphabetical place."""
    path = Path(opml_path)
    lines = path.read_text(encoding="utf-8").split("\n")
    # folders are the <outline ...> lines that open a block (no xmlUrl, not self-closing)
    folders = [(i, _indent(l)) for i, l in enumerate(lines)
               if l.strip().startswith("<outline") and "xmlUrl=" not in l and not l.rstrip().endswith("/>")]
    if not folders:
        raise ValueError("no folder in the watchlist")
    top = min(indent for _, indent in folders)
    start = None
    for i, indent in folders:
        node = ET.fromstring(lines[i].strip() + "</outline>")
        if indent > top and slugify(node.get("title") or node.get("text") or "") == sub_slug:
            start = i
            break
    if start is None:
        raise ValueError(f"unknown subcategory: {sub_slug}")
    end = next(j for j in range(start + 1, len(lines))
               if lines[j].strip() == "</outline>" and _indent(lines[j]) == _indent(lines[start]))
    feed_indent = _indent(lines[start + 1]) if start + 1 < end else _indent(lines[start]) + 2
    at = end
    for j in range(start + 1, end):
        node = ET.fromstring(lines[j].strip())
        if (node.get("title") or node.get("text") or "").casefold() > title.casefold():
            at = j
            break
    lines.insert(at, f'{" " * feed_indent}<outline text={quoteattr(title)} title={quoteattr(title)} type="rss" '
                     f'xmlUrl={quoteattr(url)} htmlUrl={quoteattr(html)} />')
    path.write_text("\n".join(lines), encoding="utf-8")


def add_descriptions(path, url, en, fr):
    """Add a feed's descriptions, keeping the file's format (sorted keys, 2-space indent)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("feeds", {})[url] = {"en": en, "fr": fr}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def reason_line(url, author, issue):
    author = re.sub(r"[^A-Za-z0-9-]", "", author or "")  # GitHub logins: letters, digits, hyphens
    return f"- {url}: suggested by @{author} in #{issue}"


def commit_message(title, url, author, issue):
    return f"Add {title} (suggested in #{issue})\n\n{reason_line(url, author, issue)}\n"


def pr_body(result, ai, sub_name, issue):
    """Pull request description; the workflow appends the check report under "## Checks"."""
    feed = result["feed"]
    rate = f"~{feed['rate']:g} posts/week" if feed.get("rate") is not None else "unknown"
    lines = [f"Feed suggested in #{issue}, checked automatically.", "",
             "## Suggested feed", "", "| | |", "|---|---|",
             f"| Feed | {_code(feed['url'])} |",
             f"| Site | {_code(feed['site'])} |",
             f"| Latest article | {(feed.get('latest') or 'unknown')[:10]} |",
             f"| Posting rate | {rate} |",
             f"| Language | {LANGUAGES.get(feed.get('language'), 'unknown')} |"]
    for k in (result.get("same_site") or [])[:3]:
        lines += ["", f"> **Note:** this site is already followed via **{md_text(k['title'])}** "
                      f"({_code(k['url'])}) in {md_text(k['folder'])}."]
    lines += ["", "## Placement", "", f"**{md_text(sub_name)}**"]
    if ai:
        lines += ["", "## Descriptions", "",
                  "_Proposed by the AI with the subcategory: these were written by an AI, review them before merging._", "",
                  f"- **en:** {md_text(ai['description_en'], 300)}",
                  f"- **fr:** {md_text(ai['description_fr'], 300)}",
                  "", "## AI assessment", "", "_Factual summary written by the AI from the feed's latest articles: check it._",
                  "", md_text(ai["assessment"], 800)]
    else:
        lines += ["", "> **AI unavailable** (not configured, quota exhausted or invalid answer): the feed keeps its own",
                  "> title and was placed in this default subcategory. Move it if needed, and add its English and",
                  "> French descriptions to `site/descriptions.json` before merging."]
    lines += ["", "## Change", "", reason_line(feed["url"], result.get("author", ""), issue), "", f"Closes #{issue}"]
    return "\n".join(lines) + "\n"


def find_open_pr_for_url(prs, url):
    """URL of an open suggestion pull request that already adds this feed, or None."""
    for pr in prs:
        if pr.get("headRefName", "").startswith("suggestion/") and is_bot_pr(pr) \
                and f"- {url}:" in (pr.get("body") or ""):
            return pr["url"]
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--result", required=True, help="suggest_feed.py --json output, status ready")
    p.add_argument("--issue", type=int, required=True)
    p.add_argument("--title-file", required=True, help="where to write the pull request title")
    p.add_argument("--commit-message", required=True)
    p.add_argument("--pr-body", required=True)
    p.add_argument("--new-urls", required=True, help="where to write the added feed URL")
    p.add_argument("--opml", default=str(check_feeds.SOURCE))
    p.add_argument("--descriptions", default=str(DESCRIPTIONS))
    args = p.parse_args(argv)

    result = json.loads(Path(args.result).read_text(encoding="utf-8"))
    feed = result["feed"]
    watchlist = site_data.load_watchlist(args.opml)
    subs, examples = suggest_ai.catalog(watchlist, site_data.load_descriptions(args.descriptions))
    ai = suggest_ai.enrich(feed, result.get("why", ""), subs, examples, suggest_ai.config_from_env(os.environ))
    slug = ai["subcategory"] if ai else FALLBACK_SUBCATEGORY
    title = safe_title(ai["title"] if ai else feed["title"]) or safe_title(urlsplit(feed["url"]).netloc)
    sub_name = next(s["name"] for s in subs if s["slug"] == slug)

    add_feed(args.opml, slug, title, feed["url"], feed.get("site") or "")
    if ai:
        add_descriptions(args.descriptions, feed["url"], ai["description_en"], ai["description_fr"])
    Path(args.title_file).write_text(f"Add {title}\n", encoding="utf-8")
    Path(args.commit_message).write_text(commit_message(title, feed["url"], result.get("author", ""), args.issue),
                                         encoding="utf-8")
    Path(args.pr_body).write_text(pr_body(result, ai, sub_name, args.issue), encoding="utf-8")
    Path(args.new_urls).write_text(feed["url"] + "\n", encoding="utf-8")
    print(f"{title} -> {sub_name} ({'AI' if ai else 'AI unavailable'})")


if __name__ == "__main__":
    main()
