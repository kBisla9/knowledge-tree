"""Tests for Knowledge Tree exporters."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_tree.exporters import (
    ExportResult,
    UnexportResult,
    get_exporter,
    list_formats,
)
from knowledge_tree.exporters.claude_code import _MANAGED_MARKER, ClaudeCodeExporter
from knowledge_tree.exporters.roo_code import RooCodeExporter
from knowledge_tree.models import CommandEntry, ContentItem, ModeEntry, PackageMetadata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_knowledge_dir(project: Path, name: str, files: dict[str, str]) -> Path:
    """Create a package source directory with given files (simulates registry cache)."""
    pkg_dir = project / ".knowledge-tree" / "cache" / "default" / "packages" / name
    pkg_dir.mkdir(parents=True)
    for filename, content in files.items():
        (pkg_dir / filename).write_text(content)
    return pkg_dir


def _sample_metadata(name: str = "base", description: str = "Universal coding conventions"):
    return PackageMetadata(
        name=name,
        description=description,
        authors=["Test Author"],
        classification="evergreen",
        tags=["core", "conventions"],
    )


# ===========================================================================
# Exporter registry
# ===========================================================================


class TestExporterRegistry:
    def test_get_exporter_claude_code(self, tmp_path):
        exporter = get_exporter("claude-code", tmp_path)
        assert isinstance(exporter, ClaudeCodeExporter)
        assert exporter.project_root == tmp_path

    def test_get_exporter_roo_code(self, tmp_path):
        exporter = get_exporter("roo-code", tmp_path)
        assert isinstance(exporter, RooCodeExporter)
        assert exporter.project_root == tmp_path

    def test_get_exporter_unknown(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown export format 'foobar'"):
            get_exporter("foobar", tmp_path)

    def test_list_formats(self):
        formats = list_formats()
        names = [name for name, _ in formats]
        assert "claude-code" in names
        assert "roo-code" in names
        # Should have descriptions
        for _, desc in formats:
            assert desc


# ===========================================================================
# ClaudeCodeExporter
# ===========================================================================


class TestClaudeCodeExporter:
    def test_export_creates_skill_directory(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package("base", source, meta, registry_name="default")

        skill_dir = tmp_path / ".claude" / "skills" / "default" / "base"
        assert skill_dir.is_dir()
        assert isinstance(result, ExportResult)
        assert result.package_name == "base"

    def test_export_generates_skill_md(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")

        skill_md = tmp_path / ".claude" / "skills" / "default" / "base" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "---" in content
        assert "name: base" in content
        assert 'description: "Universal coding conventions"' in content
        assert "user-invocable: false" in content
        assert _MANAGED_MARKER in content

    def test_export_inlines_content_files(self, tmp_path):
        source = _make_knowledge_dir(
            tmp_path,
            "api-patterns",
            {
                "rest-conventions.md": "# REST\n",
                "authentication.md": "# Auth\n",
            },
        )
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata("api-patterns", "REST API patterns")

        result = exporter.export_package("api-patterns", source, meta, registry_name="default")

        skill_dir = tmp_path / ".claude" / "skills" / "default" / "api-patterns"
        # Only SKILL.md — no separate content files
        assert not (skill_dir / "rest-conventions.md").exists()
        assert not (skill_dir / "authentication.md").exists()
        assert len(result.files_written) == 1
        # Content should be inlined in SKILL.md
        content = (skill_dir / "SKILL.md").read_text()
        assert "# REST" in content
        assert "# Auth" in content

    def test_export_skill_md_inlines_content(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")

        content = (tmp_path / ".claude" / "skills" / "default" / "base" / "SKILL.md").read_text()
        assert "# Safe Deletion" in content

    def test_export_skips_existing_non_managed(self, tmp_path):
        # Create an existing skill dir that's NOT managed by KT
        skill_dir = tmp_path / ".claude" / "skills" / "default" / "base"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My custom skill\n")

        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package(
            "base", source, meta, force=False, registry_name="default"
        )

        assert not result.files_written
        assert result.files_skipped
        # Original file should be unchanged
        assert "My custom skill" in (skill_dir / "SKILL.md").read_text()

    def test_export_overwrites_with_force(self, tmp_path):
        # Create an existing skill dir that's NOT managed by KT
        skill_dir = tmp_path / ".claude" / "skills" / "default" / "base"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My custom skill\n")

        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package("base", source, meta, force=True, registry_name="default")

        assert result.files_written
        assert _MANAGED_MARKER in (skill_dir / "SKILL.md").read_text()

    def test_export_overwrites_own_managed(self, tmp_path):
        """Re-exporting a KT-managed skill should overwrite without --force."""
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        # First export
        exporter.export_package("base", source, meta, registry_name="default")
        # Second export — should succeed without force
        result = exporter.export_package(
            "base", source, meta, force=False, registry_name="default"
        )
        assert result.files_written

    def test_unexport_removes_skill_directory(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")
        result = exporter.unexport_package("base", registry_name="default")

        skill_dir = tmp_path / ".claude" / "skills" / "default" / "base"
        assert not skill_dir.exists()
        assert isinstance(result, UnexportResult)
        assert result.files_removed

    def test_unexport_nonexistent_is_noop(self, tmp_path):
        exporter = ClaudeCodeExporter(tmp_path)
        result = exporter.unexport_package("nonexistent", registry_name="default")

        assert not result.files_removed

    def test_export_empty_source(self, tmp_path):
        """Exporting a package with no files should still create SKILL.md."""
        source = _make_knowledge_dir(tmp_path, "empty-pkg", {})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata("empty-pkg", "Empty package")

        result = exporter.export_package("empty-pkg", source, meta, registry_name="default")

        skill_md = tmp_path / ".claude" / "skills" / "default" / "empty-pkg" / "SKILL.md"
        assert skill_md.exists()
        assert len(result.files_written) == 1  # Only SKILL.md

    def test_export_different_registries(self, tmp_path):
        """Same package name from two registries should not collide."""
        source1 = _make_knowledge_dir(tmp_path, "base-a", {"a.md": "# A\n"})
        source2 = _make_knowledge_dir(tmp_path, "base-b", {"b.md": "# B\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source1, meta, registry_name="default")
        exporter.export_package("base", source2, meta, registry_name="internal")

        assert (tmp_path / ".claude" / "skills" / "default" / "base" / "SKILL.md").exists()
        assert (tmp_path / ".claude" / "skills" / "internal" / "base" / "SKILL.md").exists()


# ===========================================================================
# RooCodeExporter
# ===========================================================================


class TestRooCodeExporter:
    def test_export_creates_rules_directory(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package("base", source, meta, registry_name="default")

        rules_dir = tmp_path / ".roo" / "rules"
        assert rules_dir.is_dir()
        assert isinstance(result, ExportResult)

    def test_export_names_files_correctly(self, tmp_path):
        source = _make_knowledge_dir(
            tmp_path,
            "api-patterns",
            {
                "authentication.md": "# Auth\n",
                "rest-conventions.md": "# REST\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata("api-patterns", "REST API patterns")

        result = exporter.export_package("api-patterns", source, meta, registry_name="default")

        rules_dir = tmp_path / ".roo" / "rules"
        files = sorted(f.name for f in rules_dir.iterdir())
        # Files sorted by source name: authentication.md (01), rest-conventions.md (02)
        assert files == [
            "kt-default-api-patterns-01-authentication.md",
            "kt-default-api-patterns-02-rest-conventions.md",
        ]
        assert len(result.files_written) == 2

    def test_export_prepends_header(self, tmp_path):
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")

        rule_file = tmp_path / ".roo" / "rules" / "kt-default-base-01-safe-deletion.md"
        content = rule_file.read_text()
        assert '<!-- Managed by Knowledge Tree: registry "default" package "base" -->' in content
        assert "# Safe Deletion" in content

    def test_export_preserves_content_order(self, tmp_path):
        """Files should be numbered by sorted filename order."""
        source = _make_knowledge_dir(
            tmp_path,
            "base",
            {
                "z-last.md": "# Last\n",
                "a-first.md": "# First\n",
                "m-middle.md": "# Middle\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")

        rules_dir = tmp_path / ".roo" / "rules"
        files = sorted(f.name for f in rules_dir.iterdir())
        assert files == [
            "kt-default-base-01-a-first.md",
            "kt-default-base-02-m-middle.md",
            "kt-default-base-03-z-last.md",
        ]

    def test_export_skip_existing_non_managed(self, tmp_path):
        # Create existing files with matching names but not managed by KT
        rules_dir = tmp_path / ".roo" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "kt-default-base-01-safe-deletion.md").write_text("# User content\n")

        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package(
            "base", source, meta, force=False, registry_name="default"
        )

        assert not result.files_written
        assert result.files_skipped

    def test_export_overwrite_with_force(self, tmp_path):
        rules_dir = tmp_path / ".roo" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "kt-default-base-01-safe-deletion.md").write_text("# User content\n")

        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        result = exporter.export_package("base", source, meta, force=True, registry_name="default")

        assert result.files_written

    def test_export_overwrites_own_managed(self, tmp_path):
        """Re-exporting KT-managed files should overwrite without --force."""
        source = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe Deletion\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")
        result = exporter.export_package(
            "base", source, meta, force=False, registry_name="default"
        )
        assert result.files_written

    def test_unexport_removes_only_package_files(self, tmp_path):
        source_base = _make_knowledge_dir(tmp_path, "base", {"safe-deletion.md": "# Safe\n"})
        source_api = _make_knowledge_dir(tmp_path, "api-patterns", {"rest.md": "# REST\n"})
        exporter = RooCodeExporter(tmp_path)

        exporter.export_package("base", source_base, _sample_metadata(), registry_name="default")
        exporter.export_package(
            "api-patterns",
            source_api,
            _sample_metadata("api-patterns", "API patterns"),
            registry_name="default",
        )

        result = exporter.unexport_package("base", registry_name="default")

        rules_dir = tmp_path / ".roo" / "rules"
        remaining = [f.name for f in rules_dir.iterdir()]
        assert "kt-default-base-01-safe-deletion.md" not in remaining
        assert "kt-default-api-patterns-01-rest.md" in remaining
        assert len(result.files_removed) == 1

    def test_unexport_nonexistent_is_noop(self, tmp_path):
        exporter = RooCodeExporter(tmp_path)
        result = exporter.unexport_package("nonexistent", registry_name="default")
        assert not result.files_removed

    def test_export_empty_source(self, tmp_path):
        """Exporting a package with no files should produce no rule files."""
        source = _make_knowledge_dir(tmp_path, "empty-pkg", {})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata("empty-pkg", "Empty")

        result = exporter.export_package("empty-pkg", source, meta, registry_name="default")
        assert not result.files_written

    def test_export_cleans_old_files_on_re_export(self, tmp_path):
        """Re-exporting should remove old files if content changed."""
        source = _make_knowledge_dir(
            tmp_path, "base", {"old-file.md": "# Old\n", "another.md": "# Another\n"}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source, meta, registry_name="default")
        rules_dir = tmp_path / ".roo" / "rules"
        assert len(list(rules_dir.glob("kt-default-base-*.md"))) == 2

        # Change source files
        (source / "old-file.md").unlink()
        (source / "new-file.md").write_text("# New\n")

        exporter.export_package("base", source, meta, registry_name="default")
        files = sorted(f.name for f in rules_dir.glob("kt-default-base-*.md"))
        assert "kt-default-base-01-another.md" in files
        assert "kt-default-base-02-new-file.md" in files
        assert len(files) == 2  # old-file should be gone

    def test_export_different_registries(self, tmp_path):
        """Same package name from two registries should not collide."""
        source1 = _make_knowledge_dir(tmp_path, "base-a", {"a.md": "# A\n"})
        source2 = _make_knowledge_dir(tmp_path, "base-b", {"b.md": "# B\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = _sample_metadata()

        exporter.export_package("base", source1, meta, registry_name="default")
        exporter.export_package("base", source2, meta, registry_name="internal")

        rules_dir = tmp_path / ".roo" / "rules"
        default_files = list(rules_dir.glob("kt-default-base-*.md"))
        internal_files = list(rules_dir.glob("kt-internal-base-*.md"))
        assert len(default_files) == 1
        assert len(internal_files) == 1


# ===========================================================================
# RooCodeExporter — Skills export
# ===========================================================================


class TestRooCodeSkillsExport:
    def test_skills_content_type_creates_skill_dirs(self, tmp_path):
        """content_type=skills routes files to .roo/skills/."""
        source = _make_knowledge_dir(
            tmp_path, "api-ref", {"api-reference.md": "# API Reference\n\nLookup API details.\n"}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="api-ref",
            description="API reference docs",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        result = exporter.export_package("api-ref", source, meta, registry_name="default")

        skill_dir = tmp_path / ".roo" / "skills" / "api-reference"
        assert skill_dir.is_dir()
        assert (skill_dir / "SKILL.md").exists()
        # Only SKILL.md — content inlined, no separate source copy
        assert not (skill_dir / "api-reference.md").exists()
        assert len(result.files_written) == 1

    def test_skills_frontmatter(self, tmp_path):
        """Skills SKILL.md has Agent Skills standard frontmatter."""
        source = _make_knowledge_dir(
            tmp_path, "ref", {"lookup.md": "# Lookup Guide\n\nHow to look things up.\n"}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference package",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "skills" / "lookup" / "SKILL.md").read_text()
        assert "---" in content
        assert "name: lookup" in content
        # Description derived from heading
        assert 'description: "Lookup Guide"' in content
        # No user-invocable (Claude Code extension, not in base standard)
        assert "user-invocable" not in content

    def test_skills_managed_marker(self, tmp_path):
        """Skills SKILL.md contains the managed-by marker."""
        source = _make_knowledge_dir(tmp_path, "ref", {"lookup.md": "# Lookup\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "skills" / "lookup" / "SKILL.md").read_text()
        assert 'registry "default"' in content
        assert 'package "ref"' in content
        assert 'skill "lookup"' in content

    def test_skills_description_from_content_item(self, tmp_path):
        """Explicit ContentItem description is used for skill metadata."""
        source = _make_knowledge_dir(tmp_path, "ref", {"api.md": "# API Reference\n\nDetails.\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
            content=[ContentItem(file="api.md", description="Explicit API description")],
        )

        result = exporter.export_package("ref", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "skills" / "api" / "SKILL.md").read_text()
        assert 'description: "Explicit API description"' in content
        # No warnings when description is explicit
        assert len(result.warnings) == 0

    def test_skills_description_derived_emits_warning(self, tmp_path):
        """Derived description emits a warning."""
        source = _make_knowledge_dir(tmp_path, "ref", {"api.md": "# API Reference\n\nDetails.\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
            # No explicit description on ContentItem
        )

        result = exporter.export_package("ref", source, meta, registry_name="default")

        assert len(result.warnings) == 1
        assert "api" in result.warnings[0]
        assert "derived" in result.warnings[0].lower()

    def test_skills_description_fallback_to_package_desc(self, tmp_path):
        """When no heading in content, falls back to package description."""
        source = _make_knowledge_dir(
            tmp_path, "ref", {"data.md": "Just some data without a heading.\n"}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Package level description",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "skills" / "data" / "SKILL.md").read_text()
        assert 'description: "Package level description"' in content

    def test_skills_skip_non_managed_conflict(self, tmp_path):
        """Existing non-KT skill dir is skipped."""
        skill_dir = tmp_path / ".roo" / "skills" / "lookup"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: lookup\n---\nUser's skill.\n")

        source = _make_knowledge_dir(tmp_path, "ref", {"lookup.md": "# Lookup\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        result = exporter.export_package("ref", source, meta, force=False, registry_name="default")

        assert len(result.files_skipped) == 1
        assert len(result.files_written) == 0
        # Original preserved
        assert "User's skill." in (skill_dir / "SKILL.md").read_text()

    def test_skills_overwrite_own_managed(self, tmp_path):
        """Re-exporting KT-managed skills overwrites without --force."""
        source = _make_knowledge_dir(tmp_path, "ref", {"lookup.md": "# Lookup\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")
        result = exporter.export_package("ref", source, meta, force=False, registry_name="default")

        assert len(result.files_written) == 1  # SKILL.md only

    def test_unexport_removes_skills(self, tmp_path):
        """unexport_package removes managed skill directories."""
        source = _make_knowledge_dir(tmp_path, "ref", {"lookup.md": "# Lookup\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")
        result = exporter.unexport_package("ref", registry_name="default")

        assert not (tmp_path / ".roo" / "skills" / "lookup").exists()
        assert len(result.files_removed) > 0

    def test_multiple_skills_files(self, tmp_path):
        """Multiple skill files each get their own skill directory."""
        source = _make_knowledge_dir(
            tmp_path,
            "ref",
            {
                "api.md": "# API Reference\n",
                "config.md": "# Config Guide\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Ref",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        result = exporter.export_package("ref", source, meta, registry_name="default")

        assert (tmp_path / ".roo" / "skills" / "api" / "SKILL.md").exists()
        assert (tmp_path / ".roo" / "skills" / "config" / "SKILL.md").exists()
        # 2 skills x SKILL.md = 2 files
        assert len(result.files_written) == 2


# ===========================================================================
# RooCodeExporter — Commands export
# ===========================================================================


class TestRooCodeCommandExport:
    def test_export_commands_creates_files(self, tmp_path):
        """Commands exported to .roo/commands/<name>.md."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "start-session.md").write_text("# Start Session\n\nLoad context.\n")
        (cmd_dir / "end-session.md").write_text("# End Session\n\nPersist knowledge.\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Session management",
            authors=["Test"],
            classification="evergreen",
            commands=[
                CommandEntry(name="start-session", description="Start a session"),
                CommandEntry(name="end-session", description="End a session"),
            ],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        commands_dir = tmp_path / ".roo" / "commands"
        assert commands_dir.is_dir()
        assert (commands_dir / "start-session.md").exists()
        assert (commands_dir / "end-session.md").exists()

    def test_command_frontmatter(self, tmp_path):
        """Command file has frontmatter with description."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "my-cmd.md").write_text("# My Command\n\nDo stuff.\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="my-cmd", description="Do something")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "my-cmd.md").read_text()
        assert "---" in content
        assert 'description: "Do something"' in content

    def test_command_managed_marker(self, tmp_path):
        """Command file contains the managed-by marker."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "my-cmd.md").write_text("# My Command\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="my-cmd", description="My")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "my-cmd.md").read_text()
        assert 'registry "default"' in content
        assert 'package "core"' in content
        assert 'command "my-cmd"' in content

    def test_command_body_included(self, tmp_path):
        """Command file content appears in the exported file."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "greet.md").write_text("# Greet\n\nSay hello to the user.\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="greet", description="Greet")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "greet.md").read_text()
        assert "Say hello to the user." in content

    def test_command_description_from_heading(self, tmp_path):
        """When CommandEntry has no description, extract from file heading."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "my-cmd.md").write_text("# My Amazing Command\n\nDo stuff.\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="my-cmd")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "my-cmd.md").read_text()
        assert 'description: "My Amazing Command"' in content

    def test_command_conflict_skips(self, tmp_path):
        """Existing non-KT command file is skipped."""
        commands_dir = tmp_path / ".roo" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "my-cmd.md").write_text("User's own command.\n")

        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "my-cmd.md").write_text("# My\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="my-cmd", description="My")],
        )

        result = exporter.export_package("core", source, meta, registry_name="default")

        # The command file was skipped
        cmd_skipped = [p for p in result.files_skipped if "commands" in str(p)]
        assert len(cmd_skipped) == 1
        # Original preserved
        assert "User's own command." in (commands_dir / "my-cmd.md").read_text()

    def test_unexport_commands(self, tmp_path):
        """unexport_commands removes managed command files."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "start-session.md").write_text("# Start\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="start-session", description="Start")],
        )

        exporter.export_package("core", source, meta, registry_name="default")
        result = exporter.unexport_commands("core", ["start-session"], registry_name="default")

        assert len(result.files_removed) == 1
        assert not (tmp_path / ".roo" / "commands" / "start-session.md").exists()

    def test_unexport_commands_skips_non_managed(self, tmp_path):
        """unexport_commands leaves non-KT command files alone."""
        commands_dir = tmp_path / ".roo" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "user-cmd.md").write_text("User command.\n")

        exporter = RooCodeExporter(tmp_path)
        result = exporter.unexport_commands("core", ["user-cmd"], registry_name="default")

        assert len(result.files_removed) == 0
        assert (commands_dir / "user-cmd.md").exists()

    def test_unexport_package_removes_commands(self, tmp_path):
        """unexport_package with metadata removes commands too."""
        source = _make_knowledge_dir(tmp_path, "core", {"overview.md": "# Overview\n"})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "start.md").write_text("# Start\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="start", description="Start")],
        )

        exporter.export_package("core", source, meta, registry_name="default")
        result = exporter.unexport_package("core", registry_name="default", metadata=meta)

        # Both rules and commands should be removed
        assert not (tmp_path / ".roo" / "commands" / "start.md").exists()
        assert len(result.files_removed) >= 2  # at least rule file + command file

    def test_commands_only_package(self, tmp_path):
        """Commands-only package: no rules created, only command files."""
        source = _make_knowledge_dir(tmp_path, "core", {})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "start.md").write_text("# Start\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Commands only",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="start", description="Start")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        # Command file created
        assert (tmp_path / ".roo" / "commands" / "start.md").exists()
        # No rules directory (or empty)
        rules_dir = tmp_path / ".roo" / "rules"
        if rules_dir.exists():
            assert not list(rules_dir.iterdir())

    def test_mixed_content_and_commands(self, tmp_path):
        """Package with both content and commands creates rules + command files."""
        source = _make_knowledge_dir(tmp_path, "core", {"overview.md": "# Overview\n"})
        cmd_dir = source / "commands"
        cmd_dir.mkdir()
        (cmd_dir / "run.md").write_text("# Run\n")

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Has both",
            authors=["Test"],
            classification="evergreen",
            commands=[CommandEntry(name="run", description="Run it")],
        )

        result = exporter.export_package("core", source, meta, registry_name="default")

        # Rule file for knowledge content
        rules = list((tmp_path / ".roo" / "rules").glob("kt-default-core-*.md"))
        assert len(rules) == 1
        # Command file
        assert (tmp_path / ".roo" / "commands" / "run.md").exists()
        assert len(result.files_written) == 2  # 1 rule + 1 command


# ===========================================================================
# RooCodeExporter — Export hints routing
# ===========================================================================


class TestRooCodeExportHints:
    def test_package_level_export_hint(self, tmp_path):
        """Package-level export_hints routes all files to specified type."""
        source = _make_knowledge_dir(
            tmp_path, "ref", {"api.md": "# API\n", "config.md": "# Config\n"}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            export_hints={"roo-code": "skills"},  # all files → skills
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        # Both should be skills, not rules
        assert (tmp_path / ".roo" / "skills" / "api" / "SKILL.md").exists()
        assert (tmp_path / ".roo" / "skills" / "config" / "SKILL.md").exists()
        rules_dir = tmp_path / ".roo" / "rules"
        if rules_dir.exists():
            assert not list(rules_dir.glob("kt-default-ref-*.md"))

    def test_per_file_export_hint(self, tmp_path):
        """Per-file export hints override package-level."""
        source = _make_knowledge_dir(
            tmp_path,
            "ref",
            {
                "overview.md": "# Overview\n",
                "api.md": "# API Reference\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            content=[
                ContentItem(file="overview.md"),  # inherits default → knowledge → rules
                ContentItem(file="api.md", export_hints={"roo-code": "skills"}),
            ],
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        # overview → rules
        rules = list((tmp_path / ".roo" / "rules").glob("kt-default-ref-*.md"))
        assert len(rules) == 1
        assert "overview" in rules[0].name
        # api → skills
        assert (tmp_path / ".roo" / "skills" / "api" / "SKILL.md").exists()

    def test_per_file_overrides_package_hint(self, tmp_path):
        """Per-file hint takes precedence over package-level hint."""
        source = _make_knowledge_dir(
            tmp_path,
            "ref",
            {
                "always-on.md": "# Always On\n",
                "on-demand.md": "# On Demand\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            export_hints={"roo-code": "skills"},  # package says skills
            content=[
                ContentItem(
                    file="always-on.md",
                    export_hints={"roo-code": "knowledge"},  # override to knowledge (→ rules)
                ),
                ContentItem(file="on-demand.md"),  # inherits package hint → skills
            ],
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        # always-on → rules (per-file override)
        rules = list((tmp_path / ".roo" / "rules").glob("kt-default-ref-*.md"))
        assert len(rules) == 1
        assert "always-on" in rules[0].name
        # on-demand → skills (inherited from package)
        assert (tmp_path / ".roo" / "skills" / "on-demand" / "SKILL.md").exists()

    def test_content_type_without_hints(self, tmp_path):
        """content_type=skills without export_hints routes all to skills."""
        source = _make_knowledge_dir(tmp_path, "ref", {"guide.md": "# Guide\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        assert (tmp_path / ".roo" / "skills" / "guide" / "SKILL.md").exists()
        rules_dir = tmp_path / ".roo" / "rules"
        if rules_dir.exists():
            assert not list(rules_dir.glob("kt-default-ref-*.md"))

    def test_hint_for_other_exporter_ignored(self, tmp_path):
        """Export hints for other exporters don't affect roo-code routing."""
        source = _make_knowledge_dir(tmp_path, "ref", {"guide.md": "# Guide\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            export_hints={"claude-code": "skills"},  # only affects claude-code
        )

        exporter.export_package("ref", source, meta, registry_name="default")

        # Should default to knowledge → rules for roo-code
        rules = list((tmp_path / ".roo" / "rules").glob("kt-default-ref-*.md"))
        assert len(rules) == 1

    def test_mixed_hints_multiple_files(self, tmp_path):
        """Different files route to different types via per-file hints."""
        source = _make_knowledge_dir(
            tmp_path,
            "mixed",
            {
                "conventions.md": "# Conventions\n",
                "api-ref.md": "# API Reference\n",
                "patterns.md": "# Patterns\n",
            },
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="mixed",
            description="Mixed content",
            authors=["Test"],
            classification="evergreen",
            content=[
                ContentItem(file="conventions.md"),  # default → knowledge → rules
                ContentItem(file="api-ref.md", export_hints={"roo-code": "skills"}),
                ContentItem(file="patterns.md"),  # default → knowledge → rules
            ],
        )

        exporter.export_package("mixed", source, meta, registry_name="default")

        # 2 rules files
        rules = sorted((tmp_path / ".roo" / "rules").glob("kt-default-mixed-*.md"))
        assert len(rules) == 2
        assert "conventions" in rules[0].name
        assert "patterns" in rules[1].name
        # 1 skill
        assert (tmp_path / ".roo" / "skills" / "api-ref" / "SKILL.md").exists()


# ===========================================================================
# ClaudeCodeExporter — content_type parity
# ===========================================================================


class TestClaudeCodeContentType:
    def test_skills_content_type_same_as_knowledge(self, tmp_path):
        """Claude Code: content_type=skills produces identical output to knowledge."""
        source_k = _make_knowledge_dir(tmp_path, "ref-k", {"guide.md": "# Guide\n"})
        source_s = _make_knowledge_dir(tmp_path, "ref-s", {"guide.md": "# Guide\n"})
        exporter = ClaudeCodeExporter(tmp_path)

        meta_k = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            content_type="",  # default (knowledge)
        )
        meta_s = PackageMetadata(
            name="ref",
            description="Reference",
            authors=["Test"],
            classification="evergreen",
            content_type="skills",
        )

        result_k = exporter.export_package("ref", source_k, meta_k, registry_name="know")
        result_s = exporter.export_package("ref", source_s, meta_s, registry_name="skill")

        # Both produce same number of files
        assert len(result_k.files_written) == len(result_s.files_written)

        # Both create SKILL.md in their respective dirs
        assert (tmp_path / ".claude" / "skills" / "know" / "ref" / "SKILL.md").exists()
        assert (tmp_path / ".claude" / "skills" / "skill" / "ref" / "SKILL.md").exists()


