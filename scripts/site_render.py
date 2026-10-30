"""Render the static website (English at the root, French under fr/).

Standard library only. Every piece of text that comes from the watchlist,
the descriptions or the fetched feeds is escaped with `html.escape` at render
time: titles may contain literal `<` or `&`, and must show as plain text.
All internal links are relative, so the site works under any sub-path.
"""
import html
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import site_data
from build_category_opml import RAW_BASE
from changelog import norm

STATIC_DIR = Path(__file__).resolve().parent.parent / "site" / "static"
WATCHLIST_FILE = "infosec-intelligence-watchlist.xml"
REPO_URL = "https://github.com/ArmorIntel/infosec-intelligence-watchlist"
CREDIT_URL = "https://github.com/ArmorIntel"
LANGS = ("en", "fr")
LANG_PREFIX = {"en": "", "fr": "fr/"}
NEW_DAYS = 30  # feeds added more recently than this get a "New" badge


def e(value):
    """Escape text for element content and quoted attribute values."""
    return html.escape("" if value is None else str(value), quote=True)


def safe_url(url):
    """Return the URL if it is http(s), else None (drops javascript: and the like)."""
    if not url:
        return None
    try:
        scheme = urlsplit(str(url).strip()).scheme.lower()
    except ValueError:
        return None
    return str(url).strip() if scheme in ("http", "https") else None


def plural(s, key, n):
    """The `key` string of `s` for count `n`: `key_one` when n is 1, else `key` with {n} filled in."""
    return s[key + "_one"] if n == 1 else s[key].replace("{n}", str(n))


def format_rate(rate, s):
    """Rate is in posts per week, as computed by feed_items.posting_rate; `s`: strings of one language."""
    if rate is None:
        return ""
    if rate >= 1:
        return plural(s, "rate_week", round(rate))
    per_month = rate * 30 / 7
    if per_month >= 1:
        return plural(s, "rate_month", round(per_month))
    return s["rate_rare"]


