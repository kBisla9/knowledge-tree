"""Tests for registry add (full onboarding), commands, and templates functionality."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knowledge_tree.engine import KnowledgeTreeEngine
from knowledge_tree.exporters.claude_code import (
    _MANAGED_MARKER,
    ClaudeCodeExporter,
)
from knowledge_tree.models import (
    CommandEntry,
    PackageMetadata,
    Registry,
    RegistryPreview,
    TemplateMapping,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture
def wire_registry_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a registry repo with a package that has commands + templates.

    Returns (bare_repo_path, working_clone_path).
    """
    bare = tmp_path / "wire-registry.git"
    bare.mkdir()
    _run_git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    work = tmp_path / "wire-work"
    _run_git(["clone", str(bare), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test User"], cwd=work)

    # Create packages/core/ — a package with commands (no templates on package)
    core_dir = work / "packages" / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "package.yaml").write_text(
        "name: core\n"
        "description: Session management protocol for AI coding agents\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - session\n  - agent\n"
        "commands:\n"
        "  - name: start-session\n"
        "    description: Load project context and start a new session\n"
        "  - name: end-session\n"
        "    description: Persist session knowledge and update project status\n"
    )
    cmd_dir = core_dir / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "start-session.md").write_text(
        "# Start Session\n\nLoad project context and verify environment.\n"
    )
    (cmd_dir / "end-session.md").write_text(
        "# End Session\n\nPersist session knowledge and log session.\n"
    )

    # Templates live at registry level
    tpl_dir = work / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "AGENTS.md").write_text("# Agent Memory\n\nTrack what you learn.\n")
    (tpl_dir / "STATUS.md").write_text("# Project Status\n\nCurrent state.\n")

    # Create packages/info/ — a package with only content (no commands/templates)
    info_dir = work / "packages" / "info"
    info_dir.mkdir(parents=True)
    (info_dir / "package.yaml").write_text(
        "name: info\n"
        "description: Background knowledge\n"
        "authors:\n  - Test Author\n"
        "classification: evergreen\n"
        "tags:\n  - knowledge\n"
    )
    (info_dir / "overview.md").write_text("# Overview\n\nGeneral background info.\n")

    # registry.yaml (templates at registry level, with gitignore)
    (work / "registry.yaml").write_text(
        "gitignore:\n"
        "  - agent-session-management/\n"
        "templates:\n"
        "  - source: templates/AGENTS.md\n"
        "    dest: AGENTS.md\n"
        "  - source: templates/STATUS.md\n"
        "    dest: project_status/STATUS.md\n"
        "packages:\n"
        "  core:\n"
        "    description: Session management protocol for AI coding agents\n"
        "    classification: evergreen\n"
        "    tags:\n      - session\n      - agent\n"
        "    path: packages/core\n"
        "  info:\n"
        "    description: Background knowledge\n"
        "    classification: evergreen\n"
        "    tags:\n      - knowledge\n"
        "    path: packages/info\n"
    )

    _run_git(["add", "."], cwd=work)
    _run_git(["commit", "-m", "Add wire test registry"], cwd=work)
    _run_git(["push", "origin", "main"], cwd=work)

    return bare, work


# ===========================================================================
# CommandEntry / TemplateMapping models
# ===========================================================================


class TestCommandEntry:
    def test_defaults(self):
        cmd = CommandEntry()
        assert cmd.name == ""
        assert cmd.description == ""

    def test_explicit_values(self):
        cmd = CommandEntry(name="start", description="Start")
        assert cmd.name == "start"
        assert cmd.description == "Start"


class TestTemplateMapping:
    def test_defaults(self):
        tmpl = TemplateMapping()
        assert tmpl.source == ""
        assert tmpl.dest == ""

    def test_explicit_values(self):
        tmpl = TemplateMapping(source="templates/A.md", dest="A.md")
        assert tmpl.source == "templates/A.md"
        assert tmpl.dest == "A.md"


# ===========================================================================
# PackageMetadata with commands and templates
# ===========================================================================


