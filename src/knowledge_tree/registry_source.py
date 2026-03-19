"""Registry source detection, cache population, and refresh logic.

Supports three source types:
  - "git": remote or local git repository
  - "local": plain directory (no git)
  - "archive": .tar.gz, .tgz, or .zip file (local path or remote URL)
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from knowledge_tree import git_ops

ARCHIVE_EXTENSIONS = (".tar.gz", ".tgz", ".zip")
_URL_PREFIXES = ("http://", "https://", "ssh://", "git://", "git@", "file://")


def detect_source_type(source: str) -> str:
    """Detect registry source type from a user-provided string.

    Returns "git", "local", or "archive".
    Raises ValueError if the source cannot be classified.
    """
    has_archive_ext = any(source.endswith(ext) for ext in ARCHIVE_EXTENSIONS)

    # Archive file — local path
    if has_archive_ext and Path(source).is_file():
        return "archive"

    # Archive URL — remote download
    if has_archive_ext and any(source.startswith(p) for p in ("http://", "https://")):
        return "archive"

    # URL → git
    if any(source.startswith(prefix) for prefix in _URL_PREFIXES):
        return "git"

    path = Path(source)

    # Existing directory
    if path.is_dir():
        if git_ops.is_git_repo(path):
            return "git"
        return "local"

    raise ValueError(
        f"Cannot determine source type for '{source}'. "
        "Provide a URL, directory path, or archive file (.tar.gz, .tgz, .zip)."
    )


def populate_cache(
    source: str,
    dest: Path,
    branch: str,
    source_type: str,
) -> str:
    """Populate the registry cache directory from a source.

    Returns a ref string suitable for config storage.
    """
    if source_type == "git":
        git_ops.clone(url=source, dest=dest, branch=branch, depth=1)
        return git_ops.get_short_ref(dest)

    if source_type == "local":
        _copy_directory(Path(source), dest)
        return "local"

    if source_type == "archive":
        archive_path = _resolve_archive(source)
        try:
            _extract_archive(archive_path, dest)
            return _hash_file(archive_path)[:7]
        finally:
            # Clean up temp file if we downloaded it
            if archive_path != Path(source):
                archive_path.unlink(missing_ok=True)

    raise ValueError(f"Unknown source type: {source_type}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_archive(source: str) -> Path:
    """Return a local Path to the archive, downloading if it's a URL."""
    if any(source.startswith(p) for p in ("http://", "https://")):
        return _download_archive(source)
    return Path(source)


def _download_archive(url: str) -> Path:
    """Download a remote archive to a temporary file and return its path."""
    # Determine suffix for the temp file
    suffix = ".tar.gz"
    for ext in ARCHIVE_EXTENSIONS:
        if url.endswith(ext):
            suffix = ext
            break

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=suffix)
    try:
        with urllib.request.urlopen(url) as resp, open(tmp_fd, "wb") as tmp_f:
            shutil.copyfileobj(resp, tmp_f)
        return Path(tmp_name)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def strip_source_suffix(name: str) -> str:
    """Strip known source suffixes (.git, archive extensions) from a name."""
    for ext in ARCHIVE_EXTENSIONS:
        if name.endswith(ext):
            return name[: -len(ext)]
    return name.replace(".git", "")


def _copy_directory(src: Path, dest: Path) -> None:
    """Copy a directory's contents to dest."""
    if not src.is_dir():
        raise FileNotFoundError(f"Source directory not found: {src}")
    shutil.copytree(src, dest)


def _extract_archive(archive_path: Path, dest: Path) -> None:
    """Extract an archive to dest, handling root detection."""
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive file not found: {archive_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        if str(archive_path).endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                _safe_zip_extract(zf, tmp_path)
        else:
            with tarfile.open(archive_path) as tf:
                _safe_tar_extract(tf, tmp_path)

        root = _find_registry_root(tmp_path)
        shutil.copytree(root, dest)


def _safe_zip_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zipfile safely, guarding against path traversal."""
    for info in zf.infolist():
        member_path = Path(info.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError(f"Unsafe path in archive: {info.filename}")
    zf.extractall(dest)


def _safe_tar_extract(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract a tarfile safely, guarding against path traversal."""
    if hasattr(tarfile, "data_filter"):
        # Python 3.12+
        tf.extractall(dest, filter="data")
    else:
        for member in tf.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in archive: {member.name}")
        tf.extractall(dest)


def _find_registry_root(extracted_dir: Path) -> Path:
    """Find the actual registry root inside an extracted archive.

    Checks for registry.yaml or packages/ at root level.
    If not found, checks one level under (single top-level directory).
    """
    # Check root level
    if (extracted_dir / "registry.yaml").exists() or (extracted_dir / "packages").is_dir():
        return extracted_dir

    # Check one level under: look for a single subdirectory
    entries = [e for e in extracted_dir.iterdir() if e.is_dir()]
    if len(entries) == 1:
        candidate = entries[0]
        if (candidate / "registry.yaml").exists() or (candidate / "packages").is_dir():
            return candidate

    raise ValueError(
        "Archive does not contain a valid registry. "
        "Expected registry.yaml or packages/ at root or one level under."
    )


def _hash_file(path: Path) -> str:
    """Return hex SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
