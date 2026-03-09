"""Tests for Knowledge Tree CLI."""

from __future__ import annotations

import pytest
from rich.console import Console

from knowledge_tree import cli as cli_module
from knowledge_tree.cli import cli

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_consoles(monkeypatch):
    """Patch Rich consoles for deterministic, ANSI-free output."""
    monkeypatch.setattr(cli_module, "console", Console(no_color=True, width=120))
    monkeypatch.setattr(
        cli_module,
        "err_console",
        Console(stderr=True, no_color=True, width=120),
    )


@pytest.fixture
def cli_project(registry_repo, tmp_path, monkeypatch, cli_runner, _patch_consoles):
    """An initialized KT project with CWD set.

    Returns (runner, project_path, bare_repo_path).
    """
    bare, _ = registry_repo
    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.chdir(project)

    result = cli_runner.invoke(cli, ["init", str(bare), "--name", "default", "--no-install"])
    assert result.exit_code == 0, f"init failed: {result.output}"

    return cli_runner, project, bare


@pytest.fixture
def cli_uninit(registry_repo, tmp_path, monkeypatch, cli_runner, _patch_consoles):
    """A non-initialized project with CWD set.

    Returns (runner, project_path, bare_repo_path).
    """
    bare, _ = registry_repo
    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.chdir(project)

    return cli_runner, project, bare


# ---------------------------------------------------------------------------
# TestCliGroup
# ---------------------------------------------------------------------------


class TestCliGroup:
    def test_help(self, cli_runner, _patch_consoles):
        result = cli_runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Knowledge Tree" in result.output

    def test_version(self, cli_runner, _patch_consoles):
        result = cli_runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.1" in result.output

    def test_unknown_command(self, cli_runner, _patch_consoles):
        result = cli_runner.invoke(cli, ["nonexistent-cmd"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_success(self, cli_uninit):
        runner, _project, bare = cli_uninit
        result = runner.invoke(cli, ["init", str(bare), "--no-install"])
        assert result.exit_code == 0
        assert "Initialized Knowledge Tree" in result.output
        assert "Available packages: 4" in result.output

    def test_init_with_install(self, cli_uninit, _patch_consoles):
        runner, _project, bare = cli_uninit
        result = runner.invoke(cli, ["init", str(bare), "--format", "claude-code"])
        assert result.exit_code == 0
        assert "Initialized Knowledge Tree" in result.output
        assert "Packages installed" in result.output

    def test_init_custom_name(self, cli_uninit):
        runner, project, bare = cli_uninit
        result = runner.invoke(cli, ["init", str(bare), "--name", "primary", "--no-install"])
        assert result.exit_code == 0
        assert "primary" in result.output
        assert (project / ".knowledge-tree" / "registries" / "primary").is_dir()

    def test_init_already_initialized(self, cli_project):
        runner, _, bare = cli_project
        result = runner.invoke(cli, ["init", str(bare), "--no-install"])
        assert result.exit_code == 1

    def test_empty_init(self, cli_uninit):
        runner, project, _ = cli_uninit
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert "Empty project" in result.output
        assert (project / ".knowledge-tree" / "kt.yaml").exists()


# ---------------------------------------------------------------------------
# TestAdd
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_single(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "base"])
        assert result.exit_code == 0
        assert "base" in result.output
        assert "Installed 1 package" in result.output

    def test_add_with_dependency(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "api-patterns"])
        assert result.exit_code == 0
        assert "base" in result.output
        assert "api-patterns" in result.output
        assert "2 packages" in result.output

    def test_add_already_installed(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["add", "base"])
        assert result.exit_code == 0
        assert "already installed" in result.output
        assert "Nothing new" in result.output

    def test_add_nonexistent(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "zzzzzzz"])
        assert result.exit_code == 1

    def test_add_with_suggestion(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "bse"])
        assert result.exit_code == 1

    def test_add_missing_argument(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add"])
        assert result.exit_code == 2

    def test_add_shows_registry(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "base"])
        assert "default" in result.output


