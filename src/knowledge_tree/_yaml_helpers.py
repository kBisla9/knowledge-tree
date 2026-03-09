"""Centralized YAML load/save using ruamel.yaml."""

from pathlib import Path

from ruamel.yaml import YAML, YAMLError


def load_yaml(path: Path) -> dict:
    """Load a YAML file and return its contents as a dict.

    Returns an empty dict for empty or nonexistent content.
    Raises ValueError with a clear message on corrupted YAML.
    Raises FileNotFoundError if the file does not exist.
    Raises PermissionError/OSError on I/O errors.
    """
    yaml = YAML()
    try:
        with open(path) as f:
            data = yaml.load(f)
    except YAMLError as exc:
        raise ValueError(f"Corrupted YAML in {path.name}: {exc}") from exc
    return data if data is not None else {}


def save_yaml(data: dict, path: Path) -> None:
    """Save a dict to a YAML file.

    Creates parent directories if they don't exist.
    Uses block style (no flow style).
    Raises OSError on permission or disk-full errors.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Cannot create directory {path.parent}: {exc}") from exc
    yaml = YAML()
    yaml.default_flow_style = False
    try:
        with open(path, "w") as f:
            yaml.dump(data, f)
    except OSError as exc:
        raise OSError(f"Cannot write {path.name}: {exc}") from exc
