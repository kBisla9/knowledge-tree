"""Claude Code exporter — generates .claude/skills/ from knowledge packages."""

from __future__ import annotations

import shutil
from pathlib import Path

from knowledge_tree.exporters import Exporter, ExportResult, UnexportResult
from knowledge_tree.models import CommandEntry, ContentItem, PackageMetadata

_MANAGED_MARKER = "<!-- Managed by Knowledge Tree — do not edit manually -->"

# Files to exclude when iterating source directories (registry cache has these)
_NON_CONTENT_FILES = {"package.yaml"}


class ClaudeCodeExporter(Exporter):
    """Export knowledge packages as Claude Code skills."""

    name = "claude-code"
    description = "Claude Code skills (.claude/skills/)"

    @property
    def _skills_dir(self) -> Path:
        return self.project_root / ".claude" / "skills"

    def _skill_dir(self, package_name: str, registry_name: str = "default") -> Path:
        return self._skills_dir / registry_name / package_name

    def export_package(
        self,
        package_name: str,
        source_dir: Path,
        metadata: PackageMetadata,
        force: bool = False,
        registry_name: str = "default",
    ) -> ExportResult:
        """Export a package as a Claude Code skill.

        Creates .claude/skills/<registry>/<package>/ with SKILL.md and content files.
        Also exports any declared commands as top-level skill directories.
        """
        files_written: list[Path] = []
        files_skipped: list[Path] = []

        # --- Collect and route content files ---
        all_content_files = sorted(
            f for f in source_dir.iterdir() if f.is_file() and f.name not in _NON_CONTENT_FILES
        )

        # Build content item lookup for resolving content_type
        content_item_map: dict[str, ContentItem] = {item.file: item for item in metadata.content}

        # Split files by resolved content type
        knowledge_files: list[Path] = []
        command_content_files: list[tuple[ContentItem, Path]] = []
        for f in all_content_files:
            item = content_item_map.get(f.name, ContentItem(file=f.name))
            resolved = self._resolve_content_type(item, metadata)
            if resolved == "commands":
                command_content_files.append((item, f))
            else:
                knowledge_files.append(f)

        # --- Export content-type commands as top-level user-invocable skills ---
        if command_content_files:
            cmd_pairs: list[tuple[CommandEntry, Path]] = []
            for item, src_file in command_content_files:
                entry = CommandEntry(name=src_file.stem, description=item.description)
                cmd_pairs.append((entry, src_file))
            ct_cmd_result = self.export_commands(package_name, cmd_pairs, registry_name)
            files_written.extend(ct_cmd_result.files_written)
            files_skipped.extend(ct_cmd_result.files_skipped)

        # --- Knowledge/skills export ---
        content_files = knowledge_files
        has_commands = bool(metadata.commands) or bool(command_content_files)
        if content_files or not has_commands:
            skill_dir = self._skill_dir(package_name, registry_name)
            skill_md = skill_dir / "SKILL.md"

            # Check for conflict (non-KT-managed skill directory)
            if skill_dir.exists() and not force:
                if skill_md.exists() and _MANAGED_MARKER in skill_md.read_text():
                    pass  # ours — safe to overwrite
                else:
                    files_skipped.append(skill_dir)
                    return ExportResult(
                        package_name=package_name,
                        files_written=files_written,
                        files_skipped=files_skipped,
                    )

            # Create skill directory (wipe if exists for clean export)
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            skill_dir.mkdir(parents=True)

            # Generate SKILL.md with all content inlined
            skill_content = _build_skill_md(metadata, content_files)
            skill_md.write_text(skill_content)
            files_written.append(skill_md)

        # --- Command export ---
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
        )

    def unexport_package(
        self,
        package_name: str,
        registry_name: str = "default",
        metadata: PackageMetadata | None = None,
    ) -> UnexportResult:
        """Remove a Claude Code skill directory for a package.

        Also removes command skill directories if metadata is provided.
        """
        skill_dir = self._skill_dir(package_name, registry_name)
        files_removed: list[Path] = []

        if skill_dir.exists():
            # Collect file list before removal
            for f in skill_dir.rglob("*"):
                if f.is_file():
                    files_removed.append(f)
            shutil.rmtree(skill_dir)

        # Clean up commands (declared + content-type)
        if metadata:
            cmd_names = [cmd.name for cmd in metadata.commands]
            # Collect content-type command names from explicit content items
            for item in metadata.content:
                resolved = self._resolve_content_type(item, metadata)
                if resolved == "commands":
                    cmd_names.append(Path(item.file).stem)
            # When content_type is "commands" but no explicit content items,
            # scan top-level skill dirs for our managed marker
            if not cmd_names and metadata.content_type == "commands" and self._skills_dir.is_dir():
                for d in self._skills_dir.iterdir():
                    if not d.is_dir():
                        continue
                    skill_md = d / "SKILL.md"
                    if skill_md.exists() and _MANAGED_MARKER in skill_md.read_text():
                        cmd_names.append(d.name)
            if cmd_names:
                cmd_result = self.unexport_commands(package_name, cmd_names, registry_name)
                files_removed.extend(cmd_result.files_removed)

        return UnexportResult(
            package_name=package_name,
            files_removed=files_removed,
        )

    def _command_skill_dir(self, command_name: str) -> Path:
        """Command skills live at top level: .claude/skills/<command-name>/."""
        return self._skills_dir / command_name

    def export_commands(
        self,
        package_name: str,
        commands: list[tuple[CommandEntry, Path]],
        registry_name: str = "default",
    ) -> ExportResult:
        """Export commands as top-level Claude Code skills.

        Each command gets .claude/skills/<command-name>/SKILL.md with
        user-invocable: true.
        """
        files_written: list[Path] = []
        files_skipped: list[Path] = []

        for entry, source_path in commands:
            cmd_dir = self._command_skill_dir(entry.name)
            skill_md = cmd_dir / "SKILL.md"

            # Conflict check
            if cmd_dir.exists():
                if skill_md.exists() and _MANAGED_MARKER in skill_md.read_text():
                    pass  # ours — safe to overwrite
                else:
                    files_skipped.append(cmd_dir)
                    continue

            # Clean and recreate
            if cmd_dir.exists():
                shutil.rmtree(cmd_dir)
            cmd_dir.mkdir(parents=True)

            # Build SKILL.md for this command
            content = _build_command_skill_md(entry, source_path)
            skill_md.write_text(content)
            files_written.append(skill_md)

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
        """Remove command skill directories that have the KT managed marker."""
        files_removed: list[Path] = []

        if command_names is None:
            return UnexportResult(package_name=package_name, files_removed=files_removed)

        for name in command_names:
            cmd_dir = self._command_skill_dir(name)
            if not cmd_dir.exists():
                continue
            skill_md = cmd_dir / "SKILL.md"
            if skill_md.exists() and _MANAGED_MARKER in skill_md.read_text():
                for f in cmd_dir.rglob("*"):
                    if f.is_file():
                        files_removed.append(f)
                shutil.rmtree(cmd_dir)

        return UnexportResult(
            package_name=package_name,
            files_removed=files_removed,
        )