# ---------------------------------------------------------------------------
# TestRemove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_success(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["remove", "base"])
        assert result.exit_code == 0
        assert "base" in result.output
        assert "Removed base" in result.output

    def test_remove_with_dependents(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "api-patterns"])
        result = runner.invoke(cli, ["remove", "base"])
        assert result.exit_code == 0
        assert "Warning" in result.output
        assert "api-patterns" in result.output

    def test_remove_not_installed(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["remove", "nonexistent"])
        assert result.exit_code == 1

    def test_remove_with_suggestion(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["remove", "bse"])
        assert result.exit_code == 1

    def test_remove_missing_argument(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["remove"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# TestList
# ---------------------------------------------------------------------------


class TestStatusPackages:
    """Tests for package listing via kt status (absorbed from kt list)."""

    def test_status_installed_packages(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Installed Packages" in result.output
        assert "base" in result.output

    def test_status_no_packages(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No packages installed" in result.output

    def test_status_available(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["status", "--available"])
        assert result.exit_code == 0
        assert "Available Packages" in result.output
        assert "api-patterns" in result.output
        assert "git-conventions" in result.output

    def test_status_all_installed(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        runner.invoke(cli, ["add", "git-conventions"])
        runner.invoke(cli, ["add", "api-patterns"])
        runner.invoke(cli, ["add", "session-mgmt"])
        result = runner.invoke(cli, ["status", "--available"])
        assert result.exit_code == 0
        assert "All packages are installed" in result.output

    def test_status_community_empty(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["status", "--community"])
        assert result.exit_code == 0
        assert "No community packages" in result.output

    def test_status_table_columns(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["status"])
        assert "Name" in result.output
        assert "Description" in result.output
        assert "Type" in result.output
        assert "Registry" in result.output


# ---------------------------------------------------------------------------
# TestSearch
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_found(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["search", "base"])
        assert result.exit_code == 0
        assert "base" in result.output

    def test_search_by_tag(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["search", "api"])
        assert result.exit_code == 0
        assert "api-patterns" in result.output

    def test_search_no_results(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["search", "nonexistent-xyz"])
        assert result.exit_code == 0
        assert "No packages match" in result.output

    def test_search_shows_installed(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["search", "base"])
        assert result.exit_code == 0
        assert "yes" in result.output


# ---------------------------------------------------------------------------
# TestTree
# ---------------------------------------------------------------------------


class TestTree:
    def test_tree_output(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["tree"])
        assert result.exit_code == 0
        assert "Knowledge Tree" in result.output

    def test_tree_shows_packages(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["tree"])
        assert "base" in result.output
        assert "git-conventions" in result.output
        assert "api-patterns" in result.output

    def test_tree_installed_status(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["tree"])
        assert "installed" in result.output


# ---------------------------------------------------------------------------
# TestUpdate
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_success(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        # Now shows per-registry refs
        assert "default:" in result.output

    def test_update_rematerialized(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["update"])
        assert "Updated: base" in result.output

    def test_update_new_evergreen(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["update"])
        assert "git-conventions" in result.output

    def test_update_recovers_corrupted_cache(self, cli_project):
        import shutil

        runner, project, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        runner.invoke(cli, ["add", "api-patterns"])

        # Delete api-patterns from cache to simulate corruption
        shutil.rmtree(
            project / ".knowledge-tree" / "registries" / "default" / "packages" / "api-patterns"
        )
        # git pull during update restores the cache
        result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        assert "Updated" in result.output


# ---------------------------------------------------------------------------
# TestStatus
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_output(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Registries" in result.output

    def test_status_counts(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["status"])
        assert "1 installed, 3 available" in result.output

    def test_status_shows_registries(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["status"])
        assert "default" in result.output


# ---------------------------------------------------------------------------
# TestInfo
# ---------------------------------------------------------------------------


class TestInfo:
    def test_info_installed(self, cli_project):
        runner, _, _ = cli_project
        runner.invoke(cli, ["add", "base"])
        result = runner.invoke(cli, ["info", "base"])
        assert result.exit_code == 0
        assert "base" in result.output
        assert "Installed" in result.output
        assert "safe-deletion.md" in result.output

    def test_info_not_installed(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["info", "base"])
        assert result.exit_code == 0
        assert "Not installed" in result.output

    def test_info_nonexistent(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["info", "zzzzzzz"])
        assert result.exit_code == 1

    def test_info_relationships(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["info", "base"])
        assert "git-conventions" in result.output

    def test_info_shows_registry(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["info", "base"])
        assert "default" in result.output


# ---------------------------------------------------------------------------
# TestValidate
# ---------------------------------------------------------------------------


class TestAuthorValidate:
    def test_validate_valid(self, cli_project):
        runner, project, _ = cli_project
        pkg_path = project / ".knowledge-tree" / "registries" / "default" / "packages" / "base"
        result = runner.invoke(cli, ["author", "validate", str(pkg_path)])
        assert result.exit_code == 0
        assert "is valid" in result.output

    def test_validate_invalid(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        bad_dir = tmp_path / "bad-pkg"
        bad_dir.mkdir()
        result = runner.invoke(cli, ["author", "validate", str(bad_dir)])
        assert result.exit_code == 1
        assert "Missing package.yaml" in result.output

    def test_validate_all(self, cli_project):
        runner, project, _ = cli_project
        pkgs_path = project / ".knowledge-tree" / "registries" / "default" / "packages"
        result = runner.invoke(cli, ["author", "validate", str(pkgs_path), "--all"])
        assert result.exit_code == 0
        assert "base" in result.output
        assert "git-conventions" in result.output
        assert "api-patterns" in result.output

    def test_validate_all_with_errors(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        # Create a dir with one good and one bad package
        pkgs = tmp_path / "mixed-pkgs"
        pkgs.mkdir()
        bad = pkgs / "bad-pkg"
        bad.mkdir()
        # No package.yaml in bad-pkg
        good = pkgs / "good-pkg"
        good.mkdir()
        from knowledge_tree.models import PackageMetadata

        PackageMetadata(
            name="good-pkg",
            description="Good",
            authors=["Test"],
            classification="evergreen",
        ).to_yaml_file(good / "package.yaml")
        (good / "content.md").write_text("# Content\n")

        result = runner.invoke(cli, ["author", "validate", str(pkgs), "--all"])
        assert result.exit_code == 1

    def test_validate_nonexistent_path(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["author", "validate", "/nonexistent/path"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# TestContribute
# ---------------------------------------------------------------------------


class TestAuthorContribute:
    def test_contribute_success(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        md_file = tmp_path / "my-knowledge.md"
        md_file.write_text("# My Knowledge\nSome useful content.\n")
        result = runner.invoke(
            cli,
            ["author", "contribute", str(md_file), "--name", "my-pkg"],
        )
        assert result.exit_code == 0
        assert "Contribution prepared" in result.output

    def test_contribute_to_existing(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        md_file = tmp_path / "child.md"
        md_file.write_text("# Child\nChild content.\n")
        result = runner.invoke(
            cli,
            [
                "author",
                "contribute",
                str(md_file),
                "--name",
                "child-pkg",
                "--to",
                "base",
            ],
        )
        assert result.exit_code == 0

    def test_contribute_missing_name(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n")
        result = runner.invoke(cli, ["author", "contribute", str(md_file)])
        assert result.exit_code == 2

    def test_contribute_not_initialized(self, cli_uninit, tmp_path):
        runner, _, _ = cli_uninit
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n")
        result = runner.invoke(cli, ["author", "contribute", str(md_file), "--name", "test-pkg"])
        assert result.exit_code == 1
        assert "kt init" in result.output.lower() or "not initialized" in result.output.lower()

    def test_contribute_file_not_found(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(
            cli, ["author", "contribute", "/nonexistent/file.md", "--name", "test-pkg"]
        )
        assert result.exit_code == 2

    def test_contribute_output_contains_url(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n")
        result = runner.invoke(cli, ["author", "contribute", str(md_file), "--name", "url-pkg"])
        assert result.exit_code == 0
        assert "contribute/url-pkg" in result.output

    def test_contribute_output_shows_package_name(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test\n")
        result = runner.invoke(cli, ["author", "contribute", str(md_file), "--name", "named-pkg"])
        assert result.exit_code == 0
        assert "Contribution prepared" in result.output


# ---------------------------------------------------------------------------
# TestRegistryRebuild
# ---------------------------------------------------------------------------


class TestAuthorRebuild:
    def test_rebuild(self, cli_project):
        runner, project, _ = cli_project
        cache = project / ".knowledge-tree" / "registries" / "default"
        result = runner.invoke(cli, ["author", "rebuild", str(cache)])
        assert result.exit_code == 0
        assert "Rebuilt registry with 4 packages" in result.output

    def test_rebuild_nonexistent_path(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["author", "rebuild", "/nonexistent/path"])
        assert result.exit_code == 2

    def test_rebuild_empty_registry(self, cli_project, tmp_path):
        runner, _, _ = cli_project
        empty_reg = tmp_path / "empty-reg"
        empty_reg.mkdir()
        (empty_reg / "packages").mkdir()
        result = runner.invoke(cli, ["author", "rebuild", str(empty_reg)])
        assert result.exit_code == 0
        assert "0 packages" in result.output

    def test_rebuild_not_initialized(self, cli_uninit, tmp_path):
        runner, _, _ = cli_uninit
        reg_dir = tmp_path / "test-reg"
        reg_dir.mkdir()
        (reg_dir / "packages").mkdir()
        result = runner.invoke(cli, ["author", "rebuild", str(reg_dir)])
        assert result.exit_code == 0
        assert "0 packages" in result.output


# ---------------------------------------------------------------------------
# TestRegistrySubcommands
# ---------------------------------------------------------------------------


class TestRegistrySubcommands:
    def test_registry_add(self, cli_project, second_registry_repo, _patch_consoles):
        runner, _project, _ = cli_project
        bare2, _ = second_registry_repo
        result = runner.invoke(
            cli,
            ["registry", "add", str(bare2), "--name", "internal", "--no-install"],
        )
        assert result.exit_code == 0
        assert "Added registry 'internal'" in result.output

    def test_registry_remove(self, cli_project, second_registry_repo, _patch_consoles):
        runner, _, _ = cli_project
        bare2, _ = second_registry_repo
        runner.invoke(
            cli,
            ["registry", "add", str(bare2), "--name", "internal", "--no-install"],
        )
        result = runner.invoke(cli, ["registry", "remove", "internal"])
        assert result.exit_code == 0
        assert "Removed registry 'internal'" in result.output


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_not_initialized(self, cli_uninit):
        runner, _, _ = cli_uninit
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1

    def test_already_initialized(self, cli_project):
        runner, _, bare = cli_project
        result = runner.invoke(cli, ["init", str(bare), "--no-install"])
        assert result.exit_code == 1

    def test_value_error(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "zzzzzzz"])
        assert result.exit_code == 1

    def test_runtime_error(self, cli_uninit):
        runner, _, _ = cli_uninit
        result = runner.invoke(
            cli, ["init", "https://nonexistent.invalid/repo.git", "--no-install"]
        )
        assert result.exit_code == 1

    def test_os_error_handling(self, cli_project, monkeypatch):
        runner, _, _ = cli_project

        def raise_os_error():
            raise OSError("Permission denied")

        monkeypatch.setattr(cli_module, "_get_engine", raise_os_error)
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "I/O error" in result.output

    def test_keyboard_interrupt(self, cli_project, monkeypatch):
        runner, _, _ = cli_project

        def raise_interrupt():
            raise KeyboardInterrupt

        monkeypatch.setattr(cli_module, "_get_engine", raise_interrupt)
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 130
        assert "Interrupted" in result.output

    def test_corrupted_yaml_clean_error(self, cli_project):
        runner, project, _ = cli_project
        kt_yaml = project / ".knowledge-tree" / "kt.yaml"
        kt_yaml.write_text('": invalid: [broken')
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "Corrupted YAML" in result.output

    def test_not_initialized_suggests_init(self, cli_uninit):
        runner, _, _ = cli_uninit
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 1
        assert "kt init" in result.output

    def test_not_installed_suggests_status(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["remove", "nonexistent"])
        assert result.exit_code == 1
        assert "kt status" in result.output

    def test_not_in_registry_suggests_search(self, cli_project):
        runner, _, _ = cli_project
        result = runner.invoke(cli, ["add", "zzzzzzz"])
        assert result.exit_code == 1
        assert "kt search" in result.output


# ---------------------------------------------------------------------------
# Local directory / archive CLI tests
# ---------------------------------------------------------------------------


class TestCliLocalDir:
    def test_init_from_local_dir(
        self, registry_dir, tmp_path, monkeypatch, cli_runner, _patch_consoles
    ):
        project = tmp_path / "proj-local"
        project.mkdir()
        monkeypatch.chdir(project)

        result = cli_runner.invoke(cli, ["init", str(registry_dir), "--no-install"])
        assert result.exit_code == 0, f"init failed: {result.output}"
        assert "Initialized" in result.output

    def test_add_after_local_init(
        self, registry_dir, tmp_path, monkeypatch, cli_runner, _patch_consoles
    ):
        project = tmp_path / "proj-local"
        project.mkdir()
        monkeypatch.chdir(project)

        cli_runner.invoke(cli, ["init", str(registry_dir), "--no-install"])
        result = cli_runner.invoke(cli, ["add", "base"])
        assert result.exit_code == 0
        assert "base" in result.output

    def test_update_local_output(
        self, registry_dir, tmp_path, monkeypatch, cli_runner, _patch_consoles
    ):
        project = tmp_path / "proj-local"
        project.mkdir()
        monkeypatch.chdir(project)

        cli_runner.invoke(cli, ["init", str(registry_dir), "--no-install"])
        result = cli_runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        assert "Updated from local directory" in result.output


class TestCliArchive:
    def test_init_from_archive(
        self,
        registry_archive_tar_gz,
        tmp_path,
        monkeypatch,
        cli_runner,
        _patch_consoles,
    ):
        project = tmp_path / "proj-archive"
        project.mkdir()
        monkeypatch.chdir(project)

        result = cli_runner.invoke(cli, ["init", str(registry_archive_tar_gz), "--no-install"])
        assert result.exit_code == 0, f"init failed: {result.output}"
        assert "Initialized" in result.output

    def test_contribute_non_git_error(
        self, registry_dir, tmp_path, monkeypatch, cli_runner, _patch_consoles
    ):
        project = tmp_path / "proj-local"
        project.mkdir()
        monkeypatch.chdir(project)

        cli_runner.invoke(cli, ["init", str(registry_dir), "--no-install"])

        contrib = tmp_path / "my.md"
        contrib.write_text("# Test\n")

        result = cli_runner.invoke(cli, ["author", "contribute", str(contrib), "--name", "my-pkg"])
        assert result.exit_code == 1
        assert (
            "only supported for git" in result.output
            or "requires git" in result.output
            or "No git" in result.output
        )
