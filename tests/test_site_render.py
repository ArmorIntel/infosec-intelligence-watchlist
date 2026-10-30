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


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        wl, desc, state, strings = fixture()
        site_render.render_site(wl, desc, state, strings, cls.out, NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_pages_exist(self):
        for rel in ["index.html", "catalogue/index.html", "news/index.html",
                    "fr/index.html", "fr/catalogue/index.html", "fr/news/index.html",
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

    def strings_en(self):
        return fixture()[3]["en"]

    def test_format_rate(self):
        self.assertEqual(site_render.format_rate(7.0, "en"), "~7 posts/week")
        self.assertEqual(site_render.format_rate(0.5, "en"), "~2 posts/month")
        self.assertEqual(site_render.format_rate(0.1, "en"), "Rarely updated")
        self.assertEqual(site_render.format_rate(None, "en"), "")
        self.assertEqual(site_render.format_rate(7.0, "fr"), "~7 articles/semaine")
        self.assertEqual(site_render.format_rate(0.5, "fr"), "~2 articles/mois")
        self.assertEqual(site_render.format_rate(0.1, "fr"), "Mises à jour rares")

    def test_credit_footer(self):
        for rel in ["index.html", "fr/news/index.html"]:
            html = self.page(rel)
            footer = html[html.index("<footer"):]
            self.assertIn('href="https://github.com/ArmorIntel"', footer)
            self.assertIn('href="https://github.com/ArmorIntel/infosec-intelligence-watchlist"', footer)
            self.assertIn(f'<time datetime="{NOW.isoformat()}"', footer)
        self.assertIn("Created and maintained by", self.page("index.html"))

    def test_home_counts(self):
        html = self.page("index.html")
        self.assertIn(">3<", html)  # feeds
        self.assertIn(">2<", html)  # subcategories


if __name__ == "__main__":
    unittest.main()
