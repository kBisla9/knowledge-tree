"""Roo Code exporter — generates .roo/rules/, .roo/skills/, .roo/commands/."""

from __future__ import annotations

import shutil
from pathlib import Path

from knowledge_tree.exporters import Exporter, ExportResult, UnexportResult
from knowledge_tree.models import CommandEntry, ContentItem, PackageMetadata

_MANAGED_COMMENT = '<!-- Managed by Knowledge Tree: registry "{registry}" package "{name}" -->'
_SKILL_MANAGED_COMMENT = (
    '<!-- Managed by Knowledge Tree: registry "{registry}" package "{name}" skill "{skill}" -->'
)
_COMMAND_MANAGED_COMMENT = (
    '<!-- Managed by Knowledge Tree: registry "{registry}" package "{name}"'
    ' command "{command}" -->'
)
_FILE_PREFIX = "kt-"

# Files to exclude when iterating source directories (registry cache has these)
_NON_CONTENT_FILES = {"package.yaml"}


def _extract_first_heading(content: str) -> str:
    """Extract the first markdown heading from content, or empty string."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


class RooCodeExporter(Exporter):
    """Export knowledge packages as Roo Code rules, skills, and commands."""

    name = "roo-code"
    description = "Roo Code rules (.roo/rules/)"

    @property
    def _rules_dir(self) -> Path:
        return self.project_root / ".roo" / "rules"

    @property
    def _skills_dir(self) -> Path:
        return self.project_root / ".roo" / "skills"

    @property
    def _commands_dir(self) -> Path:
        return self.project_root / ".roo" / "commands"

    def _file_pattern(self, package_name: str, registry_name: str = "default") -> str:
        """Glob pattern matching rule files for a specific package from a registry."""
        return f"{_FILE_PREFIX}{registry_name}-{package_name}-*.md"

    def _make_filename(
        self,
        package_name: str,
        index: int,
        original_name: str,
        registry_name: str = "default",
    ) -> str:
        """Build the exported rule filename.

        Format: kt-<registry>-<package>-<nn>-<original>.md
        """
        stem = Path(original_name).stem
        return f"{_FILE_PREFIX}{registry_name}-{package_name}-{index:02d}-{stem}.md"

    def export_package(
        self,
        package_name: str,
        source_dir: Path,
        metadata: PackageMetadata,
        force: bool = False,
        registry_name: str = "default",
    ) -> ExportResult:
        """Export a package to Roo Code format.

        Routes content files to rules or skills based on content_type and export_hints.
        Also exports declared commands to .roo/commands/.
        """
        files_written: list[Path] = []
        files_skipped: list[Path] = []
        warnings: list[str] = []

        # --- Build content item list ---
        # If metadata has explicit content list, use it; otherwise build from source_dir
        content_items: list[ContentItem] = list(metadata.content)
        if not content_items:
            # Fallback: all top-level files in source_dir (excluding non-content files)
            for f in sorted(source_dir.iterdir()):
                if f.is_file() and f.name not in _NON_CONTENT_FILES:
                    content_items.append(ContentItem(file=f.name))

        # --- Group files by resolved content type ---
        rules_files: list[tuple[ContentItem, Path]] = []
        skills_files: list[tuple[ContentItem, Path]] = []
        for item in content_items:
            resolved = self._resolve_content_type(item, metadata)
            src_file = source_dir / item.file
            if not src_file.exists():
                continue
            if resolved == "skills":
                skills_files.append((item, src_file))
            else:
                # "knowledge" and anything else → rules (default)
                rules_files.append((item, src_file))

        # --- Export rules ---
        if rules_files:
            rules_result = self._export_as_rules(package_name, rules_files, force, registry_name)
            files_written.extend(rules_result.files_written)
            files_skipped.extend(rules_result.files_skipped)

        # --- Export skills ---
        if skills_files:
            skills_result = self._export_as_skills(
                package_name, skills_files, metadata, force, registry_name
            )
            files_written.extend(skills_result.files_written)
            files_skipped.extend(skills_result.files_skipped)
            warnings.extend(skills_result.warnings)

        # --- Export commands ---
        if metadata.commands:
            cmd_pairs: list[tuple[CommandEntry, Path]] = []
            for cmd in metadata.commands:
                cmd_file = source_dir / "commands" / f"{cmd.name}.md"
                cmd_pairs.append((cmd, cmd_file))
            cmd_result = self.export_commands(package_name, cmd_pairs, registry_name)
            files_written.extend(cmd_result.files_written)
            files_skipped.extend(cmd_result.files_skipped)

        return ExportResult(
            package_name=package_name,
            files_written=files_written,
            files_skipped=files_skipped,
            warnings=warnings,
        )

    def _export_as_rules(
        self,
        package_name: str,
        files: list[tuple[ContentItem, Path]],
        force: bool,
        registry_name: str,
    ) -> ExportResult:
        """Export content files as Roo Code rules (.roo/rules/)."""
        files_written: list[Path] = []
        files_skipped: list[Path] = []

        self._rules_dir.mkdir(parents=True, exist_ok=True)

        # Check for existing files from this package
        pattern = self._file_pattern(package_name, registry_name)
        existing = list(self._rules_dir.glob(pattern))
        if existing and not force:
            managed_marker = _MANAGED_COMMENT.format(registry=registry_name, name=package_name)
            first_file = existing[0]
            if managed_marker not in first_file.read_text():
                files_skipped.extend(existing)
                return ExportResult(
                    package_name=package_name,
                    files_written=files_written,
                    files_skipped=files_skipped,
                )

        # Remove old rule files for this package before writing new ones
        for old_file in self._rules_dir.glob(pattern):
            old_file.unlink()

        # Write numbered files
        header = _MANAGED_COMMENT.format(registry=registry_name, name=package_name)
        for i, (_item, src_file) in enumerate(files, start=1):
            dest_name = self._make_filename(package_name, i, src_file.name, registry_name)
            dest_path = self._rules_dir / dest_name
            original_content = src_file.read_text()
            dest_path.write_text(f"{header}\n\n{original_content}")
            files_written.append(dest_path)

        return ExportResult(
            package_name=package_name,
            files_written=files_written,
            files_skipped=files_skipped,
        )

    def _export_as_skills(
        self,
        package_name: str,
        files: list[tuple[ContentItem, Path]],
        metadata: PackageMetadata,
        force: bool,
        registry_name: str,
    ) -> ExportResult:
        """Export content files as Roo Code skills (.roo/skills/<name>/SKILL.md)."""
        files_written: list[Path] = []
        files_skipped: list[Path] = []
        warnings: list[str] = []

        for item, src_file in files:
            skill_name = src_file.stem
            skill_dir = self._skills_dir / skill_name
            skill_md = skill_dir / "SKILL.md"

            # Conflict check
            marker = _SKILL_MANAGED_COMMENT.format(
                registry=registry_name, name=package_name, skill=skill_name
            )
            if skill_dir.exists() and not force:
                if skill_md.exists() and marker in skill_md.read_text():
                    pass  # ours — safe to overwrite
                else:
                    files_skipped.append(skill_dir)
                    continue

            # Derive description
            description = item.description
            derived = False
            if not description:
                content = src_file.read_text()
                description = _extract_first_heading(content)
                derived = True
            if not description:
                description = metadata.description
                derived = True
            if not description:
                description = skill_name

            if derived:
                warnings.append(
                    f"Skill '{skill_name}': description derived from heading — "
                    "consider adding explicit description in package.yaml"
                )

            # Clean and recreate
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            skill_dir.mkdir(parents=True)

            # Build SKILL.md with content inlined
            body = src_file.read_text()
            skill_content = _build_roo_skill_md(skill_name, description, body, marker)
            skill_md.write_text(skill_content)
            files_written.append(skill_md)

        return ExportResult(
            package_name=package_name,
            files_written=files_written,
            files_skipped=files_skipped,
            warnings=warnings,
        )

    def export_commands(
        self,
        package_name: str,
        commands: list[tuple[CommandEntry, Path]],
        registry_name: str = "default",
    ) -> ExportResult:
        """Export commands as Roo Code slash commands (.roo/commands/<cmd>.md)."""
        files_written: list[Path] = []
        files_skipped: list[Path] = []

        if not commands:
            return ExportResult(package_name=package_name)

        self._commands_dir.mkdir(parents=True, exist_ok=True)

        for entry, source_path in commands:
            dest_path = self._commands_dir / f"{entry.name}.md"
            marker = _COMMAND_MANAGED_COMMENT.format(
                registry=registry_name, name=package_name, command=entry.name
            )

            # Conflict check
            if dest_path.exists():
                if marker in dest_path.read_text():
                    pass  # ours — safe to overwrite
                else:
                    files_skipped.append(dest_path)
                    continue

            # Build command file
            body = source_path.read_text() if source_path.exists() else ""
            content = _build_roo_command_md(entry, body, marker)
            dest_path.write_text(content)
            files_written.append(dest_path)

        return ExportResult(
            package_name=package_name,
            files_written=files_written,
            files_skipped=files_skipped,
        )

    def unexport_commands(
        self,
        package_name: str,
        command_names: list[str] | None = None,
        registry_name: str = "default",
    ) -> UnexportResult:
        """Remove managed command files from .roo/commands/."""
        files_removed: list[Path] = []

        if command_names is None or not self._commands_dir.is_dir():
            return UnexportResult(package_name=package_name, files_removed=files_removed)

        for cmd_name in command_names:
            dest_path = self._commands_dir / f"{cmd_name}.md"
            if not dest_path.exists():
                continue
            marker = _COMMAND_MANAGED_COMMENT.format(
                registry=registry_name, name=package_name, command=cmd_name
            )
            if marker in dest_path.read_text():
                files_removed.append(dest_path)
                dest_path.unlink()

        return UnexportResult(package_name=package_name, files_removed=files_removed)

    def unexport_package(
        self,
        package_name: str,
        registry_name: str = "default",
        metadata: PackageMetadata | None = None,
    ) -> UnexportResult:
        """Remove Roo Code rule files, skill directories, and commands for a package."""
        files_removed: list[Path] = []

        # Remove rules
        if self._rules_dir.is_dir():
            pattern = self._file_pattern(package_name, registry_name)
            for rule_file in self._rules_dir.glob(pattern):
                files_removed.append(rule_file)
                rule_file.unlink()

        # Remove skills (scan for managed marker)
        if self._skills_dir.is_dir():
            marker_pkg = f'package "{package_name}"'
            marker_reg = f'registry "{registry_name}"'
            for skill_dir in list(self._skills_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    content = skill_md.read_text()
                    if marker_pkg in content and marker_reg in content:
                        for f in skill_dir.rglob("*"):
                            if f.is_file():
                                files_removed.append(f)
                        shutil.rmtree(skill_dir)

        # Remove commands
        if metadata and metadata.commands:
            cmd_names = [cmd.name for cmd in metadata.commands]
            cmd_result = self.unexport_commands(package_name, cmd_names, registry_name)
            files_removed.extend(cmd_result.files_removed)

        return UnexportResult(
            package_name=package_name,
            files_removed=files_removed,
        )


def _build_roo_skill_md(
    skill_name: str,
    description: str,
    body: str,
    managed_marker: str,
) -> str:
    """Build SKILL.md for a Roo Code skill (Agent Skills standard)."""
    lines: list[str] = []

    # YAML frontmatter (no user-invocable — that's a Claude Code extension)
    lines.append("---")
    lines.append(f"name: {skill_name}")
    lines.append(f'description: "{description}"')
    lines.append("---")
    lines.append("")

    # Managed marker
    lines.append(managed_marker)
    lines.append("")

    # Body
    if body:
        lines.append(body)
        if not body.endswith("\n"):
            lines.append("")

    return "\n".join(lines)


def _build_roo_command_md(
    entry: CommandEntry,
    body: str,
    managed_marker: str,
) -> str:
    """Build a Roo Code command file (.roo/commands/<name>.md)."""
    lines: list[str] = []

    # Frontmatter with description if available
    description = entry.description
    if not description:
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                description = stripped
                break

    if description:
        lines.append("---")
        lines.append(f'description: "{description}"')
        lines.append("---")
        lines.append("")

    # Managed marker
    lines.append(managed_marker)
    lines.append("")

    # Body
    if body:
        lines.append(body)
        if not body.endswith("\n"):
            lines.append("")

    return "\n".join(lines)
