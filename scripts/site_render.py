"""Render the static website (English at the root, French under fr/).

Standard library only. Every piece of text that comes from the watchlist,
the descriptions or the fetched feeds is escaped with `html.escape` at render
time: titles may contain literal `<` or `&`, and must show as plain text.
All internal links are relative, so the site works under any sub-path.
"""
import hashlib
import html
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import site_data
import site_health
from build_category_opml import RAW_BASE
from changelog import norm

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
STATIC_DIR = SITE_DIR / "static"
TOOLS_FILE = SITE_DIR / "tools.json"  # RSS readers and automation tools shown on the home page
LOGO_DIR = SITE_DIR / "logos"  # their logos, from Simple Icons (CC0), inlined in the page
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

HERO_CHIPS = ("CVE", "APT", "IOC", "CERT", "LLM", "0-day")  # decorative tags around the globe
HERO_TICKER = 12  # latest articles in the hero's news ticker


def _recent_articles(ctx, days=7):
    """Number of articles of the watchlist's feeds published in the last `days` days."""
    since = ctx["now"] - timedelta(days=days)
    n = 0
    for cat in ctx["watchlist"]:
        for sub in cat["subcategories"]:
            for feed in sub["feeds"]:
                for it in (ctx["state"].get(feed["url"]) or site_data.EMPTY_STATE)["items"]:
                    dt = site_data._parse(it.get("date"))
                    n += bool(dt and since <= dt <= ctx["now"])
    return n


def _up_share(health):
    """Share of the feeds checked at the last build that worked, as a percentage; None without data."""
    last = [days[-1] for days in health.get("feeds", {}).values() if days and days[-1] in "oif"]
    return round(100 * sum(c != "f" for c in last) / len(last)) if last else None


def _hero(ctx, feeds, subs):
    s, lang_root = ctx["s"], ctx["lang_root"]
    lead = e(s["hero_lead"]).replace("{feeds}", str(feeds)).replace("{categories}", str(subs))
    stats = [(feeds, s["stat_feeds"]), (subs, s["stat_categories"]),
             (_recent_articles(ctx), s["stat_articles"])]
    up = _up_share(ctx["health"])
    if up is not None:
        stats.append((f"{up}%", s["stat_up"]))
    stat_html = "".join(f'<div><dt>{e(label)}</dt><dd>{e(value)}</dd></div>' for value, label in stats)
    chips = "".join(f"<li>{e(c)}</li>" for c in HERO_CHIPS)
    ticker = ""
    rows = site_data.ticker(ctx["watchlist"], ctx["state"], ctx["now"], ctx["lang"], HERO_TICKER)
    if rows:
        lis = "".join(f'<li>{_link(it.get("link"), it.get("title") or it.get("link"))}'
                      f' <span class="src">{e(it["source"])}</span></li>' for it in rows)
        ticker = f"""
  <div class="intel-ticker">
    <a class="label" href="{e(lang_root)}news/"><span class="pulse"></span>{e(s["hero_ticker"])}</a>
    <div class="track"><ul>{lis}</ul><ul aria-hidden="true">{lis.replace("<a ", '<a tabindex="-1" ')}</ul></div>
  </div>"""
    built = ctx["now"].isoformat()
    return f"""
<section class="intel" aria-labelledby="intel-title">
  <div class="intel-sky" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
  <canvas class="intel-globe" aria-hidden="true"></canvas>
  <ul class="intel-chips" aria-hidden="true">{chips}</ul>
  <div class="intel-copy">
    <p class="intel-pill"><span class="pulse"></span>{e(s["hero_pill"])} <time datetime="{e(built)}">{e(_short(built))}</time></p>
    <h1 id="intel-title"><span>{e(s["hero_title_1"])}</span> <span>{e(s["hero_title_2"])}</span></h1>
    <p class="intel-lead">{lead}</p>
    <p class="intel-cta"><a class="cta primary" href="{e(lang_root)}catalogue/">{e(s["hero_cta"])} <span aria-hidden="true">→</span></a>
    <a class="cta ghost" href="{e(lang_root)}news/">{e(s["hero_signals"])}</a></p>
    <dl class="intel-stats">{stat_html}</dl>
  </div>{ticker}
</section>"""


