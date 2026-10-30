import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import site_data  # noqa: E402
import site_render  # noqa: E402
from build_category_opml import RAW_BASE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

OPML = """<?xml version="1.0"?>
<opml version="2.0"><head><title>t</title></head><body>
  <outline text="Threat Intelligence" title="Threat Intelligence">
    <outline text="Security News" title="Security News">
      <outline type="rss" text="A" title="&lt;script&gt;alert(1)&lt;/script&gt;" xmlUrl="https://a.com/feed?x=1&amp;y=2" htmlUrl="https://a.com"/>
      <outline type="rss" text="B" title="Feed B" xmlUrl="https://b.com/feed" htmlUrl="https://b.com"/>
    </outline>
  </outline>
  <outline text="Technology Intelligence" title="Technology Intelligence">
    <outline text="AI" title="AI">
      <outline type="rss" text="C" title="Feed C" xmlUrl="https://c.com/feed" htmlUrl="https://c.com"/>
    </outline>
  </outline>
</body></opml>
"""

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
XSS = "<script>alert(1)</script>"


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def fixture():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "w.xml"
        p.write_text(OPML, encoding="utf-8")
        wl = site_data.load_watchlist(p)
    descriptions = {
        "categories": {"security-news": {"en": "News en", "fr": "Actualités fr"}},
        "feeds": {"https://b.com/feed": {"en": "Feed B covers things.", "fr": "Feed B couvre des choses."}},
    }
    art = {"title": XSS, "link": "https://a.com/1", "date": iso(1)}
    state = {
        "https://a.com/feed?x=1&y=2": {"latest": art, "items": [art], "rate": 7.0, "fetched": iso(0)},
        "https://b.com/feed": {"latest": {"title": "Undated B", "link": "https://b.com/u", "date": None},
                               "items": [], "rate": None, "fetched": iso(0)},
        "https://c.com/feed": {"latest": None, "items": [], "rate": None, "fetched": None},
    }
    strings = json.loads((ROOT / "site" / "strings.json").read_text(encoding="utf-8"))
    return wl, descriptions, state, strings


def change(kind, days_ago, url, title, reason, folder="Threat Intelligence > Security News", previous=None):
    return {"date": iso(days_ago), "commit": "0123456789abcdef", "subject": "Subject", "kind": kind,
            "title": title, "folder": folder, "previous_folder": previous, "url": url, "reason": reason}


