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