# ===========================================================================
# _extract_first_heading helper
# ===========================================================================


class TestExtractFirstHeading:
    def test_extracts_h1(self):
        from knowledge_tree.exporters.roo_code import _extract_first_heading

        assert _extract_first_heading("# Hello World\n\nContent.") == "Hello World"

    def test_extracts_h2(self):
        from knowledge_tree.exporters.roo_code import _extract_first_heading

        assert _extract_first_heading("## Sub Heading\n") == "Sub Heading"

    def test_empty_string(self):
        from knowledge_tree.exporters.roo_code import _extract_first_heading

        assert _extract_first_heading("") == ""

    def test_no_heading(self):
        from knowledge_tree.exporters.roo_code import _extract_first_heading

        assert _extract_first_heading("Just some text.\nNo headings here.\n") == ""

    def test_first_heading_only(self):
        from knowledge_tree.exporters.roo_code import _extract_first_heading

        assert _extract_first_heading("# First\n\n## Second\n") == "First"


# ===========================================================================
# Commands content_type routing
# ===========================================================================


class TestRooCodeCommandsContentType:
    def test_content_type_commands_routes_to_commands_dir(self, tmp_path):
        """content_type=commands routes all content files to .roo/commands/."""
        source = _make_knowledge_dir(
            tmp_path, "ops", {"start.md": "# Start\nBegin work.", "end.md": "# End\nFinish."}
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations commands",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        result = exporter.export_package("ops", source, meta, registry_name="default")

        # Both files should be in .roo/commands/
        assert (tmp_path / ".roo" / "commands" / "start.md").exists()
        assert (tmp_path / ".roo" / "commands" / "end.md").exists()
        assert len(result.files_written) == 2
        # No rules created
        rules_dir = tmp_path / ".roo" / "rules"
        if rules_dir.exists():
            assert not list(rules_dir.glob("kt-default-ops-*.md"))

    def test_content_type_commands_includes_frontmatter(self, tmp_path):
        """Command files from content_type get proper frontmatter."""
        source = _make_knowledge_dir(tmp_path, "ops", {"review.md": "# Review\nReview code."})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        exporter.export_package("ops", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "review.md").read_text()
        assert "---" in content
        assert "Managed by Knowledge Tree" in content
        assert "# Review" in content

    def test_per_file_hint_commands(self, tmp_path):
        """Per-file export_hint routes individual files to commands."""
        source = _make_knowledge_dir(
            tmp_path,
            "mixed",
            {"guide.md": "# Guide\n", "deploy.md": "# Deploy\n"},
        )
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="mixed",
            description="Mixed package",
            authors=["Test"],
            classification="evergreen",
            content=[
                ContentItem(file="guide.md"),  # default → knowledge → rules
                ContentItem(file="deploy.md", export_hints={"roo-code": "commands"}),
            ],
        )

        result = exporter.export_package("mixed", source, meta, registry_name="default")

        # guide → rules
        rules = list((tmp_path / ".roo" / "rules").glob("kt-default-mixed-*.md"))
        assert len(rules) == 1
        assert "guide" in rules[0].name
        # deploy → commands
        assert (tmp_path / ".roo" / "commands" / "deploy.md").exists()
        assert len(result.files_written) == 2

    def test_unexport_removes_content_type_commands(self, tmp_path):
        """unexport_package cleans up commands created via content_type."""
        source = _make_knowledge_dir(tmp_path, "ops", {"start.md": "# Start\n"})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        exporter.export_package("ops", source, meta, registry_name="default")
        assert (tmp_path / ".roo" / "commands" / "start.md").exists()

        result = exporter.unexport_package("ops", registry_name="default", metadata=meta)
        assert not (tmp_path / ".roo" / "commands" / "start.md").exists()
        assert len(result.files_removed) == 1

    def test_content_type_commands_with_description(self, tmp_path):
        """Content items with explicit description pass it to command frontmatter."""
        source = _make_knowledge_dir(tmp_path, "ops", {"build.md": "Run the build."})
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
            content=[ContentItem(file="build.md", description="Build the project")],
        )

        exporter.export_package("ops", source, meta, registry_name="default")

        content = (tmp_path / ".roo" / "commands" / "build.md").read_text()
        assert "Build the project" in content


