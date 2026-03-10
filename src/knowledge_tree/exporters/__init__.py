"""Tool-specific exporters for Knowledge Tree packages."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from knowledge_tree.models import CommandEntry, ContentItem, PackageMetadata


@dataclass
class ExportResult:
    """Result of exporting a single package."""

    package_name: str = ""
    files_written: list[Path] = field(default_factory=list)
    files_skipped: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class UnexportResult:
    """Result of removing exported files for a package."""

    package_name: str = ""
    files_removed: list[Path] = field(default_factory=list)


class Exporter(ABC):
    """Base class for tool-specific exporters."""

    name: str = ""
    description: str = ""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    @abstractmethod
    def export_package(
        self,
        package_name: str,
        source_dir: Path,
        metadata: PackageMetadata,
        force: bool = False,
        registry_name: str = "default",
    ) -> ExportResult:
        """Export a single package to tool-specific format."""
        ...

    @abstractmethod
    def unexport_package(
        self,
        package_name: str,
        registry_name: str = "default",
    ) -> UnexportResult:
        """Remove exported files for a package."""
        ...

    def export_commands(
        self,
        package_name: str,
        commands: list[tuple[CommandEntry, Path]],
        registry_name: str = "default",
    ) -> ExportResult:
        """Export command entries as tool-specific skills. Default: no-op."""
        return ExportResult(package_name=package_name)

    def unexport_commands(
        self,
        package_name: str,
        command_names: list[str] | None = None,
        registry_name: str = "default",
    ) -> UnexportResult:
        """Remove exported command skills. Default: no-op."""
        return UnexportResult(package_name=package_name)

    def _resolve_content_type(
        self,
        item: ContentItem,
        metadata: PackageMetadata,
    ) -> str:
        """Resolve the effective content type for a content item.

        Priority: per-file export_hint > package export_hint > content_type > "knowledge".
        """
        # Per-file hint for this exporter
        if self.name in item.export_hints:
            return item.export_hints[self.name]
        # Package-level hint for this exporter
        if self.name in metadata.export_hints:
            return metadata.export_hints[self.name]
        # Package content_type (default: knowledge)
        return metadata.content_type or "knowledge"


# -----------------------------------------------------------------------
# Exporter registry
# -----------------------------------------------------------------------

# Lazy imports to avoid circular dependencies and keep startup fast.
# Each value is a tuple of (module_path, class_name, description).
_EXPORTER_REGISTRY: dict[str, tuple[str, str, str]] = {
    "claude-code": (
        "knowledge_tree.exporters.claude_code",
        "ClaudeCodeExporter",
        "Claude Code",
    ),
    "roo-code": (
        "knowledge_tree.exporters.roo_code",
        "RooCodeExporter",
        "Roo Code",
    ),
}


def get_exporter(name: str, project_root: Path) -> Exporter:
    """Get an exporter instance by format name.

    Raises ValueError if the format is unknown.
    """
    entry = _EXPORTER_REGISTRY.get(name)
    if entry is None:
        available = ", ".join(sorted(_EXPORTER_REGISTRY))
        raise ValueError(f"Unknown export format '{name}'. Available formats: {available}")
    module_path, class_name, _description = entry
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(project_root)


def list_formats() -> list[tuple[str, str]]:
    """Return list of (format_name, description) for all registered exporters."""
    return [(name, desc) for name, (_mod, _cls, desc) in sorted(_EXPORTER_REGISTRY.items())]
