"""Shared test fixtures for Knowledge Tree."""

from __future__ import annotations

import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


def _run_git(args: list[str], cwd: Path) -> str:
    """Helper to run git commands in tests."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture
def bare_repo(tmp_path: Path) -> Path:
    """Create a bare git repository with an initial commit.

    Returns the path to the bare repo.
    """
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _run_git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    # Clone, add initial content, push
    work = tmp_path / "init-work"
    _run_git(["clone", str(bare), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test User"], cwd=work)

    readme = work / "README.md"
    readme.write_text("# Test Registry\n")
    _run_git(["add", "README.md"], cwd=work)
    _run_git(["commit", "-m", "Initial commit"], cwd=work)
    _run_git(["push", "origin", "main"], cwd=work)

    return bare


@pytest.fixture
def cloned_repo(bare_repo: Path, tmp_path: Path) -> Path:
    """Clone the bare_repo and return the clone path."""
    clone_dir = tmp_path / "clone"
    _run_git(["clone", str(bare_repo), str(clone_dir)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=clone_dir)
    _run_git(["config", "user.name", "Test User"], cwd=clone_dir)
    return clone_dir


@pytest.fixture
def registry_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare repo with a sample registry structure.

    Returns (bare_repo_path, working_clone_path).
    The clone has packages/base/ with a package.yaml and content.
    """
    bare = tmp_path / "registry.git"
    bare.mkdir()
    _run_git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    work = tmp_path / "registry-work"
    _run_git(["clone", str(bare), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test User"], cwd=work)

    # Create packages/base/
    base_dir = work / "packages" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "package.yaml").write_text(
        "name: base\n"
        "description: Universal coding conventions\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - core\n  - conventions\n"
    )
    (base_dir / "safe-deletion.md").write_text("# Safe Deletion\nAlways use soft deletes.\n")

    # Create packages/git-conventions/
    git_dir = work / "packages" / "git-conventions"
    git_dir.mkdir(parents=True)
    (git_dir / "package.yaml").write_text(
        "name: git-conventions\n"
        "description: Git commit message standards\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "parent: base\n"
        "tags:\n  - git\n"
    )
    (git_dir / "commit-messages.md").write_text("# Commit Messages\nUse conventional commits.\n")

    # Create packages/api-patterns/
    api_dir = work / "packages" / "api-patterns"
    api_dir.mkdir(parents=True)
    (api_dir / "package.yaml").write_text(
        "name: api-patterns\n"
        "description: REST API patterns and auth\n"
        "authors:\n  - Test Author\n"
        "classification: seasonal\n"
        "depends_on:\n  - base\n"
        "tags:\n  - api\n  - rest\n"
        "content:\n  - rest-conventions.md\n  - authentication.md\n"
    )
    (api_dir / "rest-conventions.md").write_text(
        "# REST Conventions\nUse plural nouns for resources.\n"
    )
    (api_dir / "authentication.md").write_text("# Authentication\nUse JWT tokens.\n")

    # Create registry.yaml
    (work / "registry.yaml").write_text(
        "id: 7348a577b60f490ba872367ed8e41371\n"
        "packages:\n"
        "  base:\n"
        "    description: Universal coding conventions\n"
        "    classification: evergreen\n"
        "    tags:\n      - core\n      - conventions\n"
        "    path: packages/base\n"
        "  git-conventions:\n"
        "    description: Git commit message standards\n"
        "    classification: evergreen\n"
        "    tags:\n      - git\n"
        "    path: packages/git-conventions\n"
        "    parent: base\n"
        "  api-patterns:\n"
        "    description: REST API patterns and auth\n"
        "    classification: seasonal\n"
        "    tags:\n      - api\n      - rest\n"
        "    path: packages/api-patterns\n"
        "    depends_on:\n      - base\n"
    )

    # Create packages/session-mgmt/ (with subdirectories)
    sm_dir = work / "packages" / "session-mgmt"
    sm_dir.mkdir(parents=True)
    (sm_dir / "package.yaml").write_text(
        "name: session-mgmt\n"
        "description: Session management with subdirectories\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - session\n"
    )
    cmd_dir = sm_dir / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "start-session.md").write_text("# Start Session\nLoad context.\n")
    (cmd_dir / "end-session.md").write_text("# End Session\nPersist knowledge.\n")
    tpl_dir = sm_dir / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "AGENTS.md").write_text("# Agent Memory\n")
    (tpl_dir / "STATUS.md").write_text("# Status\n")

    # Create community/.gitkeep
    community = work / "community"
    community.mkdir()
    (community / ".gitkeep").write_text("")

    # Update registry.yaml to include session-mgmt
    (work / "registry.yaml").write_text(
        "id: 7348a577b60f490ba872367ed8e41371\n"
        "packages:\n"
        "  base:\n"
        "    description: Universal coding conventions\n"
        "    classification: evergreen\n"
        "    tags:\n      - core\n      - conventions\n"
        "    path: packages/base\n"
        "  git-conventions:\n"
        "    description: Git commit message standards\n"
        "    classification: evergreen\n"
        "    tags:\n      - git\n"
        "    path: packages/git-conventions\n"
        "    parent: base\n"
        "  api-patterns:\n"
        "    description: REST API patterns and auth\n"
        "    classification: seasonal\n"
        "    tags:\n      - api\n      - rest\n"
        "    path: packages/api-patterns\n"
        "    depends_on:\n      - base\n"
        "  session-mgmt:\n"
        "    description: Session management with subdirectories\n"
        "    classification: evergreen\n"
        "    tags:\n      - session\n"
        "    path: packages/session-mgmt\n"
    )

    _run_git(["add", "."], cwd=work)
    _run_git(["commit", "-m", "Add sample registry"], cwd=work)
    _run_git(["push", "origin", "main"], cwd=work)

    return bare, work