class TestPackageMetadataCommandsTemplates:
    def test_round_trip_with_commands(self, tmp_path):
        """Commands survive a write->read round trip."""
        path = tmp_path / "package.yaml"
        meta = PackageMetadata(
            name="core",
            description="Test",
            authors=["A"],
            classification="evergreen",
            commands=[
                CommandEntry(name="start", description="Start it"),
                CommandEntry(name="stop"),
            ],
        )
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)

        assert len(loaded.commands) == 2
        assert loaded.commands[0].name == "start"
        assert loaded.commands[0].description == "Start it"
        assert loaded.commands[1].name == "stop"
        assert loaded.commands[1].description == ""

    def test_registry_round_trip_with_templates(self, tmp_path):
        """Templates on Registry survive a write->read round trip."""
        path = tmp_path / "registry.yaml"
        reg = Registry(
            templates=[
                TemplateMapping(source="templates/A.md", dest="A.md"),
                TemplateMapping(source="templates/B.md", dest="sub/B.md"),
            ],
        )
        reg.to_yaml_file(path)
        loaded = Registry.from_yaml_file(path)

        assert len(loaded.templates) == 2
        assert loaded.templates[0].source == "templates/A.md"
        assert loaded.templates[0].dest == "A.md"
        assert loaded.templates[1].dest == "sub/B.md"

    def test_string_shorthand_commands(self, tmp_path):
        """String entries in commands list become CommandEntry(name=s)."""
        path = tmp_path / "package.yaml"
        path.write_text(
            "name: test\n"
            "description: Test\n"
            "authors:\n  - A\n"
            "classification: evergreen\n"
            "commands:\n"
            "  - start-session\n"
            "  - end-session\n"
        )
        loaded = PackageMetadata.from_yaml_file(path)
        assert len(loaded.commands) == 2
        assert loaded.commands[0].name == "start-session"
        assert loaded.commands[0].description == ""
        assert loaded.commands[1].name == "end-session"

    def test_no_commands(self, tmp_path):
        """Backward compat: package without commands loads fine."""
        path = tmp_path / "package.yaml"
        path.write_text(
            "name: base\ndescription: Basic\nauthors:\n  - A\nclassification: evergreen\n"
        )
        loaded = PackageMetadata.from_yaml_file(path)
        assert loaded.commands == []

    def test_classification_defaults_to_seasonal(self, tmp_path):
        """Package without classification defaults to seasonal."""
        path = tmp_path / "package.yaml"
        path.write_text("name: base\ndescription: Basic\nauthors:\n  - A\n")
        loaded = PackageMetadata.from_yaml_file(path)
        assert loaded.classification == "seasonal"

    def test_registry_without_templates(self, tmp_path):
        """Registry without templates loads with empty list."""
        path = tmp_path / "registry.yaml"
        path.write_text("packages: {}\n")
        loaded = Registry.from_yaml_file(path)
        assert loaded.templates == []

    def test_registry_ignores_legacy_gitignore_field(self, tmp_path):
        """Legacy gitignore field in registry.yaml is silently ignored."""
        path = tmp_path / "registry.yaml"
        path.write_text("gitignore:\n  - foo/\npackages: {}\n")
        loaded = Registry.from_yaml_file(path)
        assert loaded.packages == {}


# ===========================================================================
# Claude Code exporter — command export
# ===========================================================================