class TestClaudeCodeCommandsContentType:
    def test_content_type_commands_creates_user_invocable_skills(self, tmp_path):
        """content_type=commands exports each file as a top-level user-invocable skill."""
        source = _make_knowledge_dir(
            tmp_path, "ops", {"start.md": "# Start\nBegin work.", "end.md": "# End\nFinish."}
        )
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations commands",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        result = exporter.export_package("ops", source, meta, registry_name="default")

        # Each file becomes a top-level user-invocable skill
        start_skill = tmp_path / ".claude" / "skills" / "start" / "SKILL.md"
        end_skill = tmp_path / ".claude" / "skills" / "end" / "SKILL.md"
        assert start_skill.exists()
        assert end_skill.exists()
        assert "user-invocable: true" in start_skill.read_text()
        assert "user-invocable: true" in end_skill.read_text()
        assert len(result.files_written) == 2
        # No package-level SKILL.md (commands-only)
        assert not (tmp_path / ".claude" / "skills" / "default" / "ops").exists()

    def test_per_file_hint_commands(self, tmp_path):
        """Per-file export_hint routes individual files as commands."""
        source = _make_knowledge_dir(
            tmp_path,
            "mixed",
            {"guide.md": "# Guide\n", "deploy.md": "# Deploy\n"},
        )
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="mixed",
            description="Mixed package",
            authors=["Test"],
            classification="evergreen",
            content=[
                ContentItem(file="guide.md"),  # default → knowledge → inlined
                ContentItem(file="deploy.md", export_hints={"claude-code": "commands"}),
            ],
        )

        result = exporter.export_package("mixed", source, meta, registry_name="default")

        # guide → inlined in package SKILL.md
        pkg_skill = tmp_path / ".claude" / "skills" / "default" / "mixed" / "SKILL.md"
        assert pkg_skill.exists()
        assert "# Guide" in pkg_skill.read_text()
        # deploy → top-level command skill
        cmd_skill = tmp_path / ".claude" / "skills" / "deploy" / "SKILL.md"
        assert cmd_skill.exists()
        assert "user-invocable: true" in cmd_skill.read_text()
        assert len(result.files_written) == 2  # 1 package SKILL.md + 1 command SKILL.md

    def test_unexport_removes_content_type_commands(self, tmp_path):
        """unexport_package cleans up commands created via content_type."""
        source = _make_knowledge_dir(tmp_path, "ops", {"start.md": "# Start\n"})
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        exporter.export_package("ops", source, meta, registry_name="default")
        assert (tmp_path / ".claude" / "skills" / "start" / "SKILL.md").exists()

        result = exporter.unexport_package("ops", registry_name="default", metadata=meta)
        assert not (tmp_path / ".claude" / "skills" / "start").exists()
        assert len(result.files_removed) == 1

    def test_commands_content_includes_body(self, tmp_path):
        """Command skill includes the full file body."""
        source = _make_knowledge_dir(
            tmp_path, "ops", {"review.md": "Review all changed files for quality."}
        )
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="ops",
            description="Operations",
            authors=["Test"],
            classification="evergreen",
            content_type="commands",
        )

        exporter.export_package("ops", source, meta, registry_name="default")

        content = (tmp_path / ".claude" / "skills" / "review" / "SKILL.md").read_text()
        assert "Review all changed files for quality." in content
        assert "name: review" in content


