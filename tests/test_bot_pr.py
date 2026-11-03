import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_pr  # noqa: E402

BOT = {"isCrossRepository": False, "author": {"login": "app/github-actions"}}
REAL_RUN = bot_pr.run


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PullRequestListTest(unittest.TestCase):
    def test_find_open_pr_for_url(self):
        prs = [{"url": "https://github.com/o/r/pull/3", "headRefName": "suggestion/issue-9", **BOT,
                "body": "- https://cyble.com/feed/: suggested by @x in #9"},
               {"url": "https://github.com/o/r/pull/4", "headRefName": "feed-health/autofix", **BOT,
                "body": "https://cyble.com/feed/"}]
        self.assertEqual(bot_pr.find_open_pr_for_url(prs, "https://cyble.com/feed/", "suggestion/"),
                         "https://github.com/o/r/pull/3")
        self.assertIsNone(bot_pr.find_open_pr_for_url(prs, "https://other.com/feed", "suggestion/"))

    def test_fork_or_human_prs_are_not_the_bots(self):
        fork = {"url": "https://github.com/o/r/pull/7", "headRefName": "suggestion/issue-9", "state": "OPEN",
                "isCrossRepository": True, "author": {"login": "app/github-actions"},
                "body": "- https://cyble.com/feed/: x"}
        human = {**fork, "url": "https://github.com/o/r/pull/8", "isCrossRepository": False, "author": {"login": "mallory"}}
        bot = {**fork, "url": "https://github.com/o/r/pull/9", **BOT}
        self.assertIsNone(bot_pr.find_open_pr_for_url([fork, human], "https://cyble.com/feed/", "suggestion/"))
        self.assertIsNone(bot_pr.bot_pr_for_branch([fork, human], "suggestion/issue-9"))
        self.assertEqual(bot_pr.bot_pr_for_branch([fork, human, bot], "suggestion/issue-9")["url"],
                         "https://github.com/o/r/pull/9")


class BranchTest(unittest.TestCase):
    """Real git repositories (a bare origin and a clone), gh replaced by a fake."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.work = root / "origin.git", root / "work"
        git("init", "-q", "--bare", "-b", "main", str(self.origin))
        git("clone", "-q", str(self.origin), str(self.work))
        self.commit("init", "me@example.com", "README.md")
        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=self.work)
        git("fetch", "-q", "origin", cwd=self.work)
        self.cwd = os.getcwd()
        os.chdir(self.work)
        self.prs = []  # what `gh pr list` answers
        self.gh_calls = []

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def commit(self, message, email, name):
        (self.work / name).write_text(message + "\n")
        git("add", name, cwd=self.work)
        git("-c", "user.name=x", "-c", f"user.email={email}", "commit", "-q", "-m", message, cwd=self.work)

    def push_branch(self, branch, *emails):
        """Create `branch` on origin from main, with one commit per committer email."""
        git("switch", "-q", "-c", branch, "origin/main", cwd=self.work)
        for i, email in enumerate(emails):
            self.commit(f"change {i}", email, f"file{i}.txt")
        git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=self.work)
        git("switch", "-q", "--detach", "origin/main", cwd=self.work)
        git("branch", "-q", "-D", branch, cwd=self.work)

    def fake_run(self, *cmd, check=True):
        if cmd[0] != "gh":
            return REAL_RUN(*cmd, check=check)
        self.gh_calls.append(cmd[1:])
        out = ""
        if cmd[1:3] == ("pr", "list"):
            out = json.dumps(self.prs)
        elif cmd[1:3] == ("pr", "create"):
            out = "https://github.com/o/r/pull/5\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def publish(self, branch="bot/fix"):
        (self.work / "data.txt").write_text("new\n")
        (self.work / "msg.txt").write_text("Update data\n")
        (self.work / "body.md").write_text("Body\n")
        with mock.patch.object(bot_pr, "run", self.fake_run):
            return bot_pr.publish(branch, "Title", "body.md", "msg.txt", ["data.txt"])

    def test_lease_for_a_new_branch(self):
        self.assertEqual(bot_pr.lease("bot/fix"), "refs/heads/bot/fix:")

    def test_lease_for_a_bot_branch(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL)
        value = bot_pr.lease("bot/fix")
        sha = git("rev-parse", "origin/bot/fix", cwd=self.work)
        self.assertEqual(value, f"refs/heads/bot/fix:{sha}")

    def test_no_lease_when_someone_else_committed(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL, "maintainer@example.com")
        self.assertIsNone(bot_pr.lease("bot/fix"))

    def test_publish_creates_the_pull_request(self):
        code, url = self.publish()
        self.assertEqual((code, url), (0, "https://github.com/o/r/pull/5"))
        self.assertEqual(git("log", "-1", "--format=%ae %s", "origin/bot/fix"), f"{bot_pr.BOT_EMAIL} Update data")
        self.assertIn(("pr", "create", "--base", "main", "--head", "bot/fix", "--title", "Title", "--body-file", "body.md"),
                      self.gh_calls)

    def test_publish_replaces_the_bots_branch_and_edits_its_pull_request(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL)
        self.prs = [{"url": "https://github.com/o/r/pull/2", "headRefName": "bot/fix", "state": "OPEN", **BOT}]
        code, url = self.publish()
        self.assertEqual((code, url), (0, "https://github.com/o/r/pull/2"))
        self.assertEqual(git("log", "--format=%s", "origin/main..origin/bot/fix"), "Update data")
        self.assertIn(("pr", "edit", "https://github.com/o/r/pull/2", "--title", "Title", "--body-file", "body.md"),
                      self.gh_calls)

    def test_publish_keeps_a_branch_with_someone_elses_commits(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL, "maintainer@example.com")
        before = git("ls-remote", str(self.origin), "refs/heads/bot/fix")
        code, _ = self.publish()
        self.assertEqual(code, bot_pr.KEPT)
        self.assertEqual(git("ls-remote", str(self.origin), "refs/heads/bot/fix"), before)

    def test_publish_ignores_a_fork_pull_request_of_the_same_branch(self):
        self.prs = [{"url": "https://github.com/o/r/pull/8", "headRefName": "bot/fix", "state": "OPEN",
                     "isCrossRepository": True, "author": {"login": "mallory"}}]
        code, url = self.publish()
        self.assertEqual(url, "https://github.com/o/r/pull/5")  # a new pull request, #8 left alone
        self.assertFalse([c for c in self.gh_calls if c[:2] == ("pr", "edit")])

    def test_close_keeps_a_branch_with_someone_elses_commits(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL, "maintainer@example.com")
        self.prs = [{"url": "https://github.com/o/r/pull/2", "headRefName": "bot/fix", "state": "OPEN", **BOT}]
        with mock.patch.object(bot_pr, "run", self.fake_run):
            code, _ = bot_pr.close("bot/fix", "done")
        self.assertEqual(code, bot_pr.KEPT)
        self.assertFalse([c for c in self.gh_calls if c[:2] == ("pr", "close")])

    def test_close_the_bots_pull_request(self):
        self.push_branch("bot/fix", bot_pr.BOT_EMAIL)
        self.prs = [{"url": "https://github.com/o/r/pull/2", "headRefName": "bot/fix", "state": "OPEN", **BOT}]
        with mock.patch.object(bot_pr, "run", self.fake_run):
            self.assertEqual(bot_pr.close("bot/fix", "done"), (0, "https://github.com/o/r/pull/2"))
        self.assertIn(("pr", "close", "https://github.com/o/r/pull/2", "--delete-branch", "--comment", "done"),
                      self.gh_calls)


if __name__ == "__main__":
    unittest.main()
