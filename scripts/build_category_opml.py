#!/usr/bin/env python3
"""Generate one OPML file per subcategory from the global watchlist.

The global file `infosec-intelligence-watchlist.xml` is the single source of
truth: never edit the files under `opml/` by hand, re-run this script instead.

Usage:
    python3 scripts/build_category_opml.py            # regenerate opml/
    python3 scripts/build_category_opml.py --table    # also print the README table
"""
import argparse
import re
import shutil
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "infosec-intelligence-watchlist.xml"
OUT_DIR = ROOT / "opml"
README = ROOT / "README.md"
RAW_BASE = "https://raw.githubusercontent.com/ArmorIntel/infosec-intelligence-watchlist/refs/heads/main"


def slugify(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def render(title, date_modified, category, subcategory, feeds):
    lines = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        '<opml version="2.0">',
        "  <head>",
        f"    <title>{escape(title)}</title>",
    ]
    if date_modified:
        lines.append(f"    <dateModified>{escape(date_modified)}</dateModified>")
    lines += [
        "    <ownerName>ArmorIntel</ownerName>",
        "    <ownerId>https://github.com/ArmorIntel</ownerId>",
        "  </head>",
        "  <body>",
        f"    <outline text={quoteattr(category)} title={quoteattr(category)}>",
        f"      <outline text={quoteattr(subcategory)} title={quoteattr(subcategory)}>",
    ]
    for feed in feeds:
        attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in feed.attrib.items())
        lines.append(f"        <outline {attrs} />")
    lines += ["      </outline>", "    </outline>", "  </body>", "</opml>", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", action="store_true", help="print the README subscription table")
    parser.add_argument("--readme", action="store_true", help="rewrite the generated blocks of the README")
    args = parser.parse_args()

    tree = ET.parse(SOURCE)
    head = tree.getroot().find("head")
    base_title = head.findtext("title", "Infosec intelligence watchlist")
    date_modified = head.findtext("dateModified")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)

    rows = []
    for category in tree.getroot().find("body").findall("outline"):
        cat_name = category.get("title") or category.get("text")
        for sub in category.findall("outline"):
            sub_name = sub.get("title") or sub.get("text")
            feeds = [o for o in sub.findall("outline") if o.get("xmlUrl")]
            if not feeds:
                continue
            path = OUT_DIR / slugify(cat_name) / f"{slugify(sub_name)}.opml"
            path.parent.mkdir(parents=True, exist_ok=True)
            title = f"{base_title} - {cat_name} - {sub_name}"
            path.write_text(render(title, date_modified, cat_name, sub_name, feeds), encoding="utf-8")
            rows.append((cat_name, sub_name, len(feeds), path.relative_to(ROOT).as_posix()))

    print(f"Generated {len(rows)} files in {OUT_DIR.relative_to(ROOT)}/")
    table = render_table(rows)
    if args.table:
        print()
        print(table)
    if args.readme:
        readme = README.read_text(encoding="utf-8")
        readme = replace_block(readme, "categories", render_categories(rows))
        readme = replace_block(readme, "category-table", table)
        README.write_text(readme, encoding="utf-8")
        print(f"Updated {README.name}")


def render_table(rows):
    lines = ["| Category | Subcategory | Feeds | Raw OPML URL |", "|---|---|---:|---|"]
    for cat_name, sub_name, count, rel in rows:
        lines.append(f"| {cat_name} | [{sub_name}](./{rel}) | {count} | `{RAW_BASE}/{rel}` |")
    return "\n".join(lines)


def render_categories(rows):
    total = sum(count for _, _, count, _ in rows)
    lines = [f"- `{SOURCE.name}` &mdash; is an OPML (Outline Processor Markup Language) file of {total} feeds, grouped by categories:"]
    current = None
    for cat_name, sub_name, _, _ in rows:
        if cat_name != current:
            lines.append(f"  - **{cat_name}**")
            current = cat_name
        lines.append(f"    - {sub_name}")
    return "\n".join(lines)


def replace_block(text, name, content):
    """Replace the content between <!-- BEGIN generated:name --> and its END marker."""
    pattern = re.compile(rf"(<!-- BEGIN generated:{name} -->\n).*?(\n<!-- END generated:{name} -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"{README.name}: missing 'generated:{name}' markers")
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), text)


if __name__ == "__main__":
    main()