# ===========================================================================
# Built-in skill export
# ===========================================================================


class TestClaudeCodeBuiltinSkill:
    def test_export_creates_skill_md(self, tmp_path):
        exporter = ClaudeCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# Feature Reference\nSome content here.\n")

        result = exporter.export_builtin_skill(
            skill_name="kt-reference",
            source_path=source,
            description="KT CLI reference",
        )

        assert len(result.files_written) == 1
        skill_md = tmp_path / ".claude" / "skills" / "kt-reference" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "user-invocable: false" in content
        assert 'description: "KT CLI reference"' in content
        assert "name: kt-reference" in content
        assert _MANAGED_MARKER in content
        assert "<!-- kt-source: kt-reference.md -->" in content
        assert "# Feature Reference" in content

    def test_export_idempotent(self, tmp_path):
        exporter = ClaudeCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# V1\n")

        exporter.export_builtin_skill("kt-reference", source, "desc")
        source.write_text("# V2\n")
        result = exporter.export_builtin_skill("kt-reference", source, "desc")

        assert len(result.files_written) == 1
        content = (tmp_path / ".claude" / "skills" / "kt-reference" / "SKILL.md").read_text()
        assert "# V2" in content

    def test_export_skips_conflict(self, tmp_path):
        # Pre-create directory without managed marker
        skill_dir = tmp_path / ".claude" / "skills" / "kt-reference"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("user-created content")

        exporter = ClaudeCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# Ref\n")

        result = exporter.export_builtin_skill("kt-reference", source, "desc")
        assert len(result.files_skipped) == 1
        assert len(result.files_written) == 0
        # User content preserved
        assert (skill_dir / "SKILL.md").read_text() == "user-created content"


