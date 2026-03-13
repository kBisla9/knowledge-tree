"""Data models for Knowledge Tree."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from knowledge_tree._yaml_helpers import load_yaml, save_yaml

# Valid package name: lowercase letters, digits, hyphens. Must start with letter.
# Examples: "base", "git-conventions", "cloud-aws-lambda"
PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

_UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def _is_valid_uuid_hex(value: str) -> bool:
    """Check if value is a valid 32-char lowercase hex UUID."""
    return bool(_UUID_HEX_RE.match(value))


VALID_CLASSIFICATIONS = {"evergreen", "seasonal"}
VALID_CONTENT_TYPES = {"knowledge", "skills", "commands"}
VALID_EXPORT_HINT_VALUES = {"knowledge", "skills", "commands"}
VALID_STATUSES = {"pending", "promoted", "archived"}


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(prev_row[j + 1] + 1, curr_row[j] + 1, prev_row[j] + cost))
        prev_row = curr_row
    return prev_row[-1]


# ---------------------------------------------------------------------------
# ContentItem / CommandEntry / TemplateMapping
# ---------------------------------------------------------------------------


@dataclass
class ContentItem:
    """A content file entry, optionally with metadata and export hints.

    Simple packages list content as plain strings (e.g., ``["overview.md"]``).
    Rich entries add per-file description and/or export hints::

        content:
          - overview.md
          - file: api-reference.md
            description: API reference for on-demand lookup
            export_hints:
              roo-code: skills
    """

    file: str = ""
    description: str = ""  # explicit description (used for skill metadata)
    export_hints: dict[str, str] = field(default_factory=dict)


@dataclass
class CommandEntry:
    """A slash command declared in a package."""

    name: str = ""
    description: str = ""  # empty = extract from file


@dataclass
class TemplateMapping:
    """A template file to scaffold into the project."""

    source: str = ""  # relative to registry root
    dest: str = ""  # relative to project root


# ---------------------------------------------------------------------------
# PackageMetadata
# ---------------------------------------------------------------------------


@dataclass
class PackageMetadata:
    """Represents a package.yaml file."""

    # Required fields
    name: str = ""
    description: str = ""
    authors: list[str] = field(default_factory=list)
    classification: str = ""

    # Optional relationship fields
    parent: str | None = None
    suggests: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    audience: list[str] = field(default_factory=list)
    content: list[ContentItem] = field(default_factory=list)
    content_type: str = ""  # "knowledge" (default) or "skills"
    export_hints: dict[str, str] = field(default_factory=dict)  # tool-name → generic type
    commands: list[CommandEntry] = field(default_factory=list)

    # Optional dates
    created: str | None = None
    updated: str | None = None

    # Community-only fields (Phase 2, defined now to avoid migration)
    status: str | None = None
    promoted_to: str | None = None
    promoted_date: str | None = None

    def validate(self) -> list[str]:
        """Return a list of validation error strings. Empty list = valid."""
        errors: list[str] = []

        if not self.name:
            errors.append("'name' is required")
        elif not PACKAGE_NAME_RE.match(self.name):
            errors.append(
                f"Invalid package name '{self.name}'. "
                "Must be lowercase kebab-case (e.g., 'cloud-aws')."
            )

        if not self.description:
            errors.append("'description' is required")

        if not self.authors:
            errors.append("At least one author is required")

        if self.classification and self.classification not in VALID_CLASSIFICATIONS:
            errors.append(
                f"Invalid classification '{self.classification}'. "
                f"Must be one of: {', '.join(sorted(VALID_CLASSIFICATIONS))}"
            )

        if self.content_type and self.content_type not in VALID_CONTENT_TYPES:
            errors.append(
                f"Invalid content_type '{self.content_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_CONTENT_TYPES))}"
            )

        for tool_name, hint_value in self.export_hints.items():
            if hint_value not in VALID_EXPORT_HINT_VALUES:
                errors.append(
                    f"Invalid export_hints value '{hint_value}' for tool '{tool_name}'. "
                    f"Must be one of: {', '.join(sorted(VALID_EXPORT_HINT_VALUES))}"
                )

        for item in self.content:
            for tool_name, hint_value in item.export_hints.items():
                if hint_value not in VALID_EXPORT_HINT_VALUES:
                    errors.append(
                        f"Invalid export_hints value '{hint_value}' for file '{item.file}' "
                        f"tool '{tool_name}'. "
                        f"Must be one of: {', '.join(sorted(VALID_EXPORT_HINT_VALUES))}"
                    )

        if self.status is not None and self.status not in VALID_STATUSES:
            errors.append(
                f"Invalid status '{self.status}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )

        return errors

    @classmethod
    def from_yaml_file(cls, path: Path) -> PackageMetadata:
        """Load a PackageMetadata from a package.yaml file."""
        data = load_yaml(path)

        # Parse content: mixed list of strings and dicts
        content_items: list[ContentItem] = []
        for item in data.get("content", []):
            if isinstance(item, str):
                content_items.append(ContentItem(file=item))
            elif isinstance(item, dict):
                content_items.append(
                    ContentItem(
                        file=item.get("file", ""),
                        description=item.get("description", ""),
                        export_hints=dict(item.get("export_hints", {})),
                    )
                )

        # Parse commands: mixed list of strings and dicts
        commands: list[CommandEntry] = []
        for item in data.get("commands", []):
            if isinstance(item, str):
                commands.append(CommandEntry(name=item))
            elif isinstance(item, dict):
                commands.append(
                    CommandEntry(
                        name=item.get("name", ""),
                        description=item.get("description", ""),
                    )
                )

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            authors=list(data.get("authors", [])),
            classification=data.get("classification", "seasonal"),
            parent=data.get("parent"),
            suggests=list(data.get("suggests", [])),
            tags=list(data.get("tags", [])),
            audience=list(data.get("audience", [])),
            content=content_items,
            content_type=data.get("content_type", ""),
            export_hints=dict(data.get("export_hints", {})),
            commands=commands,
            created=data.get("created"),
            updated=data.get("updated"),
            status=data.get("status"),
            promoted_to=data.get("promoted_to"),
            promoted_date=data.get("promoted_date"),
        )

    def to_yaml_file(self, path: Path) -> None:
        """Save this PackageMetadata to a package.yaml file.

        Omits fields that are None or empty lists (keeps output clean).
        """
        data: dict = {}
        data["name"] = self.name
        data["description"] = self.description
        data["authors"] = self.authors
        data["classification"] = self.classification

        if self.parent is not None:
            data["parent"] = self.parent
        if self.suggests:
            data["suggests"] = self.suggests
        if self.tags:
            data["tags"] = self.tags
        if self.audience:
            data["audience"] = self.audience
        if self.content:
            content_out: list = []
            for item in self.content:
                if not item.description and not item.export_hints:
                    content_out.append(item.file)
                else:
                    d: dict = {"file": item.file}
                    if item.description:
                        d["description"] = item.description
                    if item.export_hints:
                        d["export_hints"] = dict(item.export_hints)
                    content_out.append(d)
            data["content"] = content_out
        if self.content_type:
            data["content_type"] = self.content_type
        if self.export_hints:
            data["export_hints"] = dict(self.export_hints)
        if self.commands:
            cmds: list = []
            for cmd in self.commands:
                d: dict = {"name": cmd.name}
                if cmd.description:
                    d["description"] = cmd.description
                cmds.append(d)
            data["commands"] = cmds
        if self.created is not None:
            data["created"] = self.created
        if self.updated is not None:
            data["updated"] = self.updated
        if self.status is not None:
            data["status"] = self.status
        if self.promoted_to is not None:
            data["promoted_to"] = self.promoted_to
        if self.promoted_date is not None:
            data["promoted_date"] = self.promoted_date

        save_yaml(data, path)


# ---------------------------------------------------------------------------
# RegistryEntry
# ---------------------------------------------------------------------------


@dataclass
class RegistryEntry:
    """Lightweight entry for registry.yaml."""

    description: str = ""
    classification: str = ""
    tags: list[str] = field(default_factory=list)
    path: str = ""
    parent: str | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class Registry:
    """The full registry index, loaded from registry.yaml."""

    id: str = ""  # canonical UUID hex (32 chars), declared by registry author
    packages: dict[str, RegistryEntry] = field(default_factory=dict)
    templates: list[TemplateMapping] = field(default_factory=list)

    @classmethod
    def from_yaml_file(cls, path: Path) -> Registry:
        """Load a Registry from registry.yaml."""
        data = load_yaml(path)
        packages_data = data.get("packages", {})
        packages: dict[str, RegistryEntry] = {}
        for name, entry_data in packages_data.items():
            if not isinstance(entry_data, dict):
                continue
            packages[name] = RegistryEntry(
                description=entry_data.get("description", ""),
                classification=entry_data.get("classification", ""),
                tags=list(entry_data.get("tags", [])),
                path=entry_data.get("path", ""),
                parent=entry_data.get("parent"),
            )

        # Parse registry-level templates
        templates: list[TemplateMapping] = []
        for item in data.get("templates", []):
            if isinstance(item, dict):
                templates.append(
                    TemplateMapping(
                        source=item.get("source", ""),
                        dest=item.get("dest", ""),
                    )
                )

        return cls(id=data.get("id", ""), packages=packages, templates=templates)

    def to_yaml_file(self, path: Path) -> None:
        """Save this Registry to registry.yaml."""
        data: dict = {}
        if self.id:
            data["id"] = self.id
        if self.templates:
            data["templates"] = [{"source": t.source, "dest": t.dest} for t in self.templates]
        packages_data: dict = {}
        for name, entry in self.packages.items():
            entry_data: dict = {
                "description": entry.description,
                "classification": entry.classification,
            }
            if entry.tags:
                entry_data["tags"] = entry.tags
            if entry.path:
                entry_data["path"] = entry.path
            if entry.parent is not None:
                entry_data["parent"] = entry.parent
            packages_data[name] = entry_data
        data["packages"] = packages_data
        save_yaml(data, path)

    def search(self, query: str) -> list[tuple[str, RegistryEntry]]:
        """Search packages by name, description, and tags.

        Returns list of (name, entry) tuples sorted by relevance:
        exact name match > name contains > description contains > tag match.
        """
        query_lower = query.lower()
        results: list[tuple[int, str, RegistryEntry]] = []

        for name, entry in self.packages.items():
            score = 0
            name_lower = name.lower()
            desc_lower = entry.description.lower()
            tags_lower = [t.lower() for t in entry.tags]

            if name_lower == query_lower:
                score = 100
            elif query_lower in name_lower:
                score = 80
            elif query_lower in desc_lower:
                score = 60
            elif any(query_lower in tag for tag in tags_lower):
                score = 40

            if score > 0:
                results.append((score, name, entry))

        results.sort(key=lambda r: (-r[0], r[1]))
        return [(name, entry) for _, name, entry in results]

    def get_children(self, package_name: str) -> list[str]:
        """Return names of packages whose parent is package_name."""
        return [name for name, entry in self.packages.items() if entry.parent == package_name]

    def resolve_ancestor_chain(self, package_name: str) -> list[str]:
        """Return the ancestor chain from root down to package_name (inclusive).

        Walks parent links upward, then reverses so root comes first.
        Raises ValueError on circular parent chain or missing package/parent.
        """
        if package_name not in self.packages:
            similar = self.find_similar_names(package_name)
            msg = f"Package '{package_name}' not found in registry."
            if similar:
                msg += f" Did you mean: {', '.join(similar)}?"
            raise ValueError(msg)

        chain: list[str] = []
        seen: set[str] = set()
        current = package_name

        while current is not None:
            if current in seen:
                raise ValueError(f"Circular parent chain detected involving '{current}'")
            seen.add(current)
            entry = self.packages.get(current)
            if entry is None:
                similar = self.find_similar_names(current)
                msg = f"Parent '{current}' not found in registry."
                if similar:
                    msg += f" Did you mean: {', '.join(similar)}?"
                raise ValueError(msg)
            chain.append(current)
            current = entry.parent

        chain.reverse()
        return chain

    def validate_tree(self) -> list[str]:
        """Validate the entire registry's tree structure.

        Checks that every parent reference exists and there are no cycles.
        Returns a list of error strings (empty = valid).
        """
        errors: list[str] = []
        for name, entry in self.packages.items():
            if entry.parent is not None and entry.parent not in self.packages:
                similar = self.find_similar_names(entry.parent)
                msg = f"Package '{name}' has parent '{entry.parent}' which does not exist."
                if similar:
                    msg += f" Did you mean: {', '.join(similar)}?"
                errors.append(msg)
        # Cycle detection: try resolving each package's ancestor chain
        if not errors:
            for name in self.packages:
                try:
                    self.resolve_ancestor_chain(name)
                except ValueError as e:
                    if "Circular" in str(e):
                        errors.append(str(e))
                        break  # one cycle error is enough
        return errors

    def rebuild_from_packages(self, packages_dir: Path) -> None:
        """Scan packages_dir and rebuild registry entries from package.yaml files.

        Preserves existing templates (they are manually authored, not derived).
        """
        self.packages.clear()
        if not packages_dir.is_dir():
            return
        for pkg_dir in sorted(packages_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            yaml_path = pkg_dir / "package.yaml"
            if not yaml_path.exists():
                continue
            meta = PackageMetadata.from_yaml_file(yaml_path)
            self.packages[meta.name] = RegistryEntry(
                description=meta.description,
                classification=meta.classification,
                tags=list(meta.tags),
                path=f"packages/{pkg_dir.name}",
                parent=meta.parent,
            )

    def validate_id(self) -> list[str]:
        """Validate the registry id. Returns list of error strings."""
        errors: list[str] = []
        if not self.id:
            errors.append(
                "'id' is required in registry.yaml. "
                "Run 'kt author rebuild <path>' to generate one."
            )
        elif not _is_valid_uuid_hex(self.id):
            errors.append(
                f"Invalid registry id '{self.id}'. "
                "Must be a 32-character lowercase hex string (UUID)."
            )
        return errors

    def find_similar_names(self, name: str, threshold: int = 2) -> list[str]:
        """Return package names within edit distance threshold of name."""
        similar: list[tuple[int, str]] = []
        for pkg_name in self.packages:
            dist = _levenshtein(name.lower(), pkg_name.lower())
            if dist <= threshold:
                similar.append((dist, pkg_name))
        similar.sort()
        return [s[1] for s in similar]


# ---------------------------------------------------------------------------
# InstalledPackage
# ---------------------------------------------------------------------------


@dataclass
class InstalledPackage:
    """A package installed in the project, with its pinned git ref."""

    name: str = ""
    ref: str = ""
    registry: str = ""  # registry UUID this package was installed from


# ---------------------------------------------------------------------------
# RegistrySource
# ---------------------------------------------------------------------------


@dataclass
class RegistrySource:
    """A named registry source configuration."""

    id: str = ""  # UUID hex (32 chars from registry.yaml)
    name: str = ""  # user-chosen display name (kebab-case)
    source: str = ""  # URL, directory path, or archive path
    ref: str = ""  # branch for git, empty for local/archive
    type: str = "git"  # "git" | "local" | "archive"


# ---------------------------------------------------------------------------
# ProjectConfig
# ---------------------------------------------------------------------------


VALID_REGISTRY_TYPES = {"git", "local", "archive"}
VALID_EXPORT_FORMATS = {"claude-code", "roo-code"}


# ---------------------------------------------------------------------------
# ExportedPackage
# ---------------------------------------------------------------------------


@dataclass
class ExportedPackage:
    """Tracks a package that has been exported to a tool-specific format."""

    name: str = ""
    format: str = ""  # "claude-code" or "roo-code"
    ref: str = ""  # git ref (or "local"/"archive-hash") at time of export
    registry: str = ""  # registry UUID


@dataclass
class ProjectConfig:
    """Project configuration loaded from .knowledge-tree/kt.yaml."""

    registries: list[RegistrySource] = field(default_factory=list)
    packages: list[InstalledPackage] = field(default_factory=list)
    export_format: str = ""  # default export format (empty = none set)
    exports: list[ExportedPackage] = field(default_factory=list)

    @classmethod
    def from_yaml_file(cls, path: Path) -> ProjectConfig:
        """Load project config from kt.yaml.

        Supports both old format (single registry/registry_ref/registry_type)
        and new format (registries list).
        """
        data = load_yaml(path)

        # --- Registry migration ---
        registries: list[RegistrySource] = []
        if "registries" in data:
            for reg_data in data["registries"]:
                registries.append(
                    RegistrySource(
                        id=reg_data.get("id", ""),
                        name=reg_data.get("name", "default"),
                        source=reg_data.get("source", ""),
                        ref=reg_data.get("ref", ""),
                        type=reg_data.get("type", "git"),
                    )
                )
        elif data.get("registry"):
            # Old format: migrate to single "default" registry
            registries.append(
                RegistrySource(
                    id="",
                    name="default",
                    source=data["registry"],
                    ref=data.get("registry_ref", "main"),
                    type=data.get("registry_type", "git"),
                )
            )

        # --- Packages ---
        packages: list[InstalledPackage] = []
        # Determine default registry id for old-format migration
        default_reg_id = registries[0].id if registries else ""
        for pkg_data in data.get("packages", []):
            packages.append(
                InstalledPackage(
                    name=pkg_data.get("name", ""),
                    ref=pkg_data.get("ref", ""),
                    registry=pkg_data.get("registry", default_reg_id),
                )
            )

        # --- Exports ---
        exports: list[ExportedPackage] = []
        for exp_data in data.get("exports", []):
            exports.append(
                ExportedPackage(
                    name=exp_data.get("name", ""),
                    format=exp_data.get("format", ""),
                    ref=exp_data.get("ref", ""),
                    registry=exp_data.get("registry", default_reg_id),
                )
            )

        return cls(
            registries=registries,
            packages=packages,
            export_format=data.get("export_format", ""),
            exports=exports,
        )

    def to_yaml_file(self, path: Path) -> None:
        """Save project config to kt.yaml (always writes new format)."""
        data: dict = {
            "registries": [
                {
                    "id": r.id,
                    "name": r.name,
                    "source": r.source,
                    "ref": r.ref,
                    "type": r.type,
                }
                for r in self.registries
            ],
            "packages": [
                {"name": pkg.name, "ref": pkg.ref, "registry": pkg.registry}
                for pkg in self.packages
            ],
        }
        if self.export_format:
            data["export_format"] = self.export_format
        if self.exports:
            data["exports"] = [
                {
                    "name": exp.name,
                    "format": exp.format,
                    "ref": exp.ref,
                    "registry": exp.registry,
                }
                for exp in self.exports
            ]
        save_yaml(data, path)

    # --- Registry helpers ---

    def get_registry(self, name: str) -> RegistrySource | None:
        """Get a registry by display name."""
        for r in self.registries:
            if r.name == name:
                return r
        return None

    def get_registry_by_id(self, reg_id: str) -> RegistrySource | None:
        """Get a registry by UUID."""
        for r in self.registries:
            if r.id == reg_id:
                return r
        return None

    def add_registry(self, reg: RegistrySource) -> None:
        """Add a registry. Raises ValueError if name already exists."""
        if self.get_registry(reg.name) is not None:
            raise ValueError(f"Registry '{reg.name}' already exists.")
        self.registries.append(reg)

    def remove_registry(self, name: str) -> bool:
        """Remove a registry by name. Returns True if found and removed."""
        for i, r in enumerate(self.registries):
            if r.name == name:
                self.registries.pop(i)
                return True
        return False

    def get_registry_names(self) -> list[str]:
        """Return ordered list of registry display names."""
        return [r.name for r in self.registries]

    # --- Package helpers ---

    def add_package(self, name: str, ref: str, registry: str = "") -> None:
        """Add or update a package entry. registry is the registry UUID."""
        for pkg in self.packages:
            if pkg.name == name and pkg.registry == registry:
                pkg.ref = ref
                return
        self.packages.append(InstalledPackage(name=name, ref=ref, registry=registry))

    def remove_package(self, name: str, registry: str | None = None) -> bool:
        """Remove a package by name (and optionally registry). Return True if found."""
        for i, pkg in enumerate(self.packages):
            if pkg.name == name and (registry is None or pkg.registry == registry):
                self.packages.pop(i)
                return True
        return False

    def get_installed_names(self) -> set[str]:
        """Return the set of installed package names."""
        return {pkg.name for pkg in self.packages}

    def get_installed_packages_by_registry(self, reg_id: str) -> list[InstalledPackage]:
        """Return installed packages from a specific registry."""
        return [pkg for pkg in self.packages if pkg.registry == reg_id]

    def get_package_ref(self, name: str) -> str | None:
        """Get the ref for an installed package, or None."""
        for pkg in self.packages:
            if pkg.name == name:
                return pkg.ref
        return None

    def get_package_registry(self, name: str) -> str | None:
        """Get the registry UUID for an installed package, or None."""
        for pkg in self.packages:
            if pkg.name == name:
                return pkg.registry
        return None

    # --- Export helpers ---

    def add_export(self, name: str, fmt: str, ref: str, registry: str = "") -> None:
        """Add or update an export entry."""
        for exp in self.exports:
            if exp.name == name and exp.format == fmt and exp.registry == registry:
                exp.ref = ref
                return
        self.exports.append(ExportedPackage(name=name, format=fmt, ref=ref, registry=registry))

    def remove_export(self, name: str, fmt: str | None = None) -> int:
        """Remove export entries for a package. If fmt is None, remove all formats.

        Returns the number of entries removed.
        """
        before = len(self.exports)
        self.exports = [
            exp
            for exp in self.exports
            if not (exp.name == name and (fmt is None or exp.format == fmt))
        ]
        return before - len(self.exports)

    def get_exports(self, fmt: str | None = None) -> list[ExportedPackage]:
        """Return export entries, optionally filtered by format."""
        if fmt is None:
            return list(self.exports)
        return [exp for exp in self.exports if exp.format == fmt]

    def is_exported(self, name: str, fmt: str | None = None) -> bool:
        """Check if a package has been exported."""
        return any(exp.name == name and (fmt is None or exp.format == fmt) for exp in self.exports)


# ---------------------------------------------------------------------------
# Engine result types
# ---------------------------------------------------------------------------


@dataclass
class AddResult:
    """Result of add_package()."""

    installed: list[str] = field(default_factory=list)
    already_installed: list[str] = field(default_factory=list)
    registry: str = ""
    files_exported: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class RemoveResult:
    """Result of remove_package()."""

    removed: bool = False
    children: list[str] = field(default_factory=list)
    unexported: list[str] = field(default_factory=list)


@dataclass
class UpdateResult:
    """Result of update()."""

    updated_packages: list[str] = field(default_factory=list)
    failed_packages: list[str] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)
    new_evergreen: list[str] = field(default_factory=list)
    files_re_exported: int = 0
    format_switched: bool = False
    old_format: str = ""
    new_format: str = ""


@dataclass
class FileInfo:
    """A content file with its line count."""

    name: str = ""
    lines: int = 0


@dataclass
class RegistryInfo:
    """Registry summary for status display."""

    name: str = ""
    source: str = ""
    ref: str = ""
    type: str = ""
    package_count: int = 0


@dataclass
class StatusResult:
    """Result of get_status()."""

    registries: list[RegistryInfo] = field(default_factory=list)
    installed_count: int = 0
    available_count: int = 0
    total_files: int = 0
    total_lines: int = 0
    export_format: str = ""
    exported_count: int = 0


@dataclass
class PackageInfo:
    """Result of get_info()."""

    name: str = ""
    description: str = ""
    classification: str = ""
    tags: list[str] = field(default_factory=list)
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    ancestors: list[str] = field(default_factory=list)
    installed: bool = False
    ref: str = ""
    files: list[FileInfo] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    created: str | None = None
    updated: str | None = None
    exported_to: list[str] = field(default_factory=list)
    registry: str = ""


@dataclass
class ValidateResult:
    """Result of validate_package()."""

    valid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PackageExportResult:
    """Result of export_package()."""

    exported: bool = False
    files_written: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExportAllResult:
    """Result of export_all()."""

    exported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    total_files: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class UnexportPackageResult:
    """Result of unexport_package()."""

    removed: bool = False
    files_removed: list[str] = field(default_factory=list)


@dataclass
class UnexportAllResult:
    """Result of unexport_all()."""

    removed: list[str] = field(default_factory=list)
    total_files: int = 0


@dataclass
class TreeNode:
    """A node in the package tree."""

    name: str = ""
    description: str = ""
    classification: str = ""
    installed: bool = False
    children: list[TreeNode] = field(default_factory=list)
    registry: str = ""


@dataclass
class TreeData:
    """Result of get_tree_data()."""

    roots: list[TreeNode] = field(default_factory=list)


@dataclass
class PackageListEntry:
    """A single entry returned by list_packages()."""

    name: str = ""
    description: str = ""
    classification: str = ""
    tags: list[str] = field(default_factory=list)
    installed: bool = False
    registry: str = ""
    ref: str = ""
    source: str = ""
    status: str = ""


@dataclass
class RegistryPreviewPackage:
    """A package entry in a registry preview."""

    name: str = ""
    description: str = ""
    classification: str = ""  # evergreen / seasonal
    content_type: str = ""  # knowledge / commands
    tags: list[str] = field(default_factory=list)
    parent: str | None = None


@dataclass
class RegistryPreview:
    """Preview of what add_registry() will do, before executing."""

    name: str = ""
    source: str = ""
    source_type: str = ""  # git / local / archive
    packages: list[RegistryPreviewPackage] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)  # dest paths to create
    templates_existing: list[str] = field(default_factory=list)  # already exist


@dataclass
class RegistryAddResult:
    """Result of add_registry()."""

    name: str = ""
    source: str = ""
    available_packages: list[str] = field(default_factory=list)
    packages_installed: list[str] = field(default_factory=list)
    packages_skipped: list[str] = field(default_factory=list)
    commands_installed: list[str] = field(default_factory=list)
    files_exported: int = 0
    templates_instantiated: list[str] = field(default_factory=list)
    templates_skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SearchResultEntry:
    """A single entry returned by search()."""

    name: str = ""
    description: str = ""
    classification: str = ""
    tags: list[str] = field(default_factory=list)
    installed: bool = False
    registry: str = ""
