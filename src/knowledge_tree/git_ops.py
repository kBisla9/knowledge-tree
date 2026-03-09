"""Git abstraction layer using subprocess."""

from __future__ import annotations

import contextlib
import re
import subprocess
from pathlib import Path


def _classify_git_error(stderr: str) -> str:
    """Produce a human-readable hint for common git errors."""
    s = stderr.lower()
    if "could not resolve host" in s or "unable to access" in s:
        return "Check your network connection."
    if ("repository" in s and "not found" in s) or "does not appear to be a git repository" in s:
        return "Verify the repository URL is correct."
    if "authentication failed" in s or "permission denied" in s:
        return "Check your git credentials or SSH key."
    if "already exists and is not an empty directory" in s:
        return "The destination directory already exists."
    if "not a git repository" in s:
        return "This directory is not a git repository."
    return ""


def run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
) -> str:
    """Run a git command and return stdout.

    Raises RuntimeError on non-zero exit code with classified hint.
    """
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Git command timed out after {timeout}s: git {' '.join(args)}"
        ) from exc

    if result.returncode != 0:
        hint = _classify_git_error(result.stderr)
        msg = (
            f"Git command failed (exit {result.returncode}): "
            f"git {' '.join(args)}\n{result.stderr.strip()}"
        )
        if hint:
            msg += f"\n{hint}"
        raise RuntimeError(msg)
    return result.stdout.strip()


def clone(
    url: str,
    dest: Path,
    branch: str = "main",
    depth: int | None = 1,
) -> None:
    """Clone a git repository.

    Args:
        url: Repository URL (HTTPS or SSH).
        dest: Destination directory.
        branch: Branch to checkout.
        depth: Shallow clone depth. None for full clone.
    """
    args = ["clone", "--branch", branch]
    if depth is not None:
        args += ["--depth", str(depth)]
    args += [url, str(dest)]
    run_git(args)


def pull(repo_path: Path, branch: str = "main") -> str:
    """Fetch and pull latest changes. Returns new HEAD hash."""
    run_git(["fetch", "origin", branch], cwd=repo_path)
    run_git(["checkout", branch], cwd=repo_path)
    run_git(["pull", "origin", branch], cwd=repo_path)
    return get_head_ref(repo_path)


def get_head_ref(repo_path: Path) -> str:
    """Return the full 40-character commit hash of HEAD."""
    return run_git(["rev-parse", "HEAD"], cwd=repo_path)


def get_short_ref(repo_path: Path) -> str:
    """Return the 7-character short hash of HEAD."""
    return run_git(["rev-parse", "--short", "HEAD"], cwd=repo_path)


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    try:
        run_git(["rev-parse", "--git-dir"], cwd=path)
        return True
    except (RuntimeError, FileNotFoundError):
        return False


def create_branch(repo_path: Path, branch: str) -> None:
    """Create and checkout a new branch."""
    run_git(["checkout", "-b", branch], cwd=repo_path)


def push_branch(repo_path: Path, branch: str) -> None:
    """Push a branch to origin."""
    run_git(["push", "-u", "origin", branch], cwd=repo_path)


def _ensure_git_identity(repo_path: Path) -> None:
    """Set git user identity if not already configured."""
    for key, fallback in [
        ("user.name", "Knowledge Tree"),
        ("user.email", "kt@localhost"),
    ]:
        result = subprocess.run(
            ["git", "config", key],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            run_git(["config", key, fallback], cwd=repo_path)


def add_and_commit(
    repo_path: Path,
    files: list[str],
    message: str,
) -> None:
    """Stage files and create a commit."""
    _ensure_git_identity(repo_path)
    for f in files:
        run_git(["add", f], cwd=repo_path)
    run_git(["commit", "-m", message], cwd=repo_path)


def unshallow(repo_path: Path) -> None:
    """Convert a shallow clone to a full clone. No-op if already full."""
    with contextlib.suppress(RuntimeError):
        # Already full — git returns error on non-shallow repo
        run_git(["fetch", "--unshallow"], cwd=repo_path)


def detect_provider(remote_url: str) -> str:
    """Detect git hosting provider from a remote URL.

    Returns one of: 'github', 'gitlab', 'bitbucket', 'unknown'.
    """
    url_lower = remote_url.lower()
    if "github.com" in url_lower:
        return "github"
    if "gitlab" in url_lower:
        return "gitlab"
    if "bitbucket" in url_lower:
        return "bitbucket"
    return "unknown"


def _remote_to_web_url(remote_url: str) -> str:
    """Convert a git remote URL (SSH or HTTPS) to a web URL.

    Examples:
        git@github.com:user/repo.git -> https://github.com/user/repo
        https://github.com/user/repo.git -> https://github.com/user/repo
    """
    url = remote_url.strip()

    # SSH format: git@host:user/repo.git
    ssh_match = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
    if ssh_match:
        host, path = ssh_match.groups()
        return f"https://{host}/{path}"

    # HTTPS format: https://host/user/repo.git
    if url.startswith("https://") or url.startswith("http://"):
        url = re.sub(r"\.git$", "", url)
        return url

    return url


def get_mr_url(remote_url: str, branch: str) -> str:
    """Generate a merge/pull request creation URL for the given provider.

    Args:
        remote_url: The git remote URL.
        branch: The branch to create a MR/PR from.

    Returns:
        A URL string the user can open to create a MR/PR.
    """
    web_url = _remote_to_web_url(remote_url)
    provider = detect_provider(remote_url)

    if provider == "github":  # noqa: SIM116
        return f"{web_url}/compare/{branch}?expand=1"
    elif provider == "gitlab":
        return f"{web_url}/-/merge_requests/new?merge_request[source_branch]={branch}"
    elif provider == "bitbucket":
        return f"{web_url}/pull-requests/new?source={branch}"
    else:
        return f"{web_url} (create MR/PR from branch '{branch}' manually)"