class TestClaudeCodeCommandExport:
    def test_export_commands_creates_skill_dirs(self, tmp_path):
        """Each command gets a top-level .claude/skills/<name>/SKILL.md."""
        exporter = ClaudeCodeExporter(tmp_path)

        # Create command source files
        cmd_dir = tmp_path / "src" / "commands"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "start-session.md").write_text("# Start Session\nLoad context.\n")
        (cmd_dir / "end-session.md").write_text("# End Session\nPersist knowledge.\n")

        commands = [
            (
                CommandEntry(name="start-session", description="Start a session"),
                cmd_dir / "start-session.md",
            ),
            (
                CommandEntry(name="end-session", description="End a session"),
                cmd_dir / "end-session.md",
            ),
        ]

        result = exporter.export_commands("core", commands)

        assert len(result.files_written) == 2
        start_skill = tmp_path / ".claude" / "skills" / "start-session" / "SKILL.md"
        end_skill = tmp_path / ".claude" / "skills" / "end-session" / "SKILL.md"
        assert start_skill.exists()
        assert end_skill.exists()

    def test_command_skill_frontmatter(self, tmp_path):
        """Command SKILL.md has correct frontmatter."""
        exporter = ClaudeCodeExporter(tmp_path)

        cmd_dir = tmp_path / "src" / "commands"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "my-cmd.md").write_text("# My Command\n\nDo the thing.\n")

        commands = [
            (
                CommandEntry(name="my-cmd", description="Do something"),
                cmd_dir / "my-cmd.md",
            ),
        ]
        exporter.export_commands("test", commands)

        content = (tmp_path / ".claude" / "skills" / "my-cmd" / "SKILL.md").read_text()
        assert "user-invocable: true" in content
        assert "disable-model-invocation" not in content
        assert _MANAGED_MARKER in content
        assert 'description: "Do something"' in content

    def test_command_body_included(self, tmp_path):
        """Command file content appears in SKILL.md body."""
        exporter = ClaudeCodeExporter(tmp_path)
        cmd_dir = tmp_path / "src"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "greet.md").write_text("# Greet\n\nSay hello to the user.\n")

        commands = [
            (CommandEntry(name="greet", description="Greet"), cmd_dir / "greet.md"),
        ]
        exporter.export_commands("test", commands)

        content = (tmp_path / ".claude" / "skills" / "greet" / "SKILL.md").read_text()
        assert "Say hello to the user." in content

    def test_command_conflict_skips(self, tmp_path):
        """Existing non-KT command dir is skipped."""
        exporter = ClaudeCodeExporter(tmp_path)

        # Pre-create a non-KT skill dir
        conflict_dir = tmp_path / ".claude" / "skills" / "my-cmd"
        conflict_dir.mkdir(parents=True)
        (conflict_dir / "SKILL.md").write_text("---\nname: my-cmd\n---\nUser's own skill.\n")

        cmd_dir = tmp_path / "src"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "my-cmd.md").write_text("# My\n")

        commands = [
            (CommandEntry(name="my-cmd", description="My"), cmd_dir / "my-cmd.md"),
        ]
        result = exporter.export_commands("test", commands)

        assert len(result.files_skipped) == 1
        assert len(result.files_written) == 0
        # Original file preserved
        assert "User's own skill." in (conflict_dir / "SKILL.md").read_text()

    def test_unexport_commands(self, tmp_path):
        """unexport_commands removes KT-managed command dirs."""
        exporter = ClaudeCodeExporter(tmp_path)

        # Create a managed command
        cmd_dir = tmp_path / ".claude" / "skills" / "start-session"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "SKILL.md").write_text(f"---\nname: start-session\n---\n{_MANAGED_MARKER}\n")

        result = exporter.unexport_commands("core", ["start-session"])
        assert len(result.files_removed) == 1
        assert not cmd_dir.exists()

    def test_unexport_commands_skips_non_managed(self, tmp_path):
        """unexport_commands leaves non-KT command dirs alone."""
        exporter = ClaudeCodeExporter(tmp_path)

        cmd_dir = tmp_path / ".claude" / "skills" / "user-cmd"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "SKILL.md").write_text("---\nname: user-cmd\n---\nUser skill.\n")

        result = exporter.unexport_commands("core", ["user-cmd"])
        assert len(result.files_removed) == 0
        assert cmd_dir.exists()

    def test_export_package_with_commands_only(self, tmp_path):
        """Commands-only package: no knowledge SKILL.md, but command skills created."""
        exporter = ClaudeCodeExporter(tmp_path)

        # Source dir with only commands/ subdirectory (no top-level files)
        source = tmp_path / "pkg-source" / "default" / "core"
        source.mkdir(parents=True)
        cmd_sub = source / "commands"
        cmd_sub.mkdir()
        (cmd_sub / "start.md").write_text("# Start\n")

        meta = PackageMetadata(
            name="core",
            description="Commands only",
            authors=["A"],
            classification="evergreen",
            commands=[CommandEntry(name="start", description="Start")],
        )

        exporter.export_package("core", source, meta, registry_name="default")

        # Command skill should exist
        assert (tmp_path / ".claude" / "skills" / "start" / "SKILL.md").exists()
        # Knowledge skill should NOT exist (commands-only)
        assert not (tmp_path / ".claude" / "skills" / "default" / "core" / "SKILL.md").exists()

    def test_export_package_with_content_and_commands(self, tmp_path):
        """Package with both content and commands creates both skill types."""
        exporter = ClaudeCodeExporter(tmp_path)

        source = tmp_path / "pkg-source" / "default" / "mixed"
        source.mkdir(parents=True)
        (source / "overview.md").write_text("# Overview\n")
        cmd_sub = source / "commands"
        cmd_sub.mkdir()
        (cmd_sub / "run.md").write_text("# Run\n")

        meta = PackageMetadata(
            name="mixed",
            description="Has both",
            authors=["A"],
            classification="evergreen",
            commands=[CommandEntry(name="run", description="Run it")],
        )

        exporter.export_package("mixed", source, meta, registry_name="default")

        # Both types should exist
        assert (tmp_path / ".claude" / "skills" / "default" / "mixed" / "SKILL.md").exists()
        assert (tmp_path / ".claude" / "skills" / "run" / "SKILL.md").exists()

    def test_description_extracted_from_file(self, tmp_path):
        """When CommandEntry has no description, extract from file content."""
        exporter = ClaudeCodeExporter(tmp_path)
        cmd_dir = tmp_path / "src"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "my-cmd.md").write_text("# My Amazing Command\n\nDo stuff.\n")

        commands = [
            (CommandEntry(name="my-cmd"), cmd_dir / "my-cmd.md"),
        ]
        exporter.export_commands("test", commands)

        content = (tmp_path / ".claude" / "skills" / "my-cmd" / "SKILL.md").read_text()
        assert 'description: "My Amazing Command"' in content


