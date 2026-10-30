"""Shared feed fixtures (byte strings) for the test suite."""

VALID_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example feed</title>
    <link>https://example.com/</link>
    <description>Example</description>
    <item>
      <title>First</title>
      <link>https://example.com/1</link>
      <pubDate>Mon, 05 Jan 2026 10:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Second</title>
      <link>https://example.com/2</link>
      <pubDate>Tue, 06 Jan 2026 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_LINKS = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom feed</title>
  <entry>
    <title>With alternate</title>
    <link rel="self" href="/a"/>
    <link rel="alternate" href="/b"/>
    <updated>2026-01-05T10:00:00Z</updated>
  </entry>
  <entry>
    <title>Plain link</title>
    <link href="/c"/>
    <published>2026-01-06T10:00:00Z</published>
  </entry>
</feed>
"""

RDF_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com/"><title>RDF</title></channel>
  <item rdf:about="https://example.com/r1">
    <title>RDF one</title>
    <link>https://example.com/r1</link>
    <dc:date>2026-01-07T10:00:00Z</dc:date>
  </item>
  <item rdf:about="https://example.com/r2">
    <title>RDF two</title>
    <link>https://example.com/r2</link>
    <dc:date>2026-01-08T10:00:00Z</dc:date>
  </item>
</rdf:RDF>
"""

HTML_TITLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>&lt;b&gt;Patch&lt;/b&gt; &amp;amp; fix
      now</title><link>https://example.com/p</link></item>
  <item><title><![CDATA[<script>alert(1)</script>Hi]]></title><link>https://example.com/s</link></item>
</channel></rss>
"""

RELATIVE_LINK_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Rel</title><link>/posts/1</link></item>
  <item><title>Script</title><link>javascript:alert(1)</link></item>
</channel></rss>
"""

NO_LINK_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>No link</title></item>
  <item><link>https://example.com/untitled</link></item>
</channel></rss>
"""

UNDATED_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Undated</title><link>https://example.com/u</link></item>
</channel></rss>
"""


def git_repo(path, commits):
    """Create a git repository at `path` with one commit per (xml, message, date).

    The watchlist file is written with `xml` (None deletes it) before each commit.
    Global and system git config are ignored so the user's settings never interfere.
    """
    import os
    import subprocess
    from pathlib import Path

    path = Path(path)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}

    def git(*args, **extra):
        return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True,
                              env={**env, **extra}).stdout.decode()

    git("init", "-q", "-b", "main")
    shas = []
    for xml, message, date in commits:
        target = path / "infosec-intelligence-watchlist.xml"
        if xml is None:
            target.unlink()
        else:
            target.write_text(xml, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "--allow-empty", "-m", message, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        shas.append(git("rev-parse", "HEAD").strip())
    return shas


def opml(folders):
    """Watchlist XML from {"Cat > Sub": [(title, url), ...]}."""
    from xml.sax.saxutils import quoteattr

    cats = {}
    for key, feeds in folders.items():
        cat, sub = key.split(" > ")
        cats.setdefault(cat, {})[sub] = feeds
    out = ['<?xml version="1.0"?>', '<opml version="2.0"><head><title>t</title></head><body>']
    for cat, subs in cats.items():
        out.append(f"  <outline text={quoteattr(cat)} title={quoteattr(cat)}>")
        for sub, feeds in subs.items():
            out.append(f"    <outline text={quoteattr(sub)} title={quoteattr(sub)}>")
            for title, url in feeds:
                out.append(f'      <outline type="rss" text={quoteattr(title)} title={quoteattr(title)} '
                           f'xmlUrl={quoteattr(url)} htmlUrl="https://example.com"/>')
            out.append("    </outline>")
        out.append("  </outline>")
    out.append("</body></opml>")
    return "\n".join(out) + "\n"