class TestRooCodeBuiltinSkill:
    def test_export_creates_skill_md(self, tmp_path):
        from knowledge_tree.exporters.roo_code import _SKILL_MANAGED_COMMENT

        exporter = RooCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# Feature Reference\nSome content here.\n")

        result = exporter.export_builtin_skill(
            skill_name="kt-reference",
            source_path=source,
            description="KT CLI reference",
        )

        assert len(result.files_written) == 1
        skill_md = tmp_path / ".roo" / "skills" / "kt-reference" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert 'description: "KT CLI reference"' in content
        assert "name: kt-reference" in content
        marker = _SKILL_MANAGED_COMMENT.format(
            registry="_builtins", name="_builtins", skill="kt-reference"
        )
        assert marker in content
        assert "<!-- kt-source: kt-reference.md -->" in content
        assert "# Feature Reference" in content

    def test_export_idempotent(self, tmp_path):
        exporter = RooCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# V1\n")

        exporter.export_builtin_skill("kt-reference", source, "desc")
        source.write_text("# V2\n")
        result = exporter.export_builtin_skill("kt-reference", source, "desc")

        assert len(result.files_written) == 1
        content = (tmp_path / ".roo" / "skills" / "kt-reference" / "SKILL.md").read_text()
        assert "# V2" in content

    def test_export_skips_conflict(self, tmp_path):
        skill_dir = tmp_path / ".roo" / "skills" / "kt-reference"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("user-created content")

        exporter = RooCodeExporter(tmp_path)
        source = tmp_path / "kt-reference.md"
        source.write_text("# Ref\n")

        result = exporter.export_builtin_skill("kt-reference", source, "desc")
        assert len(result.files_skipped) == 1
        assert len(result.files_written) == 0