def _rich(text):
    """Escape `text`, then turn **menu names** into <strong>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", e(text))


def _logo(tool):
    svg = (LOGO_DIR / f"{tool['id']}.svg").read_text(encoding="utf-8").strip()
    return svg.replace("<svg ", f'<svg aria-hidden="true" focusable="false" fill="{e(tool["color"])}" ', 1)


def _tool_card(tool, ctx):
    s, lang = ctx["s"], ctx["lang"]
    steps = "".join(f"<li>{_rich(step)}</li>" for step in tool["steps"][lang])
    note = tool.get("note", {}).get(lang)
    note = f'\n    <p class="note">{_rich(note)}</p>' if note else ""
    return f"""  <article class="tool">
    <header><span class="logo">{_logo(tool)}</span><div><h4>{e(tool["name"])}</h4><p class="kind">{e(tool["kind"][lang])}</p></div></header>
    <ol>{steps}</ol>{note}
    <p class="docs">{_link(tool["docs"], s["tools_docs"])} <span aria-hidden="true">↗</span></p>
  </article>"""


def _workflow(ctx):
    s = ctx["s"]
    points = "".join(f'<div><h3>{e(s[f"workflow_{i}_title"])}</h3><p>{e(s[f"workflow_{i}_text"])}</p></div>'
                     for i in (1, 2, 3))
    return f"""<section class="workflow" aria-labelledby="workflow">
  <h2 id="workflow">{e(s["workflow_title"])}</h2>
  <p class="lead">{e(s["workflow_intro"])}</p>
  <div class="points">{points}</div>
</section>"""


def _tools(ctx):
    s = ctx["s"]
    tools = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    groups = []
    for key in ("readers", "automation"):
        cards = "\n".join(_tool_card(t, ctx) for t in tools[key])
        groups.append(f"""<h3>{e(s[f"tools_{key}"])}</h3>
<p class="group-intro">{e(s[f"tools_{key}_text"])}</p>
<div class="tools">
{cards}
</div>""")
    return f"""<section class="howto" aria-labelledby="tools">
  <h2 id="tools">{e(s["tools_title"])}</h2>
  <p class="lead">{e(s["tools_intro"])}</p>
  {"".join(groups)}
  <p class="credits">{e(s["tools_credits"])}</p>
</section>"""


def page_home(ctx):
    s, root = ctx["s"], ctx["root"]
    feeds = sum(len(sub["feeds"]) for cat in ctx["watchlist"] for sub in cat["subcategories"])
    subs = sum(len(cat["subcategories"]) for cat in ctx["watchlist"])
    raw = f"{RAW_BASE}/{WATCHLIST_FILE}"
    lang_root = ctx["lang_root"]
    return f"""{_hero(ctx, feeds, subs)}
<p class="lead intro">{e(s["home_intro"])}</p>
{_workflow(ctx)}
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
</section>
{_tools(ctx)}
<p><a href="{e(lang_root)}news/">{e(s["home_news"])}</a></p>
"""


def _card(feed, cat, sub, ctx):
    s, lang, desc = ctx["s"], ctx["lang"], ctx["descriptions"]
    url = feed["url"]
    entry = desc.get("feeds", {}).get(url) or {}
    search = " ".join(filter(None, [feed["title"], entry.get("en"), entry.get("fr"),
                                    cat["name"], sub["name"]])).lower()
    st = ctx["state"].get(url) or site_data.EMPTY_STATE
    badge = f' <span class="badge">{e(s["badge_new"])}</span>' if norm(url) in ctx["new_feeds"] else ""
    if site_health.unstable(ctx["health"].get("feeds", {}).get(url, "")):
        badge += (f' <a class="badge unstable" href="{e(ctx["lang_root"])}health/#{feed_anchor(url)}"'
                  f' title="{e(s["badge_unstable_title"])}">{e(s["badge_unstable"])}</a>')
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
                f'    <li lang="{e(it["lang"])}">{_link(it.get("link"), it.get("title") or it.get("link"), "title")}'
                f' <span class="meta">{_link(it.get("source_url"), it["source"], "source")}'
                f' {_time(it.get("date"), _short(it.get("date")))}</span></li>'
                for it in rows)
            body = (f'<ul class="news">\n{lis}\n  </ul>\n'
                    f'  <p class="empty lang-empty" hidden>{e(s["news_lang_empty"])}</p>')
        else:
            body = f'<p class="empty">{e(s["news_empty"])}</p>'
        sections.append(f'<section id="{e(slug)}" class="tab">\n  <h2>{e(name)}</h2>\n  {body}\n</section>')
    return f"""
