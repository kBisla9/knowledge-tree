"""Tests for git_ops module."""

from __future__ import annotations

import pytest

from knowledge_tree import git_ops


class TestRunGit:
    def test_successful_command(self, cloned_repo):
        output = git_ops.run_git(["status"], cwd=cloned_repo)
        assert "branch main" in output.lower() or "branch" in output.lower()

    def test_failure_raises_runtime_error(self, tmp_path):
        with pytest.raises(RuntimeError, match="failed"):
            git_ops.run_git(["log"], cwd=tmp_path)  # not a git repo


class TestClassifyGitError:
    def test_network_error(self):
        hint = git_ops._classify_git_error("fatal: Could not resolve host: github.com")
        assert "network" in hint.lower()

    def test_repo_not_found(self):
        hint = git_ops._classify_git_error("fatal: repository 'https://x.com/y.git' not found")
        assert "repository URL" in hint

    def test_auth_error(self):
        hint = git_ops._classify_git_error(
            "fatal: Authentication failed for 'https://x.com/y.git'"
        )
        assert "credentials" in hint.lower()

    def test_unknown_error(self):
        hint = git_ops._classify_git_error("some other error")
        assert hint == ""


class TestClone:
    def test_clone_basic(self, bare_repo, tmp_path):
        dest = tmp_path / "my-clone"
        git_ops.clone(str(bare_repo), dest, branch="main", depth=None)
        assert (dest / "README.md").exists()

    def test_clone_shallow(self, bare_repo, tmp_path):
        # Add a second commit so shallow clone has something to truncate
        work = tmp_path / "extra-work"
        git_ops.clone(str(bare_repo), work, branch="main", depth=None)
        git_ops.run_git(["config", "user.email", "t@t.com"], cwd=work)
        git_ops.run_git(["config", "user.name", "T"], cwd=work)
        (work / "second.md").write_text("second commit\n")
        git_ops.add_and_commit(work, ["second.md"], "Second commit")
        git_ops.run_git(["push", "origin", "main"], cwd=work)

        # Use file:// protocol to force pack protocol (local paths use
        # hardlinks which bypass shallow clone logic)
        dest = tmp_path / "shallow"
        git_ops.clone(f"file://{bare_repo}", dest, branch="main", depth=1)
        assert (dest / "second.md").exists()
        # Verify it's shallow (only 1 commit in log)
        log = git_ops.run_git(["log", "--oneline"], cwd=dest)
        assert log.count("\n") == 0  # single line = 1 commit


class TestPull:
    def test_pull_new_content(self, bare_repo, tmp_path):
        # Clone first copy
        clone1 = tmp_path / "clone1"
        git_ops.clone(str(bare_repo), clone1, branch="main", depth=None)
        git_ops.run_git(["config", "user.email", "test@test.com"], cwd=clone1)
        git_ops.run_git(["config", "user.name", "Test"], cwd=clone1)

        # Push new content from clone1
        (clone1 / "new-file.md").write_text("New content\n")
        git_ops.add_and_commit(clone1, ["new-file.md"], "Add new file")
        git_ops.run_git(["push", "origin", "main"], cwd=clone1)

        # Clone second copy and pull
        clone2 = tmp_path / "clone2"
        git_ops.clone(str(bare_repo), clone2, branch="main", depth=None)

        # The file should already be there since we cloned after the push
        assert (clone2 / "new-file.md").exists()


class TestHeadRef:
    def test_head_ref_format(self, cloned_repo):
        ref = git_ops.get_head_ref(cloned_repo)
        assert len(ref) == 40
        assert all(c in "0123456789abcdef" for c in ref)

    def test_short_ref_format(self, cloned_repo):
        ref = git_ops.get_short_ref(cloned_repo)
        assert len(ref) == 7
        assert all(c in "0123456789abcdef" for c in ref)

    def test_short_ref_is_prefix_of_full(self, cloned_repo):
        full = git_ops.get_head_ref(cloned_repo)
        short = git_ops.get_short_ref(cloned_repo)
        assert full.startswith(short)


class TestIsGitRepo:
    def test_true_for_repo(self, cloned_repo):
        assert git_ops.is_git_repo(cloned_repo) is True

    def test_false_for_non_repo(self, tmp_path):
        plain_dir = tmp_path / "not-a-repo"
        plain_dir.mkdir()
        assert git_ops.is_git_repo(plain_dir) is False


class TestBranch:
    def test_create_branch(self, cloned_repo):
        git_ops.create_branch(cloned_repo, "feature/test")
        output = git_ops.run_git(["branch", "--show-current"], cwd=cloned_repo)
        assert output == "feature/test"


class TestAddAndCommit:
    def test_commit_new_file(self, cloned_repo):
        (cloned_repo / "test.txt").write_text("Hello\n")
        git_ops.add_and_commit(cloned_repo, ["test.txt"], "Add test file")
        log = git_ops.run_git(["log", "--oneline", "-1"], cwd=cloned_repo)
        assert "Add test file" in log