# ===========================================================================
# RooCodeExporter — Modes export
# ===========================================================================


class TestRooCodeModeExport:
    def test_export_modes_creates_roomodes(self, tmp_path):
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            modes=[
                ModeEntry(slug="arch", name="Architect", roleDefinition="Design systems"),
            ],
        )

        source = _make_knowledge_dir(tmp_path, "core", {})
        exporter.export_package("core", source, meta, registry_name="default")

        roomodes = tmp_path / ".roomodes"
        assert roomodes.exists()
        import json

        data = json.loads(roomodes.read_text())
        assert "customModes" in data
        assert len(data["customModes"]) == 1
        assert data["customModes"][0]["slug"] == "arch"
        assert data["customModes"][0]["name"] == "Architect"
        assert data["customModes"][0]["roleDefinition"] == "Design systems"

    def test_export_modes_merges_with_existing(self, tmp_path):
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(
            json.dumps(
                {
                    "customModes": [
                        {"slug": "existing", "name": "Existing Mode", "roleDefinition": "Test"}
                    ]
                }
            )
        )

        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            modes=[
                ModeEntry(slug="arch", name="Architect", roleDefinition="Design systems"),
            ],
        )

        source = _make_knowledge_dir(tmp_path, "core", {})
        exporter.export_package("core", source, meta, registry_name="default")

        data = json.loads(roomodes.read_text())
        assert len(data["customModes"]) == 2
        slugs = [m["slug"] for m in data["customModes"]]
        assert "existing" in slugs
        assert "arch" in slugs

    def test_export_modes_skip_existing_slug(self, tmp_path):
        """Existing slug is skipped with warning; user-defined modes take precedence."""
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(
            json.dumps(
                {
                    "customModes": [
                        {
                            "slug": "arch",
                            "name": "User Architect",
                            "roleDefinition": "User version",
                        }
                    ]
                }
            )
        )

        exporter = RooCodeExporter(tmp_path)
        modes = [ModeEntry(slug="arch", name="KT Architect", roleDefinition="KT version")]
        result = exporter.export_modes("core", modes, registry_name="default")

        assert len(result.warnings) == 1
        assert "already exists" in result.warnings[0]
        assert len(result.files_skipped) == 1
        assert len(result.files_written) == 0

        # User's mode is preserved unchanged
        data = json.loads(roomodes.read_text())
        assert len(data["customModes"]) == 1
        assert data["customModes"][0]["name"] == "User Architect"

    def test_export_modes_force_overwrites(self, tmp_path):
        """force=True overwrites existing slug."""
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(
            json.dumps(
                {"customModes": [{"slug": "arch", "name": "Old", "roleDefinition": "Old def"}]}
            )
        )

        exporter = RooCodeExporter(tmp_path)
        modes = [ModeEntry(slug="arch", name="New", roleDefinition="New def")]
        result = exporter.export_modes("core", modes, registry_name="default", force=True)

        assert len(result.files_written) == 1
        assert len(result.warnings) == 0

        data = json.loads(roomodes.read_text())
        assert len(data["customModes"]) == 1
        assert data["customModes"][0]["name"] == "New"
        assert data["customModes"][0]["roleDefinition"] == "New def"

    def test_export_modes_invalid_json(self, tmp_path):
        """Corrupt .roomodes triggers warning and skips all modes."""
        roomodes = tmp_path / ".roomodes"
        roomodes.write_text("{not valid json!!")

        exporter = RooCodeExporter(tmp_path)
        modes = [ModeEntry(slug="arch", name="Arch", roleDefinition="Def")]
        result = exporter.export_modes("core", modes)

        assert len(result.warnings) == 1
        assert "not valid JSON" in result.warnings[0]
        assert len(result.files_written) == 0
        # Original file untouched
        assert roomodes.read_text() == "{not valid json!!"

    def test_export_modes_optional_fields_omitted(self, tmp_path):
        """Optional mode fields (whenToUse, description, etc.) omitted from JSON when empty."""
        import json

        exporter = RooCodeExporter(tmp_path)
        modes = [ModeEntry(slug="arch", name="Arch", roleDefinition="Def")]
        exporter.export_modes("core", modes)

        data = json.loads((tmp_path / ".roomodes").read_text())
        mode = data["customModes"][0]
        assert "whenToUse" not in mode
        assert "description" not in mode
        assert "customInstructions" not in mode
        assert "groups" not in mode

    def test_unexport_modes_removes_entries(self, tmp_path):
        exporter = RooCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            modes=[
                ModeEntry(slug="arch", name="Architect", roleDefinition="Design systems"),
            ],
        )

        source = _make_knowledge_dir(tmp_path, "core", {})
        exporter.export_package("core", source, meta, registry_name="default")

        result = exporter.unexport_package("core", registry_name="default", mode_slugs=["arch"])

        roomodes = tmp_path / ".roomodes"
        assert not roomodes.exists()
        assert len(result.files_removed) >= 1

    def test_unexport_modes_preserves_user_modes(self, tmp_path):
        """Only KT-exported slugs are removed; user-defined modes survive."""
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(
            json.dumps(
                {
                    "customModes": [
                        {"slug": "kt-mode", "name": "KT", "roleDefinition": "KT def"},
                        {"slug": "user-mode", "name": "User", "roleDefinition": "User def"},
                    ]
                }
            )
        )

        exporter = RooCodeExporter(tmp_path)
        result = exporter.unexport_modes("core", mode_slugs=["kt-mode"])

        assert len(result.files_removed) == 1
        data = json.loads(roomodes.read_text())
        assert len(data["customModes"]) == 1
        assert data["customModes"][0]["slug"] == "user-mode"

    def test_unexport_modes_deletes_empty_file(self, tmp_path):
        """When customModes empties and no other top-level keys, file is deleted."""
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(json.dumps({"customModes": [{"slug": "only", "name": "Only"}]}))

        exporter = RooCodeExporter(tmp_path)
        result = exporter.unexport_modes("core", mode_slugs=["only"])

        assert not roomodes.exists()
        assert len(result.files_removed) == 1

    def test_unexport_modes_keeps_file_with_other_keys(self, tmp_path):
        """File is kept (not deleted) when other top-level keys exist."""
        import json

        roomodes = tmp_path / ".roomodes"
        roomodes.write_text(
            json.dumps({"customModes": [{"slug": "only", "name": "Only"}], "otherConfig": True})
        )

        exporter = RooCodeExporter(tmp_path)
        exporter.unexport_modes("core", mode_slugs=["only"])

        assert roomodes.exists()
        data = json.loads(roomodes.read_text())
        assert data["customModes"] == []
        assert data["otherConfig"] is True