def _create_registry_content(dest: Path) -> None:
    """Create a sample registry directory structure (no git).

    Produces the same structure as registry_repo but as a plain directory.
    """
    # packages/base/
    base_dir = dest / "packages" / "base"
    base_dir.mkdir(parents=True)
    (base_dir / "package.yaml").write_text(
        "name: base\n"
        "description: Universal coding conventions\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - core\n  - conventions\n"
    )
    (base_dir / "safe-deletion.md").write_text("# Safe Deletion\nAlways use soft deletes.\n")

    # packages/git-conventions/
    git_dir = dest / "packages" / "git-conventions"
    git_dir.mkdir(parents=True)
    (git_dir / "package.yaml").write_text(
        "name: git-conventions\n"
        "description: Git commit message standards\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "parent: base\n"
        "tags:\n  - git\n"
    )
    (git_dir / "commit-messages.md").write_text("# Commit Messages\nUse conventional commits.\n")

    # packages/api-patterns/
    api_dir = dest / "packages" / "api-patterns"
    api_dir.mkdir(parents=True)
    (api_dir / "package.yaml").write_text(
        "name: api-patterns\n"
        "description: REST API patterns and auth\n"
        "authors:\n  - Test Author\n"
        "classification: seasonal\n"
        "depends_on:\n  - base\n"
        "tags:\n  - api\n  - rest\n"
        "content:\n  - rest-conventions.md\n  - authentication.md\n"
    )
    (api_dir / "rest-conventions.md").write_text(
        "# REST Conventions\nUse plural nouns for resources.\n"
    )
    (api_dir / "authentication.md").write_text("# Authentication\nUse JWT tokens.\n")

    # packages/session-mgmt/ (with subdirectories)
    sm_dir = dest / "packages" / "session-mgmt"
    sm_dir.mkdir(parents=True)
    (sm_dir / "package.yaml").write_text(
        "name: session-mgmt\n"
        "description: Session management with subdirectories\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - session\n"
    )
    cmd_dir = sm_dir / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "start-session.md").write_text("# Start Session\nLoad context.\n")
    (cmd_dir / "end-session.md").write_text("# End Session\nPersist knowledge.\n")
    tpl_dir = sm_dir / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "AGENTS.md").write_text("# Agent Memory\n")
    (tpl_dir / "STATUS.md").write_text("# Status\n")

    # registry.yaml
    (dest / "registry.yaml").write_text(
        "id: 7348a577b60f490ba872367ed8e41371\n"
        "packages:\n"
        "  base:\n"
        "    description: Universal coding conventions\n"
        "    classification: evergreen\n"
        "    tags:\n      - core\n      - conventions\n"
        "    path: packages/base\n"
        "  git-conventions:\n"
        "    description: Git commit message standards\n"
        "    classification: evergreen\n"
        "    tags:\n      - git\n"
        "    path: packages/git-conventions\n"
        "    parent: base\n"
        "  api-patterns:\n"
        "    description: REST API patterns and auth\n"
        "    classification: seasonal\n"
        "    tags:\n      - api\n      - rest\n"
        "    path: packages/api-patterns\n"
        "    depends_on:\n      - base\n"
        "  session-mgmt:\n"
        "    description: Session management with subdirectories\n"
        "    classification: evergreen\n"
        "    tags:\n      - session\n"
        "    path: packages/session-mgmt\n"
    )


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    """Create a plain directory (no git) with registry structure.

    Returns the path to the directory.
    """
    plain = tmp_path / "plain-registry"
    plain.mkdir()
    _create_registry_content(plain)
    return plain


@pytest.fixture
def registry_archive_tar_gz(registry_dir: Path, tmp_path: Path) -> Path:
    """Create a .tar.gz archive from the registry directory (root-level layout).

    Returns the path to the archive file.
    """
    archive_path = tmp_path / "registry.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        for item in sorted(registry_dir.iterdir()):
            tf.add(item, arcname=item.name)
    return archive_path


@pytest.fixture
def registry_archive_zip(registry_dir: Path, tmp_path: Path) -> Path:
    """Create a .zip archive from the registry directory (root-level layout).

    Returns the path to the archive file.
    """
    archive_path = tmp_path / "registry.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(registry_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(registry_dir))
    return archive_path