class TestUnshallow:
    def test_unshallow_shallow_clone(self, bare_repo, tmp_path):
        # Add a second commit so shallow clone has something to truncate
        work = tmp_path / "extra-work"
        git_ops.clone(str(bare_repo), work, branch="main", depth=None)
        git_ops.run_git(["config", "user.email", "t@t.com"], cwd=work)
        git_ops.run_git(["config", "user.name", "T"], cwd=work)
        (work / "second.md").write_text("second commit\n")
        git_ops.add_and_commit(work, ["second.md"], "Second commit")
        git_ops.run_git(["push", "origin", "main"], cwd=work)

        # Use file:// protocol to force shallow behavior
        dest = tmp_path / "shallow"
        git_ops.clone(f"file://{bare_repo}", dest, branch="main", depth=1)
        # Verify shallow: only 1 commit visible
        log_before = git_ops.run_git(["log", "--oneline"], cwd=dest)
        assert log_before.count("\n") == 0

        git_ops.unshallow(dest)
        # After unshallow, both commits should be visible
        log_after = git_ops.run_git(["log", "--oneline"], cwd=dest)
        assert log_after.count("\n") == 1  # 2 lines = 2 commits

    def test_unshallow_full_clone_noop(self, cloned_repo):
        # Should not raise
        git_ops.unshallow(cloned_repo)


class TestEnsureGitIdentity:
    def test_sets_identity_when_missing(self, cloned_repo, monkeypatch):
        # Isolate from any global/system git config
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
        # Remove any existing local user config
        git_ops.run_git(["config", "--unset", "user.name"], cwd=cloned_repo)
        git_ops.run_git(["config", "--unset", "user.email"], cwd=cloned_repo)

        git_ops._ensure_git_identity(cloned_repo)

        name = git_ops.run_git(["config", "user.name"], cwd=cloned_repo)
        email = git_ops.run_git(["config", "user.email"], cwd=cloned_repo)
        assert name == "Knowledge Tree"
        assert email == "kt@localhost"

    def test_preserves_existing_identity(self, cloned_repo):
        git_ops.run_git(["config", "user.name", "Custom User"], cwd=cloned_repo)
        git_ops.run_git(["config", "user.email", "custom@example.com"], cwd=cloned_repo)

        git_ops._ensure_git_identity(cloned_repo)

        name = git_ops.run_git(["config", "user.name"], cwd=cloned_repo)
        email = git_ops.run_git(["config", "user.email"], cwd=cloned_repo)
        assert name == "Custom User"
        assert email == "custom@example.com"

    def test_sets_only_missing_fields(self, cloned_repo, monkeypatch):
        # Isolate from any global/system git config
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
        git_ops.run_git(["config", "user.name", "Custom User"], cwd=cloned_repo)
        git_ops.run_git(["config", "--unset", "user.email"], cwd=cloned_repo)

        git_ops._ensure_git_identity(cloned_repo)

        name = git_ops.run_git(["config", "user.name"], cwd=cloned_repo)
        email = git_ops.run_git(["config", "user.email"], cwd=cloned_repo)
        assert name == "Custom User"
        assert email == "kt@localhost"


class TestDetectProvider:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://github.com/user/repo.git", "github"),
            ("git@github.com:user/repo.git", "github"),
            ("https://gitlab.com/user/repo.git", "gitlab"),
            ("git@gitlab.company.com:team/repo.git", "gitlab"),
            ("https://bitbucket.org/user/repo.git", "bitbucket"),
            ("https://selfhosted.example.com/repo.git", "unknown"),
        ],
    )
    def test_detect_provider(self, url, expected):
        assert git_ops.detect_provider(url) == expected


class TestRemoteToWebUrl:
    @pytest.mark.parametrize(
        "remote, expected",
        [
            (
                "git@github.com:user/repo.git",
                "https://github.com/user/repo",
            ),
            (
                "https://github.com/user/repo.git",
                "https://github.com/user/repo",
            ),
            (
                "https://github.com/user/repo",
                "https://github.com/user/repo",
            ),
            (
                "git@gitlab.com:team/project.git",
                "https://gitlab.com/team/project",
            ),
        ],
    )
    def test_remote_to_web_url(self, remote, expected):
        assert git_ops._remote_to_web_url(remote) == expected


class TestGetMrUrl:
    def test_github(self):
        url = git_ops.get_mr_url("https://github.com/user/repo.git", "feature/test")
        assert "github.com/user/repo/compare/feature/test" in url

    def test_gitlab(self):
        url = git_ops.get_mr_url("https://gitlab.com/user/repo.git", "feature/test")
        assert "merge_requests/new" in url
        assert "source_branch]=feature/test" in url

    def test_bitbucket(self):
        url = git_ops.get_mr_url("https://bitbucket.org/user/repo.git", "feature/test")
        assert "pull-requests/new" in url
        assert "source=feature/test" in url

    def test_unknown_provider(self):
        url = git_ops.get_mr_url("https://selfhosted.example.com/repo.git", "feature/test")
        assert "manually" in url
