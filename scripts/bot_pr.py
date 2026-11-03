#!/usr/bin/env python3
"""Open, update or close the pull request of one of the bot's branches.

main only takes pull requests, so the workflows that change files for the
maintainer (feed-health.yml, sync-generated.yml, suggest-feed.yml) push to a
branch of their own and open a pull request from it. The rules live here:
- only the bot's pull requests count, never a fork's or a person's from a
  branch of the same name
- a branch with someone else's commits since main is never pushed to nor
  deleted: the maintainer's work is kept (exit code 3)
- the push uses --force-with-lease, so it never overwrites a commit pushed
  after the check
- when Actions may not open pull requests (Settings > Actions > "Allow GitHub
  Actions to create and approve pull requests" is off), the comparison URL is
  given instead, with a warning

Commands, each writing its result to --output:
    bot_pr.py state --branch B --output F       "<STATE> <url>" of the bot's latest PR for B (STATE NONE if none)
    bot_pr.py find --url U --prefix P [--exclude-branch B] --output F
                                                URL of an open bot PR from a P* branch whose body has a "- U:" line
    bot_pr.py publish --branch B --title T --body-file F --commit-message-file C --output F PATH...
                                                commit PATH... on B from the current HEAD, push, open or update the PR
    bot_pr.py close --branch B --comment TEXT   close the bot's open PR for B and delete the branch

git and gh run in the current directory; gh needs GH_TOKEN, and pushing needs
`gh auth setup-git`. The branch is compared with origin/main, which must have
its history (actions/checkout with fetch-depth: 0).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BOT_LOGINS = {"app/github-actions", "github-actions[bot]"}  # author of PRs opened with GITHUB_TOKEN
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
BASE = "main"
KEPT = 3  # exit code: the branch has someone else's commits, left untouched
PR_FIELDS = "url,state,headRefName,isCrossRepository,author,body"


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def gh_json(*args):
    return json.loads(run("gh", *args).stdout or "[]")


def warn(message):
    print(f"::warning::{message}")


def is_bot_pr(pr):
    """True for a pull request the bot opened in this repository (not from a fork, not by a person)."""
    return not pr.get("isCrossRepository") and (pr.get("author") or {}).get("login") in BOT_LOGINS


def bot_pr_for_branch(prs, branch):
    """The bot's latest pull request for a branch (gh lists newest first), or None."""
    return next((pr for pr in prs if pr.get("headRefName") == branch and is_bot_pr(pr)), None)


def find_open_pr_for_url(prs, url, prefix):
    """URL of an open bot pull request from a `prefix` branch whose body has a "- <url>:" line, or None."""
    for pr in prs:
        if pr.get("headRefName", "").startswith(prefix) and is_bot_pr(pr) and f"- {url}:" in (pr.get("body") or ""):
            return pr["url"]
    return None


def list_prs(branch, state):
    return gh_json("pr", "list", "--head", branch, "--state", state, "--limit", "20", "--json", PR_FIELDS)


def lease(branch, base=BASE):
    """--force-with-lease value for pushing `branch`: it must not exist yet, or still be where it is now.

    None when the branch has commits from someone else than the bot since `base`."""
    if run("git", "ls-remote", "--exit-code", "-q", "origin", f"refs/heads/{branch}", check=False).returncode == 2:
        return f"refs/heads/{branch}:"
    run("git", "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    # an amend or rebase keeps the bot as author: check committers too
    emails = run("git", "log", f"origin/{base}..origin/{branch}", "--format=%ae%n%ce").stdout.split()
    if any(email != BOT_EMAIL for email in emails):
        return None
    return f"refs/heads/{branch}:{run('git', 'rev-parse', f'origin/{branch}').stdout.strip()}"


def compare_url(branch, base=BASE):
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}/compare/{base}...{branch}?expand=1"


def state(branch):
    pr = bot_pr_for_branch(list_prs(branch, "all"), branch) or {}
    return f"{pr.get('state', 'NONE')} {pr.get('url', '')}".strip()


def find(url, prefix, exclude_branch=None):
    prs = gh_json("pr", "list", "--state", "open", "--limit", "200", "--json", PR_FIELDS)
    return find_open_pr_for_url([p for p in prs if p.get("headRefName") != exclude_branch], url, prefix) or ""


def publish(branch, title, body_file, message_file, paths, base=BASE):
    """(exit code, pull request URL): commit `paths` on `branch`, push it, open or update its pull request."""
    existing = (bot_pr_for_branch(list_prs(branch, "open"), branch) or {}).get("url", "")
    value = lease(branch, base)
    if value is None:
        warn(f"{branch} has commits from someone else, left untouched: merge or close its pull request")
        return KEPT, existing
    run("git", "switch", "-q", "-C", branch)
    run("git", "add", "-A", "--", *paths)
    run("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "-q", "-F", message_file)
    run("git", "push", "-q", f"--force-with-lease={value}", "origin", f"HEAD:refs/heads/{branch}")
    if existing:
        run("gh", "pr", "edit", existing, "--title", title, "--body-file", body_file)
        return 0, existing
    created = run("gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", body_file,
                  check=False)
    if created.returncode:
        url = compare_url(branch, base)
        warn(f"Could not open the pull request, open it from {url}")
        return 0, url
    return 0, created.stdout.strip()


def close(branch, comment, base=BASE):
    """(exit code, URL of the closed pull request, empty if there was none)."""
    pr = bot_pr_for_branch(list_prs(branch, "open"), branch)
    if not pr:
        return 0, ""
    if lease(branch, base) is None:
        warn(f"{branch} has commits from someone else, left open: merge or close its pull request")
        return KEPT, pr["url"]
    run("gh", "pr", "close", pr["url"], "--delete-branch", "--comment", comment)
    return 0, pr["url"]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("state", "find", "publish", "close"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--output", help="where to write the result")
        if name != "find":
            cmd.add_argument("--branch", required=True)
    sub.choices["find"].add_argument("--url", required=True)
    sub.choices["find"].add_argument("--prefix", required=True, help="only branches starting with this")
    sub.choices["find"].add_argument("--exclude-branch")
    sub.choices["publish"].add_argument("--title", required=True)
    sub.choices["publish"].add_argument("--body-file", required=True)
    sub.choices["publish"].add_argument("--commit-message-file", required=True)
    sub.choices["publish"].add_argument("paths", nargs="+", help="files to commit")
    sub.choices["close"].add_argument("--comment", required=True)
    args = p.parse_args(argv)

    code = 0
    try:
        if args.command == "state":
            result = state(args.branch)
        elif args.command == "find":
            result = find(args.url, args.prefix, args.exclude_branch)
        elif args.command == "publish":
            code, result = publish(args.branch, args.title, args.body_file, args.commit_message_file, args.paths)
        else:
            code, result = close(args.branch, args.comment)
    except subprocess.CalledProcessError as e:
        print(f"::error::{' '.join(e.cmd[:3])} failed: {(e.stderr or '').strip()[:500]}")
        return 1
    if args.output:
        Path(args.output).write_text(result + "\n" if result else "", encoding="utf-8")
    print(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
