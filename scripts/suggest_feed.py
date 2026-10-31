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
- skip: nothing to do (closed issue, or already answered for this link)

Usage:
    python3 scripts/suggest_feed.py --issue issue.json --open-suggestions 0 \\
        --json result.json --comment comment.md
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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
MAX_OPEN = 5  # open suggestions per author before new ones wait
LABELS = {
    "ready": "suggestion: ready",
    "duplicate": "suggestion: duplicate",
    "no-feed": "suggestion: no-feed",
    "inactive": "suggestion: inactive",
    "needs-review": "suggestion: needs-review",
    "invalid": "suggestion: invalid",
    "limit": None,
    "skip": None,
}
LANGUAGES = {"en": "English", "fr": "French"}
MAX_SAME_SITE = 3  # "already followed" notes shown in the comment
LINK_HEADING = "Link to an article"
WHY_HEADING = "Why is it useful"
# brackets, braces and quotes end a URL: Markdown links, and no curl globbing pattern
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"'`]+")
FEED_PATH_RE = re.compile(r"(?i)feed|rss|atom|\.xml")
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
    urls = list(dict.fromkeys(u.rstrip(".,;:!?") for u in URL_RE.findall(link_text)))
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


COMMENTS_RE = re.compile(r"(?i)comment")  # also matches the French "commentaires"


class FeedLinkParser(autofix_feeds.LinkParser):
    """Feed links of a page, without comment feeds (WordPress declares one per site and one per post)."""

    def handle_starttag(self, tag, attrs):
        before = len(self.feeds)
        super().handle_starttag(tag, attrs)
        if len(self.feeds) > before and COMMENTS_RE.search(dict(attrs).get("title") or ""):
            self.feeds.pop()


def discover_feeds(url, timeout):
    """Candidate feeds for a page, most likely first: [{"url", "guess"}]."""
    status = check_feeds.fetch(url, timeout).get("status")
    if status == "ok":
        return [{"url": url, "guess": False}]
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}/"
    parent = urljoin(url, "./")
    found = []
    if status == "check" and FEED_PATH_RE.search(parts.path):
        found.append((url, False))  # probably the feed itself, blocked to scripts
    declared = []
    for page in dict.fromkeys([url, parent, root]):
        _, html = autofix_feeds.fetch_page(page, timeout)
        parser = FeedLinkParser()
        try:
            parser.feed(html)
        except Exception:
            pass
        declared += [urljoin(page, href) for href in parser.feeds]
    found += [(u, False) for u in declared]
    if not declared:
        for base in dict.fromkeys([parent, root]):
            found += [(urljoin(base, path), True) for path in autofix_feeds.COMMON_PATHS]
    seen, out = set(), []
    for candidate, guess in found:
        key = autofix_feeds.norm(candidate)
        if candidate.startswith(("http://", "https://")) and key not in seen \
                and not COMMENTS_RE.search(urlsplit(candidate).path):
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
    by_key = {}
    for k in known:
        by_key.setdefault(autofix_feeds.norm(k["url"]), k)
    result = {"status": "no-feed", "link": link, "feed": None, "alternatives": [], "existing": None,
              "same_site": [], "tried": 0}
    if autofix_feeds.norm(link) in by_key:  # a listed feed pasted as is, even if it is down today
        result.update(status="duplicate", existing=by_key[autofix_feeds.norm(link)])
        return result
    candidates = discover_feeds(link, timeout)
    with ThreadPoolExecutor(8) as ex:
        checked = list(ex.map(lambda c: check_feeds.fetch(c["url"], timeout), candidates))
    result["tried"] = len(candidates)
    rows = []
    for c, res in zip(candidates, checked):
        final = res.get("final_url") or c["url"]
        rows.append({"url": c["url"], "guess": c["guess"], "res": res,
                     "class": check_feeds.classify(res, MAX_AGE_DAYS, ABANDONED_DAYS),
                     "known": by_key.get(autofix_feeds.norm(c["url"])) or by_key.get(autofix_feeds.norm(final))})

    new_ok = [r for r in rows if r["class"] == "ok" and not r["known"]]
    if new_ok:
        # sorted() is stable: equally close feeds keep their discovery order
        new_ok = sorted(new_ok, key=lambda r: -_shared_segments(link, r["url"]))
        feed = describe(new_ok[0]["url"], timeout, now)
        # compare websites, not feed hosts: FeedBurner or Reddit host many unrelated feeds
        h = host(feed["site"])
        result.update(status="ready", feed=feed, alternatives=[r["url"] for r in new_ok[1:]],
                      same_site=[k for k in known if h and h == host(k.get("html"))])
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