<h1>{e(s["title_news"])}</h1>
<p class="lead">{e(s["news_intro"])}</p>
<fieldset class="lang-filter" hidden>
  <legend>{e(s["news_lang"])}</legend>
  <label><input type="radio" name="news-lang" value="" checked> {e(s["news_lang_all"])}</label>
  <label lang="fr"><input type="radio" name="news-lang" value="fr"> Français</label>
  <label lang="en"><input type="radio" name="news-lang" value="en"> English</label>
</fieldset>
<nav class="tabs" aria-labelledby="news-tabs-label"><span class="filter-label" id="news-tabs-label">{e(s["news_tabs"])}</span><ul>{bar}</ul></nav>
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


def feed_anchor(url):
    """Stable id of a feed's row on the Health page."""
    return "h-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]


def _percent(ratio):
    return "—" if ratio is None else f"{ratio * 100:.0f}%"


def _health_row(row, dates, s, tag=""):
    feed, sub, days, error = row["feed"], row["sub"], row["days"], row["error"]
    cells = "".join(f'<i class="d-{e(c)}" title="{e(d.isoformat())} · {e(s["health_state_" + c])}"></i>'
                    for c, d in zip(days, dates))
    err = ""
    if error:
        when = _time(error.get("date"))
        err = (f'<p class="error"><span class="label">{e(s["health_last_error"])}</span> '
               f'{e(error.get("error"))}{" (" + when + ")" if when else ""}</p>')
    ratio = site_health.availability(days)[0]
    cell = f'<span class="tag">{e(tag)}</span>' if tag else e(_percent(ratio))
    return (f'    <tr id="{feed_anchor(feed["url"])}" data-cat="{e(sub["slug"])}">\n'
            f'      <th scope="row">{_link(feed["html"] or feed["url"], feed["title"])}'
            f' <span class="folder">{e(sub["name"])}</span>{err}</th>\n'
            f'      <td><span class="cells" aria-hidden="true">{cells}</span></td>\n'
            f'      <td class="avail">{cell}</td>\n    </tr>')


def _health_table(rows, dates, s, tag=""):
    body = "\n".join(_health_row(r, dates, s, tag) for r in rows)
    return (f'<div class="health-scroll"><table class="health">\n  <thead><tr>'
            f'<th scope="col">{e(s["health_col_feed"])}</th><th scope="col">{e(s["health_col_days"])}</th>'
            f'<th scope="col">{e(s["health_col_availability"])}</th></tr></thead>\n'
            f'  <tbody>\n{body}\n  </tbody>\n</table></div>')