# ===========================================================================
# Engine — _detect_tool_format
# ===========================================================================


class TestDetectToolFormat:
    def test_detects_claude_code(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        engine = KnowledgeTreeEngine(tmp_path)
        assert engine._detect_tool_format() == "claude-code"

    def test_detects_roo_code(self, tmp_path):
        (tmp_path / ".roo").mkdir()
        engine = KnowledgeTreeEngine(tmp_path)
        assert engine._detect_tool_format() == "roo-code"

    def test_returns_none_for_unknown(self, tmp_path):
        engine = KnowledgeTreeEngine(tmp_path)
        assert engine._detect_tool_format() is None

    def test_claude_code_takes_precedence(self, tmp_path):
        """If both .claude/ and .roo/ exist, .claude/ wins."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".roo").mkdir()
        engine = KnowledgeTreeEngine(tmp_path)
        assert engine._detect_tool_format() == "claude-code"


# ===========================================================================
# Engine — _instantiate_templates
# ===========================================================================


class TestInstantiateTemplates:
    def test_copies_template_files(self, tmp_path):
        engine = KnowledgeTreeEngine(tmp_path)

        # Create source
        source_base = tmp_path / "src"
        tpl_dir = source_base / "templates"
        tpl_dir.mkdir(parents=True)
        (tpl_dir / "AGENTS.md").write_text("# Agent Memory\n")

        templates = [TemplateMapping(source="templates/AGENTS.md", dest="AGENTS.md")]
        inst, skip = engine._instantiate_templates(templates, source_base)

        assert inst == ["AGENTS.md"]
        assert skip == []
        assert (tmp_path / "AGENTS.md").read_text() == "# Agent Memory\n"

    def test_creates_parent_dirs(self, tmp_path):
        engine = KnowledgeTreeEngine(tmp_path)

        source_base = tmp_path / "src"
        tpl_dir = source_base / "templates"
        tpl_dir.mkdir(parents=True)
        (tpl_dir / "STATUS.md").write_text("# Status\n")

        templates = [
            TemplateMapping(source="templates/STATUS.md", dest="project_status/STATUS.md")
        ]
        inst, _skip = engine._instantiate_templates(templates, source_base)

        assert inst == ["project_status/STATUS.md"]
        assert (tmp_path / "project_status" / "STATUS.md").exists()

    def test_skips_existing_dest(self, tmp_path):
        """Templates are not overwritten if they already exist."""
        engine = KnowledgeTreeEngine(tmp_path)

        # Pre-create destination
        (tmp_path / "AGENTS.md").write_text("# My Custom Content\n")

        source_base = tmp_path / "src"
        tpl_dir = source_base / "templates"
        tpl_dir.mkdir(parents=True)
        (tpl_dir / "AGENTS.md").write_text("# Agent Memory\n")

        templates = [TemplateMapping(source="templates/AGENTS.md", dest="AGENTS.md")]
        inst, skip = engine._instantiate_templates(templates, source_base)

        assert inst == []
        assert skip == ["AGENTS.md"]
        # Original content preserved
        assert "My Custom Content" in (tmp_path / "AGENTS.md").read_text()

    def test_skips_missing_source(self, tmp_path):
        """Template with missing source file is skipped."""
        engine = KnowledgeTreeEngine(tmp_path)
        source_base = tmp_path / "src"
        source_base.mkdir()

        templates = [TemplateMapping(source="templates/MISSING.md", dest="MISSING.md")]
        inst, skip = engine._instantiate_templates(templates, source_base)

        assert inst == []
        assert skip == ["MISSING.md"]

    def test_idempotent(self, tmp_path):
        """Running twice produces same result (second run all skipped)."""
        engine = KnowledgeTreeEngine(tmp_path)

        source_base = tmp_path / "src"
        tpl_dir = source_base / "templates"
        tpl_dir.mkdir(parents=True)
        (tpl_dir / "A.md").write_text("# A\n")

        templates = [TemplateMapping(source="templates/A.md", dest="A.md")]
        inst1, skip1 = engine._instantiate_templates(templates, source_base)
        inst2, skip2 = engine._instantiate_templates(templates, source_base)

        assert inst1 == ["A.md"]
        assert skip1 == []
        assert inst2 == []
        assert skip2 == ["A.md"]


# ===========================================================================
# Engine — add_registry (full onboarding, replaces wire)
# ===========================================================================


class TestRegistryAdd:
    def test_installs_and_exports(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() installs packages, exports skills, and instantiates templates."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        (project / ".claude").mkdir()  # tool marker

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), tool_format="claude-code")

        # Packages installed
        assert "core" in result.packages_installed
        assert "info" in result.packages_installed

        # Commands installed
        assert "start-session" in result.commands_installed
        assert "end-session" in result.commands_installed

        # Command skill files exist
        start_skill = project / ".claude" / "skills" / "start-session" / "SKILL.md"
        end_skill = project / ".claude" / "skills" / "end-session" / "SKILL.md"
        assert start_skill.exists()
        assert end_skill.exists()
        assert "user-invocable: true" in start_skill.read_text()

        # Knowledge skill for info package
        info_skills = list((project / ".claude" / "skills").rglob("*/info/SKILL.md"))
        assert len(info_skills) == 1

        # Templates instantiated
        assert "AGENTS.md" in result.templates_instantiated
        assert "project_status/STATUS.md" in result.templates_instantiated
        assert (project / "AGENTS.md").exists()
        assert (project / "project_status" / "STATUS.md").exists()

        # Files exported
        assert result.files_exported > 0

    def test_auto_inits_project(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() auto-initializes .knowledge-tree/ if it doesn't exist."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), tool_format="claude-code")

        assert (project / ".knowledge-tree").is_dir()
        assert (project / ".knowledge-tree" / ".gitignore").exists()
        assert (project / ".knowledge-tree" / ".gitignore").read_text().strip() == "*"
        assert result.files_exported > 0

    def test_derives_name_from_url(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() derives registry name from URL path."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), tool_format="claude-code")

        # Bare repo is named "wire-registry.git" -> name should be "wire-registry"
        assert result.name == "wire-registry"

    def test_custom_name(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() uses custom registry name when provided."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), name="my-sessions", tool_format="claude-code")

        assert result.name == "my-sessions"

    def test_idempotent(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """Running add_registry() twice is safe — second run skips gracefully."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), tool_format="claude-code")
        result2 = engine.add_registry(str(bare), tool_format="claude-code")

        # Second run: packages already installed
        assert len(result2.packages_installed) == 0
        assert len(result2.packages_skipped) > 0

        # Templates already exist
        assert len(result2.templates_skipped) > 0
        assert len(result2.templates_instantiated) == 0

    def test_per_dir_gitignore_in_knowledge_tree(
        self, wire_registry_repo: tuple[Path, Path], tmp_path
    ):
        """add_registry() creates .gitignore with '*' inside .knowledge-tree/."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), tool_format="claude-code")

        gitignore = project / ".knowledge-tree" / ".gitignore"
        assert gitignore.exists()
        assert "*" in gitignore.read_text()

    def test_per_dir_gitignore_in_tool_dir(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """Exporting creates .gitignore with '*' inside the tool directory."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), tool_format="claude-code")

        gitignore = project / ".claude" / ".gitignore"
        assert gitignore.exists()
        assert "*" in gitignore.read_text()

    def test_no_install_mode(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry(install_packages=False) only registers the source."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), install_packages=False)

        assert len(result.available_packages) > 0
        assert result.packages_installed == []
        assert result.files_exported == 0
        assert result.templates_instantiated == []

    def test_no_export_without_tool_format(self, wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() without tool_format installs but doesn't export."""
        bare, _ = wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare))

        assert len(result.packages_installed) > 0
        assert result.files_exported == 0
        # Templates still instantiated (tool-agnostic)
        assert len(result.templates_instantiated) > 0


# ===========================================================================
# Registry add — Roo Code format
# ===========================================================================


@pytest.fixture
def roo_wire_registry_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a registry repo with mixed content types for roo-code testing.

    Returns (bare_repo_path, working_clone_path).
    """
    bare = tmp_path / "roo-registry.git"
    bare.mkdir()
    _run_git(["init", "--bare", "--initial-branch=main"], cwd=bare)

    work = tmp_path / "roo-work"
    _run_git(["clone", str(bare), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "test@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test User"], cwd=work)

    # packages/core/ — commands-only package
    core_dir = work / "packages" / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "package.yaml").write_text(
        "name: core\n"
        "description: Session management\n"
        "authors:\n  - Test\n"
        "classification: evergreen\n"
        "commands:\n"
        "  - name: start-session\n"
        "    description: Start a session\n"
    )
    cmd_dir = core_dir / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "start-session.md").write_text("# Start Session\n\nLoad project context.\n")

    # packages/rules-pkg/ — knowledge content (-> rules)
    rules_dir = work / "packages" / "rules-pkg"
    rules_dir.mkdir(parents=True)
    (rules_dir / "package.yaml").write_text(
        "name: rules-pkg\n"
        "description: Coding conventions\n"
        "authors:\n  - Test\n"
        "classification: evergreen\n"
    )
    (rules_dir / "conventions.md").write_text("# Conventions\n\nFollow these rules.\n")

    # registry.yaml
    (work / "registry.yaml").write_text(
        "packages:\n"
        "  core:\n"
        "    description: Session management\n"
        "    classification: evergreen\n"
        "    path: packages/core\n"
        "  rules-pkg:\n"
        "    description: Coding conventions\n"
        "    classification: evergreen\n"
        "    path: packages/rules-pkg\n"
    )

    _run_git(["add", "."], cwd=work)
    _run_git(["commit", "-m", "Add roo wire test registry"], cwd=work)
    _run_git(["push", "origin", "main"], cwd=work)

    return bare, work


class TestRegistryAddRooCode:
    def test_roo_code_creates_rules(self, roo_wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() with roo-code format creates .roo/rules/ files."""
        bare, _ = roo_wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), tool_format="roo-code")

        # Knowledge package -> rules
        rules_dir = project / ".roo" / "rules"
        assert rules_dir.is_dir()
        rules_files = list(rules_dir.glob("kt-roo-registry-rules-pkg-*.md"))
        assert len(rules_files) == 1
        content = rules_files[0].read_text()
        assert "Conventions" in content

    def test_roo_code_creates_commands(self, roo_wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() with roo-code format creates .roo/commands/ files."""
        bare, _ = roo_wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), tool_format="roo-code")

        # Commands exported
        assert "start-session" in result.commands_installed
        cmd_file = project / ".roo" / "commands" / "start-session.md"
        assert cmd_file.exists()
        content = cmd_file.read_text()
        assert "Load project context" in content

    def test_roo_code_explicit_format(self, roo_wire_registry_repo: tuple[Path, Path], tmp_path):
        """add_registry() with explicit roo-code format works without .roo/ marker."""
        bare, _ = roo_wire_registry_repo
        project = tmp_path / "my-project"
        project.mkdir()

        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(bare), tool_format="roo-code")

        assert result.files_exported > 0
        # Rules created even without .roo/ pre-existing
        rules_dir = project / ".roo" / "rules"
        assert rules_dir.is_dir()


# ---------------------------------------------------------------------------
# TestPreviewRegistry
# ---------------------------------------------------------------------------


class TestPreviewRegistry:
    """Tests for engine.preview_registry() and selected_packages."""

    def test_preview_returns_packages(self, registry_repo, tmp_path):
        bare, _ = registry_repo
        project = tmp_path / "preview-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        preview = engine.preview_registry(str(bare))

        assert isinstance(preview, RegistryPreview)
        assert preview.name  # auto-derived
        assert preview.source == str(bare)
        assert preview.source_type == "git"
        names = [p.name for p in preview.packages]
        assert "base" in names
        assert "api-patterns" in names
        assert len(preview.packages) == 4

    def test_preview_package_metadata(self, registry_repo, tmp_path):
        bare, _ = registry_repo
        project = tmp_path / "preview-meta"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        preview = engine.preview_registry(str(bare))

        base = next(p for p in preview.packages if p.name == "base")
        assert base.description == "Universal coding conventions"
        assert base.classification == "evergreen"
        assert "core" in base.tags

        api = next(p for p in preview.packages if p.name == "api-patterns")
        assert api.classification == "seasonal"
        assert "base" in api.depends_on

    def test_preview_then_add_no_double_clone(self, registry_repo, tmp_path):
        """After preview_registry, add_registry should reuse the cached source."""
        bare, _ = registry_repo
        project = tmp_path / "preview-add"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        preview = engine.preview_registry(str(bare))
        result = engine.add_registry(str(bare), tool_format=None, install_packages=True)

        assert result.name == preview.name
        assert len(result.packages_installed) == 4

    def test_selected_packages(self, registry_repo, tmp_path):
        """add_registry with selected_packages installs only those."""
        bare, _ = registry_repo
        project = tmp_path / "selected-pkgs"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        engine.preview_registry(str(bare))
        result = engine.add_registry(
            str(bare),
            install_packages=True,
            selected_packages=["base", "git-conventions"],
        )

        assert "base" in result.packages_installed
        assert "git-conventions" in result.packages_installed
        assert "api-patterns" not in result.packages_installed
        assert "session-mgmt" not in result.packages_installed

    def test_selected_packages_exports_only_selected(self, registry_repo, tmp_path):
        """Export should only cover selected packages."""
        bare, _ = registry_repo
        project = tmp_path / "selected-export"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        engine.preview_registry(str(bare))
        result = engine.add_registry(
            str(bare),
            tool_format="claude-code",
            install_packages=True,
            selected_packages=["base"],
        )

        assert result.files_exported > 0
        # base should be exported
        base_skill = project / ".claude" / "skills"
        assert base_skill.is_dir()
        # api-patterns should NOT be exported
        config = engine._load_config()
        installed_names = [p.name for p in config.packages]
        assert "base" in installed_names
        assert "api-patterns" not in installed_names

    def test_selected_packages_empty_list(self, registry_repo, tmp_path):
        """Empty selected_packages installs nothing."""
        bare, _ = registry_repo
        project = tmp_path / "empty-select"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        engine.preview_registry(str(bare))
        result = engine.add_registry(str(bare), install_packages=True, selected_packages=[])

        assert result.packages_installed == []
        assert result.files_exported == 0

    def test_preview_cancel_cleanup(self, registry_repo, tmp_path):
        """After preview, remove_registry cleans up properly."""
        bare, _ = registry_repo
        project = tmp_path / "cancel-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        preview = engine.preview_registry(str(bare))
        assert (project / ".knowledge-tree" / "registries" / preview.name).is_dir()

        engine.remove_registry(preview.name, force=True)
        assert not (project / ".knowledge-tree" / "registries" / preview.name).is_dir()