def load_strings(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _time(value, text=None):
    """`<time>` for an ISO date, or "" when the date is missing or unparsable."""
    dt = site_data._parse(value)
    if dt is None:
        return ""
    label = text or dt.strftime("%Y-%m-%d")
    return f'<time datetime="{e(value)}">{e(label)}</time>'


def _link(url, text, cls=""):
    url = safe_url(url)
    attr = f' class="{cls}"' if cls else ""
    if url is None:
        return f"<span{attr}>{e(text)}</span>"
    return f'<a{attr} href="{e(url)}" rel="noopener">{e(text)}</a>'


def _copy_button(value, label, s):
    return (f'<button type="button" class="btn copy" data-copy="{e(value)}" '
            f'data-copied="{e(s["copied"])}" data-failed="{e(s["copy_failed"])}">{e(label)}</button>')


def _desc(descriptions, group, key, lang):
    return (descriptions.get(group, {}).get(key) or {}).get(lang) or ""


# --- pages ---------------------------------------------------------------

def page_home(ctx):
    s, root = ctx["s"], ctx["root"]
    feeds = sum(len(sub["feeds"]) for cat in ctx["watchlist"] for sub in cat["subcategories"])
    subs = sum(len(cat["subcategories"]) for cat in ctx["watchlist"])
    counts = e(s["home_counts"]).replace("{feeds}", f"<strong>{feeds}</strong>").replace(
        "{categories}", f"<strong>{subs}</strong>")
    raw = f"{RAW_BASE}/{WATCHLIST_FILE}"
    lang_root = ctx["lang_root"]
    return f"""
<section class="hero">
  <h1>{e(s["title_home"])}</h1>
  <p class="lead">{e(s["home_intro"])}</p>
  <p class="counts">{counts}</p>
</section>
<section aria-labelledby="subscribe">
  <h2 id="subscribe">{e(s["home_subscribe"])}</h2>
  <div class="ways">
    <div class="way">
      <h3>{e(s["home_all_title"])}</h3>
      <p>{e(s["home_all_text"])}</p>
      <p class="actions"><a class="btn primary" href="{e(root + WATCHLIST_FILE)}" download>{e(s["download_all"])}</a>
      {_copy_button(raw, s["copy_raw"], s)}</p>
      <p class="url"><code>{e(raw)}</code></p>
    </div>
    <div class="way">
      <h3>{e(s["home_category_title"])}</h3>
      <p>{e(s["home_category_text"])}</p>
      <p class="actions"><a class="btn" href="{e(lang_root)}catalogue/">{e(s["home_browse"])}</a></p>
    </div>
    <div class="way">
      <h3>{e(s["home_feed_title"])}</h3>
      <p>{e(s["home_feed_text"])}</p>
      <p class="actions"><a class="btn" href="{e(lang_root)}catalogue/">{e(s["home_browse"])}</a></p>
    </div>
  </div>
  <p class="tip">{e(s["home_tip"])}</p>
  <p><a href="{e(lang_root)}news/">{e(s["home_news"])}</a></p>
</section>
"""


def _card(feed, cat, sub, ctx):
    s, lang, desc = ctx["s"], ctx["lang"], ctx["descriptions"]
    url = feed["url"]
    entry = desc.get("feeds", {}).get(url) or {}
    search = " ".join(filter(None, [feed["title"], entry.get("en"), entry.get("fr"),
                                    cat["name"], sub["name"]])).lower()
    st = ctx["state"].get(url) or site_data.EMPTY_STATE
    badge = f' <span class="badge">{e(s["badge_new"])}</span>' if norm(url) in ctx["new_feeds"] else ""
    parts = [f'<h3>{_link(feed["html"], feed["title"])}{badge}</h3>']
    text = entry.get(lang) or ""
    if text:
        parts.append(f'<p class="desc">{e(text)}</p>')
    latest = st.get("latest")
    if latest and latest.get("title"):
        when = _time(latest.get("date"))
        parts.append(f'<p class="latest"><span class="label">{e(s["latest"])}</span> '
                     f'{_link(latest.get("link"), latest["title"])}{" " + when if when else ""}</p>')
    rate = format_rate(st.get("rate"), s)
    if rate:
        parts.append(f'<p class="rate">{e(rate)}</p>')
    parts.append(f'<p class="url"><code>{e(url)}</code></p>')
    q = quote(url, safe="")
    parts.append(
        '<p class="actions">'
        f'{_copy_button(url, s["copy_rss"], s)} '
        f'<a class="btn" href="https://www.inoreader.com/?add_feed={e(q)}" rel="noopener">{e(s["add_inoreader"])}</a> '
        f'<a class="btn" href="https://feedly.com/i/subscription/feed/{e(q)}" rel="noopener">{e(s["add_feedly"])}</a>'
        '</p>')
    body = "\n    ".join(parts)
    return f'  <article class="card" data-search="{e(search)}">\n    {body}\n  </article>'


def page_catalogue(ctx):
    s, root, lang = ctx["s"], ctx["root"], ctx["lang"]
    side, sections = [], []
    for cat in ctx["watchlist"]:
        links = "".join(
            f'<li><a href="#{e(sub["slug"])}">{e(sub["name"])} '
            f'<span class="count">{e(plural(s, "feeds_count", len(sub["feeds"])))}</span></a></li>'
            for sub in cat["subcategories"])
        side.append(f'<h3>{e(cat["name"])}</h3>\n<ul>{links}</ul>')
        for sub in cat["subcategories"]:
            text = _desc(ctx["descriptions"], "categories", sub["slug"], lang)
            desc = f'<p class="desc">{e(text)}</p>' if text else ""
            cards = "\n".join(_card(f, cat, sub, ctx) for f in sub["feeds"])
            sections.append(f"""<section id="{e(sub["slug"])}" class="category">
  <p class="parent">{e(cat["name"])}</p>
  <h2>{e(sub["name"])}</h2>
  {desc}
  <p class="actions"><a class="btn primary" href="{e(root + sub["opml"])}" download>{e(s["download_opml"])}</a>
  {_copy_button(f'{RAW_BASE}/{sub["opml"]}', s["copy_opml"], s)}</p>
  <div class="cards">
{cards}
  </div>
</section>""")
    return f"""
<h1>{e(s["title_catalogue"])}</h1>
<div class="layout">
  <nav class="sidebar" aria-label="{e(s["categories"])}">
    {"".join(side)}
  </nav>
  <div class="main">
    <div class="search" hidden>
      <label for="search">{e(s["search_label"])}</label>
      <input type="search" id="search" placeholder="{e(s["search_placeholder"])}" autocomplete="off">
      <p class="search-empty" hidden>{e(s["search_empty"])}</p>
    </div>
    {"".join(sections)}
  </div>
</div>
"""


def page_news(ctx):
    s = ctx["s"]
    items = site_data.news(ctx["watchlist"], ctx["state"], ctx["now"])
    tabs = [("all", s["news_all"])] + [
        (sub["slug"], sub["name"]) for cat in ctx["watchlist"] for sub in cat["subcategories"]]
    bar = "".join(f'<li><a href="#{e(slug)}">{e(name)}</a></li>' for slug, name in tabs)
    sections = []
    for slug, name in tabs:
        rows = items.get(slug) or []
        if rows:
            lis = "\n".join(
                f'    <li>{_link(it.get("link"), it.get("title") or it.get("link"), "title")}'
                f' <span class="meta">{_link(it.get("source_url"), it["source"], "source")}'
                f' {_time(it.get("date"), _short(it.get("date")))}</span></li>'
                for it in rows)
            body = f'<ul class="news">\n{lis}\n  </ul>'
        else:
            body = f'<p class="empty">{e(s["news_empty"])}</p>'
        sections.append(f'<section id="{e(slug)}" class="tab">\n  <h2>{e(name)}</h2>\n  {body}\n</section>')
    return f"""
<h1>{e(s["title_news"])}</h1>
<p class="lead">{e(s["news_intro"])}</p>
<nav class="tabs" aria-label="{e(s["news_tabs"])}"><ul>{bar}</ul></nav>
{"".join(sections)}
"""


def page_changes(ctx):
    s = ctx["s"]
    days = {}
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    # newest first by date (stable: a commit's rows keep their order), undated last
    for c in sorted(ctx["changes"], key=lambda c: site_data._parse(c.get("date")) or oldest, reverse=True):
        dt = site_data._parse(c.get("date"))
        days.setdefault(dt.astimezone(timezone.utc).strftime("%Y-%m-%d") if dt else "", []).append(c)
    sections = []
    for day, rows in days.items():
        lis = []
        for c in rows:
            kind = c.get("kind")
            parts = [f'<span class="kind kind-{e(kind)}">{e(s.get("change_" + str(kind), kind))}</span>',
                     f'<strong class="title">{e(c.get("title"))}</strong>',
                     f'<span class="folder">{e(c.get("folder"))}</span>']
            if c.get("previous_folder"):
                parts.append(f'<span class="from">{e(s["changes_from"].replace("{folder}", c["previous_folder"]))}</span>')
            if kind == "updated" and c.get("previous_url"):
                parts.append(f'<span class="urls"><code>{e(c["previous_url"])}</code> → <code>{e(c.get("url"))}</code></span>')
            elif kind == "removed" and c.get("url"):
                parts.append(f'<span class="urls"><code>{e(c["url"])}</code></span>')
            commit = str(c.get("commit") or "")
            link = (f' <a class="commit" href="{e(REPO_URL)}/commit/{e(quote(commit))}" rel="noopener">'
                    f'{e(s["changes_commit"])} <code>{e(commit[:7])}</code></a>') if commit else ""
            lis.append(f'    <li class="change">\n      <p class="what">{" ".join(parts)}</p>\n'
                       f'      <p class="reason">{e(c.get("reason"))}{link}</p>\n    </li>')
        heading = f'<time datetime="{e(day)}">{e(day)}</time>' if day else e(s["changes_undated"])
        sections.append(f'<section class="day">\n  <h2>{heading}</h2>\n  <ul class="changes">\n'
                        + "\n".join(lis) + "\n  </ul>\n</section>")
    body = "\n".join(sections) if sections else f'<p class="empty">{e(s["changes_empty"])}</p>'
    return f"""
<h1>{e(s["title_changes"])}</h1>
<p class="lead">{e(s["changes_intro"])}</p>
{body}
"""


def _short(value):
    dt = site_data._parse(value)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else None


# One entry per page: (key, path under the language root, title key, renderer).
# Adding a page = adding an entry here and its strings.
PAGES = [
    ("home", "", "title_home", page_home),
    ("catalogue", "catalogue/", "title_catalogue", page_catalogue),
    ("news", "news/", "title_news", page_news),
    ("changes", "changes/", "title_changes", page_changes),
]


def _layout(ctx, key, path, title_key, body):
    s, lang, root = ctx["s"], ctx["lang"], ctx["root"]
    other = "fr" if lang == "en" else "en"
    switch = (root + LANG_PREFIX[other] + path) or "./"
    current = ' aria-current="page"'
    nav = "".join(
        f'<li><a href="{e(ctx["lang_root"] + p)}"{current if k == key else ""}>{e(s["nav_" + k])}</a></li>'
        for k, p, _, _ in PAGES)
    first, second = (s["site_name"], s[title_key]) if key == "home" else (s[title_key], s["site_name"])
    title = f"{first} · {second}"
    built = ctx["now"].isoformat()
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(s["meta_description"])}">
<link rel="alternate" hreflang="{other}" href="{e(switch)}">
<link rel="stylesheet" href="{e(root)}static/style.css">
<script src="{e(root)}static/app.js" defer></script>
</head>
<body data-page="{e(key)}">
<a class="skip" href="#content">{e(s["skip"])}</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{e(ctx["lang_root"])}">{e(s["site_name"])}</a>
    <nav aria-label="{e(s["nav_label"])}"><ul>{nav}</ul></nav>
    <div class="extra">
      <a lang="{other}" hreflang="{other}" href="{e(switch)}">{e(s["lang_switch"])}</a>
      <a href="{REPO_URL}" rel="noopener">{e(s["github"])}</a>
    </div>
  </div>