def answered_link(comment):
    """The link a previous bot answer was for, or None (no answer, or one that must not block a new check)."""
    m = re.search(r"<!-- link: (\S*) -->", comment or "")
    return m.group(1) if m else None


def run(issue, last_comment, open_suggestions, known, timeout, now, force=False):
    """Result for one issue, as written to --json (`issue`: gh issue view --json body,author,state).

    `last_comment`: the bot's previous answer on the issue, if any. Nothing is done when it was for the
    same link (an edit of the title or of the "why" field), unless `force` (a manual run)."""
    link, why = parse_issue(issue.get("body"))
    author = (issue.get("author") or {}).get("login", "")
    base = {"link": link, "why": why, "author": author}
    if (issue.get("state") or "").upper() == "CLOSED":
        return {**base, "status": "skip"}
    if not force and link and answered_link(last_comment) == link:
        return {**base, "status": "skip"}
    if not link:
        return {**base, "status": "invalid"}
    if open_suggestions > MAX_OPEN:
        return {**base, "status": "limit"}
    return {**analyse(link, known, timeout, now), **base}


def _code(url):
    return "`" + " ".join(str(url or "").replace("`", "").split()) + "`"


def render_comment(result, author, pr_url=None, pr_existing=False):
    """Markdown answer posted on the issue; every value from a feed goes through md_text.

    `pr_url`: the pull request prepared for a ready feed, or (`pr_existing`) one that already adds it."""
    status, feed = result["status"], result.get("feed") or {}
    who = "@" + re.sub(r"[^A-Za-z0-9-]", "", author or "")  # GitHub logins: letters, digits, hyphens
    lines = [MARKER]
    if status != "limit":  # a limited suggestion is checked on its next edit
        lines.append(f"<!-- link: {result.get('link') or ''} -->")
    if status == "ready":
        rate = f"~{feed['rate']:g} posts/week" if feed.get("rate") is not None else "unknown"
        lines += [f"**Feed found**, thanks {who}!", "", "| | |", "|---|---|",
                  f"| Feed | {_code(feed['url'])} |",
                  f"| Title | {md_text(feed['title'])} |",
                  f"| Site | {_code(feed['site'])} |",
                  f"| Latest article | {(feed.get('latest') or 'unknown')[:10]} |",
                  f"| Posting rate | {rate} |",
                  f"| Language | {LANGUAGES.get(feed.get('language'), 'unknown')} |"]
        if feed.get("samples"):
            lines += ["", "Recent articles:"] + [f"- {md_text(title)}" for title in feed["samples"][:5]]
        same_site = result.get("same_site") or []
        for k in same_site[:MAX_SAME_SITE]:
            lines += ["", f"> **Note:** this site is already followed via **{md_text(k['title'])}** "
                          f"({_code(k['url'])}) in {md_text(k['folder'])}."]
        if len(same_site) > MAX_SAME_SITE:
            lines += ["", f"> And {len(same_site) - MAX_SAME_SITE} more feeds of this site."]
        if result.get("alternatives"):
            lines += ["", "Other feeds found on this site: " + ", ".join(_code(u) for u in result["alternatives"])]
        if pr_url and pr_existing:
            lines += ["", f"This feed is already proposed in {_code(pr_url).strip('`')}.", "",
                      "_Ce flux est déjà proposé dans une autre pull request._"]
        elif pr_url:
            lines += ["", f"Next: the maintainer reviews the pull request {_code(pr_url).strip('`')} "
                          "before the feed is added.", "",
                      "_Flux trouvé : le mainteneur relit la pull request avant de l'ajouter._"]
        else:
            lines += ["", "Next: the maintainer reviews this suggestion before adding it.", "",
                      "_Flux trouvé : le mainteneur relit la proposition avant de l'ajouter._"]
    elif status == "duplicate":
        k = result["existing"]
        lines += [f"**Already in the watchlist**: **{md_text(k['title'])}** ({_code(k['url'])}) is listed in "
                  f"{md_text(k['folder'])}. Thanks {who}, closing this suggestion.", "",
                  "_Déjà dans la watchlist : merci, la proposition est close._"]
    elif status == "no-feed":
        lines += [f"**No feed found** from {_code(result['link'])} ({result.get('tried', 0)} URLs tried). "
                  "If you know the feed URL, edit this issue and paste it in the link field: the check runs again.", "",
                  "_Aucun flux trouvé : si vous connaissez l'URL du flux, modifiez l'issue pour la coller, "
                  "la vérification sera relancée._"]
    elif status == "inactive":
        lines += [f"**Feed inactive**: {_code(feed['url'])} last published on {(feed.get('latest') or 'unknown')[:10]}. "
                  "The watchlist keeps sources that published within the last 6 months.", "",
                  "_Flux inactif : la watchlist garde les sources ayant publié dans les 6 derniers mois._"]
    elif status == "needs-review":
        why = md_text(feed.get("error") or "no dated articles")
        lines += [f"**Feed found, manual check needed**: {_code(feed['url'])} ({why}). "
                  "It may still work in RSS readers: the maintainer will check it by hand.", "",
                  "_Flux trouvé mais illisible pour les scripts : le mainteneur le vérifiera à la main._"]
    elif status == "invalid":
        lines += ["**No link found**: the link field must contain one http(s) URL. "
                  "Edit this issue to fix it: the check runs again.", "",
                  "_Lien manquant ou invalide : modifiez l'issue pour le corriger, la vérification sera relancée._"]
    elif status == "limit":
        lines += [f"**Too many open suggestions**: {who} already has more than {MAX_OPEN} open suggestions, "
                  "edit this issue later to run the check again.", "",
                  "_Trop de propositions ouvertes : modifiez l'issue plus tard pour relancer la vérification._"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--issue", help="gh issue view --json body,author,state output (required unless --render)")
    p.add_argument("--last-comment-file", help="the bot's previous answer on the issue, if any")
    p.add_argument("--force", action="store_true", help="check again even if the link did not change")
    p.add_argument("--open-suggestions", type=int, default=0, help="open suggestions of the issue's author")
    p.add_argument("--json", help="where to write the result (required unless --render)")
    p.add_argument("--render", help="only write the comment for this --json result (no check)")
    p.add_argument("--pr-url", help="with --render: the pull request prepared for the feed")
    p.add_argument("--pr-existing", action="store_true", help="with --pr-url: it was opened for another issue")
    p.add_argument("--comment", required=True, help="where to write the comment (empty when skipped)")
    p.add_argument("--opml", default=str(check_feeds.SOURCE))
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    args = p.parse_args(argv)
    if args.render:
        result = json.loads(Path(args.render).read_text(encoding="utf-8"))
        Path(args.comment).write_text(render_comment(result, result.get("author", ""), args.pr_url, args.pr_existing),
                                      encoding="utf-8")
        return
    if not args.issue or not args.json:
        p.error("--issue and --json are required unless --render")

    issue = json.loads(Path(args.issue).read_text(encoding="utf-8"))
    last = Path(args.last_comment_file).read_text(encoding="utf-8") if args.last_comment_file else None
    known = check_feeds.load_feeds(args.opml)
    result = run(issue, last, args.open_suggestions, known, args.timeout, datetime.now(timezone.utc), args.force)
    Path(args.json).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    comment = "" if result["status"] == "skip" else render_comment(result, result.get("author", ""))
    Path(args.comment).write_text(comment, encoding="utf-8")
    print(f"{result['status']}: {result.get('link')}")


if __name__ == "__main__":
    main()