def _build_command_skill_md(entry: CommandEntry, source_path: Path) -> str:
    """Build SKILL.md for a command (slash command) skill."""
    # Read the command file content
    body = source_path.read_text() if source_path.exists() else ""

    # Use description from entry, or extract first non-empty line from body
    description = entry.description
    if not description:
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                description = stripped
                break
    if not description:
        description = entry.name

    lines: list[str] = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f"name: {entry.name}")
    lines.append(f'description: "{description}"')
    lines.append("user-invocable: true")
    lines.append("---")
    lines.append("")

    # Managed marker
    lines.append(_MANAGED_MARKER)
    lines.append("")

    # Body: include the full command content
    if body:
        lines.append(body)
        if not body.endswith("\n"):
            lines.append("")

    return "\n".join(lines)


def _build_skill_md(
    metadata: PackageMetadata,
    content_files: list[Path],
) -> str:
    """Build SKILL.md with YAML frontmatter and all content inlined."""
    lines: list[str] = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f"name: {metadata.name}")
    lines.append(f'description: "{metadata.description}"')
    lines.append("user-invocable: false")
    lines.append("---")
    lines.append("")

    # Managed marker
    lines.append(_MANAGED_MARKER)
    lines.append("")

    # Inline all content files
    for i, f in enumerate(content_files):
        body = f.read_text()
        lines.append(body)
        if not body.endswith("\n"):
            lines.append("")
        # Blank line between files
        if i < len(content_files) - 1:
            lines.append("")

    return "\n".join(lines)