def page_health(ctx):
    s, health = ctx["s"], ctx["health"]
    dates = site_health.day_dates(health)
    head = f'<h1>{e(s["title_health"])}</h1>\n<p class="lead">{e(s["health_intro"])}</p>\n'
    if not dates or not health.get("feeds"):
        return head + f'<p class="empty">{e(s["health_empty"])}</p>\n'
    groups = {"incident": [], "collection": [], "clean": []}
    for cat in ctx["watchlist"]:
        for sub in cat["subcategories"]:
            for feed in sub["feeds"]:
                days = health["feeds"].get(feed["url"]) or "-" * len(dates)
                group = site_health.summary(days)
                row = {"feed": feed, "sub": sub, "days": days,
                       "error": (health.get("errors") or {}).get(feed["url"])}
                groups["clean" if group == "empty" else group].append(row)
    groups["incident"].sort(key=lambda r: (site_health.availability(r["days"])[0], r["feed"]["title"].lower()))
    for key in ("collection", "clean"):
        groups[key].sort(key=lambda r: r["feed"]["title"].lower())

    legend = "".join(f'<li><i class="d-{c}"></i> {e(s["health_state_" + c])}</li>' for c in "oifc-")
    options = "".join(f'<option value="{e(sub["slug"])}">{e(sub["name"])}</option>'
                      for cat in ctx["watchlist"] for sub in cat["subcategories"])
    since = e(s["health_since"].replace("{date}", str(health.get("since") or "")))  # absolute on purpose
    incidents = (_health_table(groups["incident"], dates, s) if groups["incident"]
                 else f'<p class="empty">{e(s["health_incidents_none"])}</p>')
    parts = [head, f'<p class="since">{since}</p>\n<ul class="legend">{legend}</ul>\n',
             f'<p class="health-filter" hidden><label for="health-cat">{e(s["health_filter"])}</label> '
             f'<select id="health-cat"><option value="">{e(s["health_filter_all"])}</option>{options}</select></p>\n',
             f'<section class="health-group">\n<h2>{e(s["health_incidents"])}</h2>\n{incidents}\n</section>\n']
    if groups["collection"]:
        parts.append(f'<details class="health-group">\n<summary>'
                     f'{e(plural(s, "health_collection", len(groups["collection"])))}</summary>\n'
                     f'{_health_table(groups["collection"], dates, s, s["health_collection_tag"])}\n</details>\n')
    if groups["clean"]:
        lis = "\n".join(
            f'  <li id="{feed_anchor(r["feed"]["url"])}" data-cat="{e(r["sub"]["slug"])}">'
            f'{_link(r["feed"]["html"] or r["feed"]["url"], r["feed"]["title"])}'
            f' <span class="folder">{e(r["sub"]["name"])}</span></li>' for r in groups["clean"])
        parts.append(f'<details class="health-group">\n<summary>'
                     f'{e(plural(s, "health_clean", len(groups["clean"])))}</summary>\n'
                     f'<ul class="clean">\n{lis}\n</ul>\n</details>\n')
    return "".join(parts)


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
    ("health", "health/", "title_health", page_health),
]


# The logo mark: a small globe whose meridians turn, with one live signal.
MARK = ('<svg class="mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">'
        '<defs><linearGradient id="mark-tint" x1="0" x2="1">'
        '<stop offset="0" stop-color="#22e3ff"/><stop offset="1" stop-color="#9d7bff"/></linearGradient></defs>'
        '<g fill="none" stroke="url(#mark-tint)" stroke-width="1.6">'
        '<circle cx="16" cy="16" r="13"/><ellipse cx="16" cy="16" rx="13" ry="4.5"/>'
        '<ellipse class="meridian" cx="16" cy="16" rx="13" ry="13"/>'
        '<ellipse class="meridian late" cx="16" cy="16" rx="13" ry="13"/></g>'
        '<circle class="signal" cx="23" cy="9" r="2.2" fill="#ff3d71"/></svg>')


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
    # Every page but home opens on a night band with a slice of the home globe,
    # carrying the page's own <h1> (moved out of the body).
    band = ""
    heading = re.match(r"\s*<h1>.*?</h1>", body, re.S)
    if key != "home" and heading:
        body = body[heading.end():]
        band = f"""<div class="band">
  <canvas class="band-globe" aria-hidden="true"></canvas>
  <div class="wrap">
    <p class="intel-pill"><span class="pulse"></span>{e(s["hero_pill"])} <time datetime="{e(built)}">{e(_short(built))}</time></p>
    {heading.group().strip()}
  </div>
</div>
"""
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
    <a class="brand" href="{e(ctx["lang_root"])}">{MARK}{e(s["site_name"])}</a>
    <nav aria-label="{e(s["nav_label"])}"><ul>{nav}</ul></nav>
    <div class="extra">
      <a lang="{other}" hreflang="{other}" href="{e(switch)}">{e(s["lang_switch"])}</a>
      <a href="{REPO_URL}" rel="noopener">{e(s["github"])}</a>
    </div>
  </div>
</header>
<main id="content">
{band}<div class="wrap">
{body}
</div>
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