# ===========================================================================
# ClaudeCodeExporter — Modes export
# ===========================================================================


class TestClaudeCodeModeExport:
    def test_export_modes_creates_skill_directories(self, tmp_path):
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            modes=[
                ModeEntry(
                    slug="arch",
                    name="Architect",
                    roleDefinition="Design systems",
                    description="Arch desc",
                ),
            ],
        )

        source = _make_knowledge_dir(tmp_path, "core", {})
        exporter.export_package("core", source, meta, registry_name="default")

        skill_md = tmp_path / ".claude" / "skills" / "arch" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "name: arch" in content
        assert "user-invocable: true" in content
        assert "Design systems" in content

    def test_export_modes_skill_content(self, tmp_path):
        """SKILL.md has roleDefinition + customInstructions in body, whenToUse as description."""
        exporter = ClaudeCodeExporter(tmp_path)
        modes = [
            ModeEntry(
                slug="reviewer",
                name="Code Reviewer",
                roleDefinition="You are a code reviewer.",
                whenToUse="When reviewing PRs.",
                customInstructions="Focus on security.",
            ),
        ]
        exporter.export_modes("core", modes)

        skill_md = tmp_path / ".claude" / "skills" / "reviewer" / "SKILL.md"
        content = skill_md.read_text()
        assert 'description: "When reviewing PRs."' in content
        assert "You are a code reviewer." in content
        assert "Focus on security." in content
        assert _MANAGED_MARKER in content

    def test_export_modes_ignores_groups(self, tmp_path):
        """Groups field is Roo-specific and should not appear in Claude Code SKILL.md."""
        exporter = ClaudeCodeExporter(tmp_path)
        modes = [
            ModeEntry(
                slug="arch",
                name="Arch",
                roleDefinition="Def",
                groups=["read", "edit"],
            ),
        ]
        exporter.export_modes("core", modes)

        content = (tmp_path / ".claude" / "skills" / "arch" / "SKILL.md").read_text()
        assert "groups" not in content
        assert (
            "read" not in content.split("---")[-1]
        )  # not in body (only frontmatter name: arch has 'r')

    def test_export_modes_description_fallback(self, tmp_path):
        """When whenToUse is empty, description falls back to first line of roleDefinition."""
        exporter = ClaudeCodeExporter(tmp_path)
        modes = [
            ModeEntry(
                slug="arch", name="Arch", roleDefinition="First line of role.\nSecond line."
            ),
        ]
        exporter.export_modes("core", modes)

        content = (tmp_path / ".claude" / "skills" / "arch" / "SKILL.md").read_text()
        assert 'description: "First line of role."' in content

    def test_unexport_modes_removes_skills(self, tmp_path):
        exporter = ClaudeCodeExporter(tmp_path)
        meta = PackageMetadata(
            name="core",
            description="Core",
            authors=["Test"],
            classification="evergreen",
            modes=[
                ModeEntry(slug="arch", name="Architect", roleDefinition="Design systems"),
            ],
        )

        source = _make_knowledge_dir(tmp_path, "core", {})
        exporter.export_package("core", source, meta, registry_name="default")

        result = exporter.unexport_package("core", registry_name="default", mode_slugs=["arch"])

        skill_dir = tmp_path / ".claude" / "skills" / "arch"
        assert not skill_dir.exists()
        assert len(result.files_removed) >= 1

    def test_unexport_modes_skips_non_managed(self, tmp_path):
        """Non-KT skill directory with same slug is not removed."""
        skill_dir = tmp_path / ".claude" / "skills" / "arch"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("User's own skill, no managed marker")

        exporter = ClaudeCodeExporter(tmp_path)
        result = exporter.unexport_modes("core", mode_slugs=["arch"])

        assert skill_dir.exists()
        assert len(result.files_removed) == 0
