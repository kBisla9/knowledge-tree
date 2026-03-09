"""Tests for export-related CLI behavior (auto-export, format switching)."""

from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from knowledge_tree.cli import cli
from knowledge_tree.engine import KnowledgeTreeEngine


@pytest.fixture
def cli_project(registry_repo, tmp_path):
    """Create an initialized project with packages installed and exported.

    Returns (project_dir, CliRunner).
    """
    bare, _ = registry_repo
    project = tmp_path / "project"
    project.mkdir()

    engine = KnowledgeTreeEngine(project)
    engine.init(str(bare), branch="main")
    engine.set_config("export_format", "claude-code")
    engine.add_package("api-patterns")  # installs base + api-patterns (auto-exports)

    runner = CliRunner()
    return project, runner


class TestRemoveExportCleanup:
    def test_remove_cleans_up_exports(self, cli_project):
        project, runner = cli_project
        os.chdir(project)

        assert (project / ".claude" / "skills" / "default" / "base" / "SKILL.md").exists()

        result = runner.invoke(cli, ["remove", "base"])

        assert result.exit_code == 0
        assert "Cleaned up claude-code export" in result.output
        assert not (project / ".claude" / "skills" / "default" / "base").exists()


class TestExportStatusIntegration:
    def test_status_shows_export_info(self, cli_project):
        project, runner = cli_project
        os.chdir(project)

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Export: claude-code" in result.output

    def test_info_shows_export_format(self, cli_project):
        project, runner = cli_project
        os.chdir(project)

        result = runner.invoke(cli, ["info", "base"])

        assert result.exit_code == 0
        assert "claude-code" in result.output


class TestUpdateFormatSwitch:
    def test_update_format_switch(self, cli_project):
        """--format roo-code should unexport claude-code and export roo-code."""
        project, runner = cli_project
        os.chdir(project)

        # Verify claude-code exports exist
        assert (project / ".claude" / "skills" / "default" / "base" / "SKILL.md").exists()

        result = runner.invoke(cli, ["update", "--format", "roo-code"])

        assert result.exit_code == 0
        assert "Switched tool format" in result.output
        # Old exports should be cleaned up
        assert not (project / ".claude" / "skills" / "default" / "base").exists()
        # New exports should exist
        rules = list((project / ".roo" / "rules").glob("kt-default-base-*.md"))
        assert len(rules) >= 1

    def test_update_format_same_no_switch(self, cli_project):
        """--format with the same format should not trigger a switch."""
        project, runner = cli_project
        os.chdir(project)

        result = runner.invoke(cli, ["update", "--format", "claude-code"])

        assert result.exit_code == 0
        assert "Switched tool format" not in result.output

    def test_update_format_invalid(self, cli_project):
        """--format with invalid name should error."""
        project, runner = cli_project
        os.chdir(project)

        result = runner.invoke(cli, ["update", "--format", "unknown"])

        assert result.exit_code == 1
        assert "Unknown format" in result.output

    def test_update_without_format_unchanged(self, cli_project):
        """Update without --format should work normally."""
        project, runner = cli_project
        os.chdir(project)

        result = runner.invoke(cli, ["update"])

        assert result.exit_code == 0
        assert "Switched tool format" not in result.output
        # Exports should still be there
        assert (project / ".claude" / "skills" / "default" / "base" / "SKILL.md").exists()