</header>
<main id="content" class="wrap">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p>{e(s["footer_credit"])} <a href="{CREDIT_URL}" rel="noopener">ArmorIntel</a>
    · <a href="{REPO_URL}" rel="noopener">{e(s["footer_repo"])}</a></p>
    <p>{e(s["footer_built"])} <time datetime="{e(built)}">{e(_short(built))}</time></p>
  </div>
</footer>
</body>
</html>
"""


def new_feeds(changes, now):
    """Normalised URLs of the feeds added in the last NEW_DAYS days."""
    out = set()
    for c in changes:
        dt = site_data._parse(c.get("date"))
        if c.get("kind") == "added" and dt and now - dt <= timedelta(days=NEW_DAYS):
            out.add(norm(c["url"]))
    return out


def render_site(watchlist, descriptions, state, strings, out_dir: Path, now: datetime, changes=None,
                health=None) -> None:
    """`changes`: feed changes, newest first, as returned by site_changes.collect_changes.
    `health`: feed health history, as returned by site_health.record."""
    out_dir = Path(out_dir)
    changes = changes or []
    fresh = new_feeds(changes, now)
    for lang in LANGS:
        for key, path, title_key, render in PAGES:
            depth = (LANG_PREFIX[lang] + path).count("/")
            root = "../" * depth
            ctx = {
                "lang": lang, "s": strings[lang], "root": root,
                "lang_root": (root + LANG_PREFIX[lang]) or "./",
                "watchlist": watchlist, "descriptions": descriptions,
                "state": state, "now": now, "changes": changes, "new_feeds": fresh,
                "health": health or {},
            }
            target = out_dir / LANG_PREFIX[lang] / path / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_layout(ctx, key, path, title_key, render(ctx)), encoding="utf-8")
    static = out_dir / "static"
    static.mkdir(parents=True, exist_ok=True)
    for f in STATIC_DIR.iterdir():
        if f.is_file():
            shutil.copy2(f, static / f.name)
