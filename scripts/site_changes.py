"""Feed changes (added, removed, moved, URL updated) from the git history.

Each commit that touched the watchlist is compared with its parent version,
using the same matching rules as `changelog.py`. The reason of a change is the
commit message line `- <feed URL>: <reason>` for that feed (old or new URL),
otherwise the commit's subject line.
"""
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from changelog import FILE, diff_feeds, norm, parse_feeds

REASON_LINE = re.compile(r"^- (https?://\S+): (.+)$")
KIND_ORDER = ("added", "removed", "moved", "updated")
SHA = re.compile(r"^[0-9a-f]{40,64}$")


class HistoryUnavailable(Exception):
    """Git or the repository history can't be read (not a repo, shallow clone, no git)."""


def parse_reasons(message):
    """{normalised url: reason} from the `- <feed URL>: <reason>` lines of a commit message."""
    reasons = {}
    for line in message.split("\n"):  # not splitlines(): it also splits on \x1c-\x1e
        m = REASON_LINE.match(line.rstrip())
        if m:
            reasons[norm(m.group(1))] = m.group(2).strip()
    return reasons


def _original_urls(data):
    """{normalised url: url as written} for the watchlist XML `data`."""
    if not data:
        return {}
    return {norm(o.get("xmlUrl")): o.get("xmlUrl") for o in ET.fromstring(data).iter("outline") if o.get("xmlUrl")}


def changes_between(old_data, new_data, reasons, commit):
    """Change entries between two versions of the watchlist XML (bytes, or None when absent).

    `commit` holds the "commit", "date" and "subject" copied into every entry.
    """
    old = parse_feeds(old_data) if old_data else {}
    new = parse_feeds(new_data) if new_data else {}
    old_urls, new_urls = _original_urls(old_data), _original_urls(new_data)
    d = diff_feeds(old, new)

    def entry(kind, o, n):
        title, folder = (new[n] if n else old[o])
        reason = reasons.get(n) or reasons.get(o) or commit["subject"]
        return {
            "date": commit["date"], "commit": commit["commit"], "subject": commit["subject"],
            "kind": kind, "title": title, "folder": folder,
            "previous_folder": old[o][1] if kind == "moved" else None,
            "url": new_urls[n] if n else old_urls[o],
            "previous_url": old_urls[o] if kind == "updated" else None,
            "reason": reason,
        }

    rows = ([entry("added", None, n) for n in d["added"]]
            + [entry("removed", o, None) for o in d["removed"]]
            + [entry("moved", o, n) for o, n in d["moved"]]
            + [entry("updated", o, n) for o, n in d["updated"]])
    rows.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), r["title"].casefold()))
    return rows


def _git(repo, *args, check=True):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", b"") or b""
        raise HistoryUnavailable(f"git {args[0]} failed: {detail.decode(errors='replace').strip() or e}") from e


def _show(repo, rev):
    """The watchlist at `rev`, or None if it doesn't exist there (or `rev` has no parent)."""
    p = _git(repo, "show", f"{rev}:{FILE}", check=False)
    return p.stdout if p.returncode == 0 else None


def _records(log):
    """(sha, date, message) of every well-formed record of `git log -z --format=%H%x1f%cI%x1f%B`.

    Records are NUL-separated (a commit message can't hold a NUL); a malformed
    record is skipped, never fatal.
    """
    for record in log.decode("utf-8", "replace").split("\x00"):
        parts = record.lstrip("\n").split("\x1f", 2)
        if len(parts) != 3 or not SHA.match(parts[0]):
            continue
        try:
            date = datetime.fromisoformat(parts[1])
        except ValueError:
            continue
        yield parts[0], parts[1], date, parts[2]


def collect_changes(repo: Path, since: datetime) -> list:
    """Every feed change committed since `since`, newest first.

    The commit that introduced the watchlist (the oldest one touching it, with
    no parent version) is the baseline: its feeds are not reported as added.
    Raises HistoryUnavailable when the history can't be read in full.
    """
    if _git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
        raise HistoryUnavailable("shallow clone: fetch the full history (fetch-depth: 0)")
    log = _git(repo, "log", "-z", "--no-merges", "--format=%H%x1f%cI%x1f%B", "--", FILE).stdout
    records = list(_records(log))
    changes = []
    for i, (sha, date_text, date, message) in enumerate(records):
        if date < since:
            continue
        previous = _show(repo, f"{sha}^")
        if previous is None and i == len(records) - 1:
            continue  # baseline: the commit that introduced the watchlist
        subject = message.strip().split("\n")[0].rstrip("\r")
        try:
            rows = changes_between(previous, _show(repo, sha), parse_reasons(message),
                                   {"commit": sha, "date": date_text, "subject": subject})
        except ET.ParseError:
            continue  # an unreadable version can't be compared
        changes += rows
    return changes