CHANGES = [
    change("added", 10, "https://www.B.com/feed/", "Feed B", "Great " + XSS),
    change("moved", 10, "https://a.com/feed?x=1&y=2", XSS, "Better folder",
           folder="Threat Intelligence > Security News", previous="Technology Intelligence > AI"),
    change("added", 40, "https://c.com/feed", "Feed C", "Old addition"),
    change("removed", 41, "https://gone.com/feed", "Gone feed", "nothing published for 25 months"),
]


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        wl, desc, state, strings = fixture()
        site_render.render_site(wl, desc, state, strings, cls.out, NOW, changes=CHANGES)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_pages_exist(self):
        for rel in ["index.html", "catalogue/index.html", "news/index.html", "changes/index.html",
                    "fr/index.html", "fr/catalogue/index.html", "fr/news/index.html", "fr/changes/index.html",
                    "health/index.html", "fr/health/index.html",
                    "static/app.js", "static/style.css"]:
            self.assertTrue((self.out / rel).is_file(), rel)

    def test_lang_and_switch(self):
        self.assertIn('<html lang="en">', self.page("index.html"))
        self.assertIn('<html lang="fr">', self.page("fr/news/index.html"))
        cases = {
            "index.html": 'hreflang="fr" href="fr/"',
            "catalogue/index.html": 'hreflang="fr" href="../fr/catalogue/"',
            "news/index.html": 'hreflang="fr" href="../fr/news/"',
            "fr/index.html": 'hreflang="en" href="../"',
            "fr/catalogue/index.html": 'hreflang="en" href="../../catalogue/"',
            "fr/news/index.html": 'hreflang="en" href="../../news/"',
            "changes/index.html": 'hreflang="fr" href="../fr/changes/"',
            "fr/changes/index.html": 'hreflang="en" href="../../changes/"',
        }
        for rel, needle in cases.items():
            html = self.page(rel)
            self.assertIn(needle, html, rel)
            self.assertNotRegex(html, r'(href|src)="/(?!/)', rel)
        self.assertIn('href="../static/style.css"', self.page("catalogue/index.html"))
        self.assertIn('href="../../static/style.css"', self.page("fr/news/index.html"))

    def test_escaping(self):
        for rel in ["catalogue/index.html", "news/index.html", "fr/catalogue/index.html"]:
            html = self.page(rel)
            self.assertNotIn(XSS, html, rel)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html, rel)
        self.assertIn("https://a.com/feed?x=1&amp;y=2", self.page("catalogue/index.html"))

    def test_unsafe_link_scheme_dropped(self):
        wl, desc, state, strings = fixture()
        state["https://b.com/feed"]["latest"]["link"] = "javascript:alert(1)"
        with tempfile.TemporaryDirectory() as d:
            site_render.render_site(wl, desc, state, strings, Path(d), NOW)
            html = (Path(d) / "catalogue/index.html").read_text(encoding="utf-8")
        self.assertNotIn("javascript:", html)
        self.assertIn("Undated B", html)

    def test_category_names_english_on_fr(self):
        html = self.page("fr/catalogue/index.html")
        self.assertIn("Security News", html)
        self.assertIn("Threat Intelligence", html)
        self.assertIn("Actualités fr", html)
        self.assertIn("Feed B couvre des choses.", html)
        self.assertIn("Security News", self.page("fr/news/index.html"))

    def test_import_links(self):
        html = self.page("catalogue/index.html")
        self.assertIn("https://www.inoreader.com/?add_feed=https%3A%2F%2Fb.com%2Ffeed", html)
        self.assertIn("https://feedly.com/i/subscription/feed/https%3A%2F%2Fb.com%2Ffeed", html)
        self.assertIn("add_feed=https%3A%2F%2Fa.com%2Ffeed%3Fx%3D1%26y%3D2", html)
        raw = RAW_BASE + "/opml/threat-intelligence/security-news.opml"
        self.assertIn(f'data-copy="{raw}"', html)
        self.assertIn('href="../opml/threat-intelligence/security-news.opml"', html)
        self.assertIn('id="security-news"', html)
        self.assertIn('href="#security-news"', html)
        home = self.page("index.html")
        self.assertIn('href="infosec-intelligence-watchlist.xml"', home)
        self.assertIn(f'data-copy="{RAW_BASE}/infosec-intelligence-watchlist.xml"', home)

    def test_undated_latest_has_no_time(self):
        html = self.page("catalogue/index.html")
        card = html[html.index("Undated B"):]
        card = card[:card.index("</article>")]
        self.assertNotIn("<time", card)
        dated = html[html.index("https://a.com/1"):]
        dated = dated[:dated.index("</article>")]
        self.assertIn(f'<time datetime="{iso(1)}"', dated)

    def test_card_search_and_rate(self):
        html = self.page("catalogue/index.html")
        m = re.search(r'<article class="card" data-search="([^"]*)"[^>]*>(?:(?!</article>).)*Feed B', html, re.S)
        self.assertIsNotNone(m)
        self.assertIn("feed b covers things.", m.group(1))
        self.assertIn("feed b couvre des choses.", m.group(1))
        self.assertIn("security news", m.group(1))
        self.assertIn("threat intelligence", m.group(1))
        self.assertIn("~7 posts/week", html)
        self.assertIn("~7 articles/semaine", self.page("fr/catalogue/index.html"))

    def test_news(self):
        html = self.page("news/index.html")
        self.assertLess(html.index('href="#all"'), html.index('href="#security-news"'))
        self.assertLess(html.index('href="#security-news"'), html.index('href="#ai"'))
        ai = html[html.index('<section id="ai"'):]
        ai = ai[:ai.index("</section>")]
        self.assertIn(self.strings_en()["news_empty"], ai)
        self.assertIn('href="https://a.com/1"', html)

    def test_news_language_filter(self):
        html = self.page("news/index.html")
        self.assertIn('<fieldset class="lang-filter" hidden>', html)  # shown by app.js
        self.assertIn('<input type="radio" name="news-lang" value="" checked> Both', html)
        self.assertIn('<li lang="en"><a class="title" href="https://a.com/1"', html)
        self.assertIn(self.strings_en()["news_lang_empty"], html)
        self.assertIn("> Les deux</label>", self.page("fr/news/index.html"))
        self.assertIn('<span class="filter-label" id="news-tabs-label">Categories</span>', html)

    def strings_en(self):
        return fixture()[3]["en"]

    def test_format_rate(self):
        en, fr = fixture()[3]["en"], fixture()[3]["fr"]
        self.assertEqual(site_render.format_rate(7.0, en), "~7 posts/week")
        self.assertEqual(site_render.format_rate(0.5, en), "~2 posts/month")
        self.assertEqual(site_render.format_rate(0.1, en), "Rarely updated")
        self.assertEqual(site_render.format_rate(None, en), "")
        self.assertEqual(site_render.format_rate(7.0, fr), "~7 articles/semaine")
        self.assertEqual(site_render.format_rate(0.5, fr), "~2 articles/mois")
        self.assertEqual(site_render.format_rate(0.1, fr), "Mises à jour rares")

    def test_format_rate_singular(self):
        en, fr = fixture()[3]["en"], fixture()[3]["fr"]
        self.assertEqual(site_render.format_rate(1.0, en), "~1 post/week")
        self.assertEqual(site_render.format_rate(1.4, en), "~1 post/week")
        self.assertEqual(site_render.format_rate(0.3, en), "~1 post/month")
        self.assertEqual(site_render.format_rate(1.0, fr), "~1 article/semaine")
        self.assertEqual(site_render.format_rate(0.3, fr), "~1 article/mois")
        self.assertEqual(site_render.format_rate(1.6, en), "~2 posts/week")

    def test_feed_count_singular(self):
        en, fr = self.page("catalogue/index.html"), self.page("fr/catalogue/index.html")
        self.assertIn('<span class="count">1 feed</span>', en)   # AI has one feed
        self.assertIn('<span class="count">2 feeds</span>', en)  # Security News has two
        self.assertIn('<span class="count">1 flux</span>', fr)
        self.assertIn('<span class="count">2 flux</span>', fr)

    def test_credit_footer(self):
        for rel in ["index.html", "fr/news/index.html"]:
            html = self.page(rel)
            footer = html[html.index("<footer"):]
            self.assertIn('href="https://github.com/ArmorIntel"', footer)
            self.assertIn('href="https://github.com/ArmorIntel/infosec-intelligence-watchlist"', footer)
            self.assertIn(f'<time datetime="{NOW.isoformat()}"', footer)
        self.assertIn("Created and maintained by", self.page("index.html"))

    def test_changes_page(self):
        html = self.page("changes/index.html")
        self.assertNotIn(XSS, html)
        self.assertIn("Great &lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn('href="https://github.com/ArmorIntel/infosec-intelligence-watchlist/commit/0123456789abcdef"', html)
        self.assertIn("Technology Intelligence &gt; AI", html)  # previous folder of the move
        self.assertIn("nothing published for 25 months", html)
        self.assertIn('aria-current="page">Changes<', html)
        # grouped by date, newest first
        d10, d40 = iso(10)[:10], iso(40)[:10]
        self.assertEqual(html.count(f'<h2><time datetime="{d10}">'), 1)
        self.assertLess(html.index(d10), html.index(d40))
        fr = self.page("fr/changes/index.html")
        self.assertIn('<html lang="fr">', fr)
        self.assertIn("Great &lt;script&gt;alert(1)&lt;/script&gt;", fr)  # reasons as written
        self.assertIn("Threat Intelligence &gt; Security News", fr)
        self.assertIn(">Modifications<", fr)

    def render_changes(self, changes, rel="changes/index.html"):
        wl, desc, state, strings = fixture()
        with tempfile.TemporaryDirectory() as d:
            site_render.render_site(wl, desc, state, strings, Path(d), NOW, changes=changes)
            return (Path(d) / rel).read_text(encoding="utf-8")

    def test_changes_sorted_newest_first_by_date(self):
        html = self.render_changes([
            change("added", 40, "https://c.com/feed", "Old one", "r"),
            change("added", 5, "https://b.com/feed", "Recent one", "r"),
            change("removed", 20, "https://gone.com/feed", "Middle one", "r"),
        ])
        self.assertLess(html.index("Recent one"), html.index("Middle one"))
        self.assertLess(html.index("Middle one"), html.index("Old one"))
        self.assertLess(html.index(iso(5)[:10]), html.index(iso(20)[:10]))

    def test_changes_show_urls_of_updates_and_removals(self):
        updated = change("updated", 3, "https://new.com/feed?a=1&b=2", "Upd", "moved host")
        updated["previous_url"] = "https://old.com/<feed>"
        html = self.render_changes([updated, change("removed", 4, "https://gone.com/feed", "Gone", "dead")])
        self.assertIn("https://old.com/&lt;feed&gt;", html)
        self.assertIn("https://new.com/feed?a=1&amp;b=2", html)
        self.assertIn("https://gone.com/feed", html)
        self.assertLess(html.index("https://old.com/"), html.index("https://new.com/"))
        self.assertNotIn("<feed>", html)

    def test_changes_empty(self):
        wl, desc, state, strings = fixture()
        with tempfile.TemporaryDirectory() as d:
            site_render.render_site(wl, desc, state, strings, Path(d), NOW)
            html = (Path(d) / "changes/index.html").read_text(encoding="utf-8")
        self.assertIn(strings["en"]["changes_empty"], html)

    def card(self, rel, needle):
        html = self.page(rel)
        start = html.rindex("<article", 0, html.index(needle))
        return html[start:html.index("</article>", start)]

    def test_new_badge(self):
        self.assertIn('class="badge"', self.card("catalogue/index.html", "https://b.com/feed"))
        self.assertIn(">New<", self.card("catalogue/index.html", "https://b.com/feed"))
        self.assertIn(">Nouveau<", self.card("fr/catalogue/index.html", "https://b.com/feed"))
        self.assertNotIn('class="badge"', self.card("catalogue/index.html", "https://c.com/feed"))
        self.assertNotIn('class="badge"', self.card("catalogue/index.html", "https://a.com/feed?x=1&amp;y=2"))

    def test_strings_keys_match(self):
        strings = fixture()[3]
        self.assertEqual(set(strings["en"]), set(strings["fr"]))

    def test_home_counts(self):
        html = self.page("index.html")
        self.assertIn(">3<", html)  # feeds
        self.assertIn(">2<", html)  # subcategories

    def test_home_tools(self):
        html = self.page("index.html")
        self.assertIn('<h2 id="workflow">Plug it into your watch</h2>', html)
        tools = html[html.index('<section class="howto"'):]
        self.assertIn("<h4>Inoreader</h4>", tools)
        self.assertIn('<svg aria-hidden="true" focusable="false" fill="#1875F3"', tools)  # inlined logo
        self.assertIn("<strong>Add feed › Import feeds</strong>", tools)
        self.assertIn('href="https://docs.feedly.com/article/51-how-to-import-opml-into-feedly"', tools)
        self.assertIn("Documentation officielle", self.page("fr/index.html"))

    def test_tools_file_complete(self):
        tools = json.loads(site_render.TOOLS_FILE.read_text(encoding="utf-8"))
        for tool in tools["readers"] + tools["automation"]:
            self.assertTrue((site_render.LOGO_DIR / f"{tool['id']}.svg").is_file(), tool["id"])
            self.assertTrue(tool["docs"].startswith("https://"), tool["id"])
            for lang in ("en", "fr"):
                self.assertTrue(tool["kind"][lang] and tool["steps"][lang], (tool["id"], lang))
            self.assertEqual(len(tool["steps"]["en"]), len(tool["steps"]["fr"]), tool["id"])
            if "note" in tool:
                self.assertEqual(set(tool["note"]), {"en", "fr"}, tool["id"])

    def test_home_hero(self):
        html = self.page("index.html")
        s = self.strings_en()
        self.assertIn("<dt>Articles in 7 days</dt><dd>1</dd>", html)
        self.assertNotIn(s["stat_up"], html)  # no health history in this fixture
        ticker = html[html.index('class="intel-ticker"'):]
        self.assertEqual(ticker.count('href="https://a.com/1"'), 2)  # list, then its copy for the loop
        self.assertIn('<ul aria-hidden="true"><li><a tabindex="-1" href="https://a.com/1"', ticker)
        self.assertNotIn("<script>alert", ticker)
        self.assertIn(">Transformez le bruit<", self.page("fr/index.html"))


A_URL = "https://a.com/feed?x=1&y=2"
HEALTH = {
    "start": (NOW.date() - timedelta(days=89)).isoformat(),
    "since": "2026-08-01",
    "feeds": {
        A_URL: "o" * 80 + "ffffoofffo",              # unstable: 4/10 over the last days
        "https://b.com/feed": "o" * 85 + "ccccc",    # collection issues only
        "https://c.com/feed": "o" * 88 + "fo",       # one failure, still stable
    },
    "errors": {A_URL: {"date": iso(1), "error": "HTTP 500 " + XSS}},
}


class HealthRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        wl, desc, state, strings = fixture()
        cls.strings = strings
        site_render.render_site(wl, desc, state, strings, cls.out, NOW, health=HEALTH)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_pages_and_nav(self):
        html = self.page("health/index.html")
        self.assertIn('href="../health/" aria-current="page"', html)
        self.assertIn('hreflang="fr" href="../fr/health/"', html)
        self.assertIn(">Santé des flux<", self.page("fr/health/index.html"))
        self.assertIn(">Health<", self.page("index.html"))

    def test_home_up_share(self):
        # Feeds A and C worked at the last build; B's collection issue is left out.
        self.assertIn("<dt>Feeds up at last check</dt><dd>100%</dd>", self.page("index.html"))

    def test_groups_and_order(self):
        html = self.page("health/index.html")
        incidents = html[:html.index("<details")]
        self.assertLess(incidents.index("&lt;script&gt;"), incidents.index("Feed C"))  # least available first
        self.assertNotIn("Feed B", incidents)
        self.assertIn("1 feed with collection issues only", html)
        self.assertIn(">Collection issue<", html[html.index("<details"):])
        self.assertIn(">92%<", incidents)  # 83 of 90 days
        self.assertIn(">99%<", incidents)

    def test_cells_and_escaping(self):
        html = self.page("health/index.html")
        anchor = site_render.feed_anchor(A_URL)
        row = html[html.index(f'id="{anchor}"'):]
        row = row[:row.index("</tr>")]
        self.assertEqual(row.count("<i "), 90)
        self.assertIn(f'title="{iso(9)[:10]} · Failing"', row)
        self.assertIn("HTTP 500 &lt;script&gt;", row)
        self.assertNotIn(XSS, html)
        self.assertIn("2026-08-01", html)

    def test_unstable_badge(self):
        anchor = site_render.feed_anchor(A_URL)
        cat = self.page("catalogue/index.html")
        self.assertIn(f'href="../health/#{anchor}"', cat)
        self.assertEqual(cat.count("badge unstable"), 1)
        self.assertIn(">Instable<", self.page("fr/catalogue/index.html"))

    def test_empty_history(self):
        wl, desc, state, strings = fixture()
        with tempfile.TemporaryDirectory() as d:
            site_render.render_site(wl, desc, state, strings, Path(d), NOW)
            html = (Path(d) / "health/index.html").read_text(encoding="utf-8")
            cat = (Path(d) / "catalogue/index.html").read_text(encoding="utf-8")
        self.assertIn(strings["en"]["health_empty"], html)
        self.assertNotIn("badge unstable", cat)


if __name__ == "__main__":
    unittest.main()
