"""Tests for registry_source module."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from knowledge_tree.registry_source import (
    _find_registry_root,
    _hash_file,
    _safe_zip_extract,
    detect_source_type,
    populate_cache,
)

# ---------------------------------------------------------------------------
# detect_source_type
# ---------------------------------------------------------------------------


class TestDetectSourceType:
    def test_https_url(self) -> None:
        assert detect_source_type("https://github.com/user/repo") == "git"

    def test_http_url(self) -> None:
        assert detect_source_type("http://github.com/user/repo") == "git"

    def test_ssh_url(self) -> None:
        assert detect_source_type("ssh://git@github.com/user/repo") == "git"

    def test_git_at_url(self) -> None:
        assert detect_source_type("git@github.com:user/repo.git") == "git"

    def test_git_protocol_url(self) -> None:
        assert detect_source_type("git://github.com/user/repo") == "git"

    def test_file_url(self) -> None:
        assert detect_source_type("file:///tmp/my-repo") == "git"

    def test_archive_tar_gz(self, tmp_path: Path) -> None:
        archive = tmp_path / "registry.tar.gz"
        archive.write_bytes(b"fake")
        assert detect_source_type(str(archive)) == "archive"

    def test_archive_tgz(self, tmp_path: Path) -> None:
        archive = tmp_path / "registry.tgz"
        archive.write_bytes(b"fake")
        assert detect_source_type(str(archive)) == "archive"

    def test_archive_zip(self, tmp_path: Path) -> None:
        archive = tmp_path / "registry.zip"
        archive.write_bytes(b"fake")
        assert detect_source_type(str(archive)) == "archive"

    def test_archive_extension_nonexistent_file(self, tmp_path: Path) -> None:
        """A .tar.gz path that doesn't exist should raise ValueError."""
        with pytest.raises(ValueError, match="Cannot determine source type"):
            detect_source_type(str(tmp_path / "nope.tar.gz"))

    def test_local_directory(self, tmp_path: Path) -> None:
        plain = tmp_path / "my-dir"
        plain.mkdir()
        assert detect_source_type(str(plain)) == "local"

    def test_local_git_repo(self, tmp_path: Path) -> None:
        repo = tmp_path / "my-repo"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repo,
            capture_output=True,
        )
        assert detect_source_type(str(repo)) == "git"

    def test_nonexistent_path(self) -> None:
        with pytest.raises(ValueError, match="Cannot determine source type"):
            detect_source_type("/does/not/exist")


# ---------------------------------------------------------------------------
# _find_registry_root
# ---------------------------------------------------------------------------


class TestFindRegistryRoot:
    def test_root_level_registry_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "registry.yaml").write_text("packages: {}")
        assert _find_registry_root(tmp_path) == tmp_path

    def test_root_level_packages_dir(self, tmp_path: Path) -> None:
        (tmp_path / "packages").mkdir()
        assert _find_registry_root(tmp_path) == tmp_path

    def test_one_level_under_registry_yaml(self, tmp_path: Path) -> None:
        wrapper = tmp_path / "my-registry"
        wrapper.mkdir()
        (wrapper / "registry.yaml").write_text("packages: {}")
        assert _find_registry_root(tmp_path) == wrapper

    def test_one_level_under_packages_dir(self, tmp_path: Path) -> None:
        wrapper = tmp_path / "my-registry"
        wrapper.mkdir()
        (wrapper / "packages").mkdir()
        assert _find_registry_root(tmp_path) == wrapper

    def test_multiple_top_level_dirs_fails(self, tmp_path: Path) -> None:
        (tmp_path / "dir-a").mkdir()
        (tmp_path / "dir-b").mkdir()
        with pytest.raises(ValueError, match="does not contain a valid registry"):
            _find_registry_root(tmp_path)

    def test_empty_dir_fails(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ValueError, match="does not contain a valid registry"):
            _find_registry_root(empty)

    def test_single_dir_without_markers_fails(self, tmp_path: Path) -> None:
        wrapper = tmp_path / "wrapper"
        wrapper.mkdir()
        (wrapper / "random.txt").write_text("nothing")
        with pytest.raises(ValueError, match="does not contain a valid registry"):
            _find_registry_root(tmp_path)


# ---------------------------------------------------------------------------
# Path traversal safety
# ---------------------------------------------------------------------------


class TestSafeZipExtract:
    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("/etc/passwd", "root:x:0:0")
        with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="Unsafe path"):
            _safe_zip_extract(zf, tmp_path / "out")

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../../etc/crontab", "malicious")
        with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="Unsafe path"):
            _safe_zip_extract(zf, tmp_path / "out")

    def test_allows_normal_paths(self, tmp_path: Path) -> None:
        archive = tmp_path / "safe.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("packages/base/readme.md", "# Hello")
        dest = tmp_path / "out"
        with zipfile.ZipFile(archive) as zf:
            _safe_zip_extract(zf, dest)
        assert (dest / "packages" / "base" / "readme.md").exists()


# ---------------------------------------------------------------------------
# _hash_file
# ---------------------------------------------------------------------------


class TestHashFile:
    def test_deterministic(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        assert _hash_file(f) == _hash_file(f)

    def test_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f1.write_bytes(b"hello")
        f2 = tmp_path / "b.bin"
        f2.write_bytes(b"world")
        assert _hash_file(f1) != _hash_file(f2)

    def test_returns_hex_string(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"data")
        h = _hash_file(f)
        assert len(h) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# populate_cache
# ---------------------------------------------------------------------------


class TestPopulateCache:
    def test_git_clone(self, registry_repo: tuple[Path, Path], tmp_path: Path) -> None:
        bare, _ = registry_repo
        dest = tmp_path / "cache"
        ref = populate_cache(str(bare), dest, "main", "git")
        assert len(ref) == 7
        assert (dest / "registry.yaml").exists()
        assert (dest / "packages" / "base" / "package.yaml").exists()

    def test_local_copy(self, registry_dir: Path, tmp_path: Path) -> None:
        dest = tmp_path / "cache"
        ref = populate_cache(str(registry_dir), dest, "", "local")
        assert ref == "local"
        assert (dest / "registry.yaml").exists()
        assert (dest / "packages" / "base" / "package.yaml").exists()

    def test_archive_tar_gz(self, registry_archive_tar_gz: Path, tmp_path: Path) -> None:
        dest = tmp_path / "cache"
        ref = populate_cache(str(registry_archive_tar_gz), dest, "", "archive")
        assert len(ref) == 7
        assert (dest / "registry.yaml").exists()
        assert (dest / "packages" / "base" / "package.yaml").exists()

    def test_archive_zip(self, registry_archive_zip: Path, tmp_path: Path) -> None:
        dest = tmp_path / "cache"
        ref = populate_cache(str(registry_archive_zip), dest, "", "archive")
        assert len(ref) == 7
        assert (dest / "registry.yaml").exists()

    def test_archive_nested_root(self, registry_archive_nested: Path, tmp_path: Path) -> None:
        dest = tmp_path / "cache"
        ref = populate_cache(str(registry_archive_nested), dest, "", "archive")
        assert len(ref) == 7
        assert (dest / "registry.yaml").exists()
        assert (dest / "packages" / "base" / "package.yaml").exists()

    def test_local_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            populate_cache(str(tmp_path / "nope"), tmp_path / "cache", "", "local")

    def test_archive_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            populate_cache(str(tmp_path / "nope.tar.gz"), tmp_path / "cache", "", "archive")

    def test_unknown_type_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown source type"):
            populate_cache(str(tmp_path), tmp_path / "cache", "", "ftp")


# refresh_cache removed — update now uses nuke-and-reclone via populate_cache