@pytest.fixture
def registry_archive_nested(registry_dir: Path, tmp_path: Path) -> Path:
    """Create a .tar.gz archive with contents one level under a wrapper dir.

    Returns the path to the archive file.
    """
    archive_path = tmp_path / "registry-nested.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        for item in sorted(registry_dir.iterdir()):
            tf.add(item, arcname=f"my-registry/{item.name}")
    return archive_path


@pytest.fixture
def second_registry_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a second bare repo with different packages (internal-rules, company-standards).

    Returns (bare_repo_path, working_clone_path).
    """
    bare = tmp_path / "second-registry.git"
    bare.mkdir()
    _run_git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    work = tmp_path / "second-registry-work"
    _run_git(["clone", str(bare), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test User"], cwd=work)

    # Create packages/internal-rules/
    ir_dir = work / "packages" / "internal-rules"
    ir_dir.mkdir(parents=True)
    (ir_dir / "package.yaml").write_text(
        "name: internal-rules\n"
        "description: Company internal coding rules\n"
        "authors:\n  - Internal Team\n"
        "classification: evergreen\n"
        "tags:\n  - internal\n  - rules\n"
    )
    (ir_dir / "code-style.md").write_text("# Code Style\nUse 4-space indentation.\n")

    # Create packages/company-standards/
    cs_dir = work / "packages" / "company-standards"
    cs_dir.mkdir(parents=True)
    (cs_dir / "package.yaml").write_text(
        "name: company-standards\n"
        "description: Company-wide development standards\n"
        "authors:\n  - Standards Team\n"
        "classification: seasonal\n"
        "depends_on:\n  - internal-rules\n"
        "tags:\n  - company\n  - standards\n"
    )
    (cs_dir / "standards.md").write_text("# Standards\nFollow the company handbook.\n")

    # Create registry.yaml
    (work / "registry.yaml").write_text(
        "id: 8512b48c8a9b44a7a2c2ece8e6201279\n"
        "packages:\n"
        "  internal-rules:\n"
        "    description: Company internal coding rules\n"
        "    classification: evergreen\n"
        "    tags:\n      - internal\n      - rules\n"
        "    path: packages/internal-rules\n"
        "  company-standards:\n"
        "    description: Company-wide development standards\n"
        "    classification: seasonal\n"
        "    tags:\n      - company\n      - standards\n"
        "    path: packages/company-standards\n"
        "    depends_on:\n      - internal-rules\n"
    )

    # Create community/.gitkeep
    community = work / "community"
    community.mkdir()
    (community / ".gitkeep").write_text("")

    _run_git(["add", "."], cwd=work)
    _run_git(["commit", "-m", "Add second registry"], cwd=work)
    _run_git(["push", "origin", "main"], cwd=work)

    return bare, work


def _create_second_registry_content(dest: Path) -> None:
    """Create a second registry directory structure (no git)."""
    ir_dir = dest / "packages" / "internal-rules"
    ir_dir.mkdir(parents=True)
    (ir_dir / "package.yaml").write_text(
        "name: internal-rules\n"
        "description: Company internal coding rules\n"
        "authors:\n  - Internal Team\n"
        "classification: evergreen\n"
        "tags:\n  - internal\n  - rules\n"
    )
    (ir_dir / "code-style.md").write_text("# Code Style\nUse 4-space indentation.\n")

    cs_dir = dest / "packages" / "company-standards"
    cs_dir.mkdir(parents=True)
    (cs_dir / "package.yaml").write_text(
        "name: company-standards\n"
        "description: Company-wide development standards\n"
        "authors:\n  - Standards Team\n"
        "classification: seasonal\n"
        "depends_on:\n  - internal-rules\n"
        "tags:\n  - company\n  - standards\n"
    )
    (cs_dir / "standards.md").write_text("# Standards\nFollow the company handbook.\n")

    (dest / "registry.yaml").write_text(
        "id: 8512b48c8a9b44a7a2c2ece8e6201279\n"
        "packages:\n"
        "  internal-rules:\n"
        "    description: Company internal coding rules\n"
        "    classification: evergreen\n"
        "    tags:\n      - internal\n      - rules\n"
        "    path: packages/internal-rules\n"
        "  company-standards:\n"
        "    description: Company-wide development standards\n"
        "    classification: seasonal\n"
        "    tags:\n      - company\n      - standards\n"
        "    path: packages/company-standards\n"
        "    depends_on:\n      - internal-rules\n"
    )


@pytest.fixture
def second_registry_dir(tmp_path: Path) -> Path:
    """Create a plain directory (no git) with second registry structure."""
    plain = tmp_path / "second-plain-registry"
    plain.mkdir()
    _create_second_registry_content(plain)
    return plain


@pytest.fixture
def cli_runner():
    """Click test runner."""
    from click.testing import CliRunner

    return CliRunner()
