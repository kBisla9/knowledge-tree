"""Tests for Knowledge Tree engine."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from knowledge_tree.engine import KnowledgeTreeEngine
from knowledge_tree.models import ProjectConfig


def _run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout.strip()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Return a clean project directory."""
    project = tmp_path / "my-project"
    project.mkdir()
    return project


@pytest.fixture
def initialized_project(
    registry_repo: tuple[Path, Path],
    tmp_path: Path,
) -> tuple[KnowledgeTreeEngine, Path]:
    """Return an initialized engine + project dir.

    Uses the registry_repo fixture from conftest.py.
    """
    bare, _ = registry_repo
    project = tmp_path / "my-project"
    project.mkdir()
    engine = KnowledgeTreeEngine(project)
    engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
    return engine, project


# ---------------------------------------------------------------------------
# add_registry (auto-init)
# ---------------------------------------------------------------------------


class TestAddRegistryAutoInit:
    def test_creates_directories(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        assert (project_dir / ".knowledge-tree").is_dir()
        assert (project_dir / ".knowledge-tree" / "kt.yaml").exists()
        # .knowledge-tree/ gets a .gitignore containing '*'
        gitignore = project_dir / ".knowledge-tree" / ".gitignore"
        assert gitignore.exists()
        assert gitignore.read_text().strip() == "*"

    def test_caches_registry(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        cache = project_dir / ".knowledge-tree" / "cache" / "default"
        assert cache.is_dir()
        assert (cache / "registry.yaml").exists()

    def test_returns_available_packages(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)
        result = engine.add_registry(
            str(bare), name="default", branch="main", install_packages=False
        )

        assert "base" in result.available_packages
        assert "git-conventions" in result.available_packages
        assert "api-patterns" in result.available_packages

    def test_saves_config(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        config = ProjectConfig.from_yaml_file(project_dir / ".knowledge-tree" / "kt.yaml")
        assert len(config.registries) == 1
        assert config.registries[0].source == str(bare)
        assert config.registries[0].ref == "main"
        assert config.registries[0].name == "default"
        assert config.registries[0].id != ""

    def test_cleans_up_on_clone_failure(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)

        # Attempt with a bad URL — should fail and clean up
        with pytest.raises(RuntimeError):
            engine.add_registry("file:///nonexistent/repo.git", branch="main")

        # .knowledge-tree/ should NOT exist (cleaned up)
        assert not (project_dir / ".knowledge-tree").exists()

        # Retry with the correct URL — should succeed
        result = engine.add_registry(
            str(bare), name="default", branch="main", install_packages=False
        )
        assert "base" in result.available_packages

    def test_custom_name(self, registry_repo: tuple[Path, Path], project_dir: Path):
        bare, _ = registry_repo
        engine = KnowledgeTreeEngine(project_dir)
        engine.add_registry(str(bare), name="primary", branch="main", install_packages=False)

        cache = project_dir / ".knowledge-tree" / "cache" / "primary"
        assert cache.is_dir()

        config = ProjectConfig.from_yaml_file(project_dir / ".knowledge-tree" / "kt.yaml")
        assert config.registries[0].name == "primary"


# ---------------------------------------------------------------------------
# add_package
# ---------------------------------------------------------------------------


class TestAddPackage:
    def test_add_single_package(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _project = initialized_project
        result = engine.add_package("base")

        assert "base" in result.installed

    def test_add_with_dependency(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _project = initialized_project
        result = engine.add_package("api-patterns")

        # base is the parent of api-patterns
        assert "base" in result.installed
        assert "api-patterns" in result.installed

    def test_add_with_explicit_content_list(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _project = initialized_project
        result = engine.add_package("api-patterns")

        assert "api-patterns" in result.installed

    def test_add_already_installed(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")
        result = engine.add_package("base")

        assert result.installed == []
        assert "base" in result.already_installed

    def test_add_nonexistent_with_suggestion(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="Did you mean"):
            engine.add_package("bse")  # close to "base"

    def test_add_nonexistent_no_match(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="not found"):
            engine.add_package("zzzzzzz")

    def test_dependency_not_duplicated(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        engine.add_package("base")
        result = engine.add_package("api-patterns")

        assert "base" not in result.installed
        assert "base" in result.already_installed
        assert "api-patterns" in result.installed

    def test_add_returns_registry_name(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        result = engine.add_package("base")
        assert result.registry == "default"

    def test_add_package_with_subdirectories(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _project = initialized_project
        result = engine.add_package("session-mgmt")

        assert "session-mgmt" in result.installed

    def test_dry_run_does_not_materialize(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, project = initialized_project
        result = engine.add_package("api-patterns", dry_run=True)

        # Should report what would be installed
        assert "base" in result.installed
        assert "api-patterns" in result.installed
        assert result.registry == "default"

        # Config should not be updated
        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.get_installed_names() == set()

    def test_dry_run_with_partial_install(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _project = initialized_project
        engine.add_package("base")

        result = engine.add_package("api-patterns", dry_run=True)

        assert "base" in result.already_installed
        assert "api-patterns" in result.installed


# ---------------------------------------------------------------------------
# remove_package
# ---------------------------------------------------------------------------


class TestRemovePackage:
    def test_remove_package(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _project = initialized_project
        engine.add_package("base")
        result = engine.remove_package("base")

        assert result.removed is True

    def test_remove_nonexistent(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="not installed"):
            engine.remove_package("nonexistent")

    def test_remove_warns_about_children(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        engine.add_package("api-patterns")  # installs base + api-patterns
        result = engine.remove_package("base")

        assert result.removed is True
        assert "api-patterns" in result.children


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_pulls_changes(
        self,
        registry_repo: tuple[Path, Path],
        tmp_path: Path,
    ):
        bare, work = registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        engine.add_package("base")

        # Push a change to the registry
        new_file = work / "packages" / "base" / "new-content.md"
        new_file.write_text("# New Content\nNew stuff.\n")
        _run_git(["add", "."], cwd=work)
        _run_git(["commit", "-m", "Add new content"], cwd=work)
        _run_git(["push", "origin", "main"], cwd=work)

        result = engine.update()

        assert "base" in result.updated_packages

    def test_update_returns_refs_dict(
        self,
        registry_repo: tuple[Path, Path],
        tmp_path: Path,
    ):
        bare, _ = registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        engine.add_package("base")

        result = engine.update()
        assert "default" in result.refs

    def test_update_detects_new_evergreen(
        self,
        registry_repo: tuple[Path, Path],
        tmp_path: Path,
    ):
        bare, _work = registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        engine.add_package("base")  # install only base

        # git-conventions is evergreen and not installed
        result = engine.update()
        assert "git-conventions" in result.new_evergreen

    def test_selective_update(
        self,
        registry_repo: tuple[Path, Path],
        tmp_path: Path,
    ):
        bare, _ = registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        engine.add_package("base")
        engine.add_package("git-conventions")

        result = engine.update(package_name="base")

        assert result.updated_packages == ["base"]
        assert result.new_evergreen == []  # skipped for selective update

    def test_selective_update_not_installed(
        self,
        registry_repo: tuple[Path, Path],
        tmp_path: Path,
    ):
        bare, _ = registry_repo
        project = tmp_path / "my-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        with pytest.raises(ValueError, match="not installed"):
            engine.update(package_name="base")


# ---------------------------------------------------------------------------
# list_packages
# ---------------------------------------------------------------------------


class TestListPackages:
    def test_list_installed(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")

        results = engine.list_packages(available=False)
        names = [r.name for r in results]
        assert "base" in names
        assert all(r.installed for r in results)

    def test_list_available(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")

        results = engine.list_packages(available=True)
        names = [r.name for r in results]
        assert "base" not in names
        assert "api-patterns" in names
        assert "git-conventions" in names

    def test_list_includes_registry(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")

        results = engine.list_packages(available=False)
        assert results[0].registry == "default"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_by_name(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        results = engine.search("base")
        names = [r.name for r in results]
        assert "base" in names

    def test_search_by_tag(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        results = engine.search("api")
        names = [r.name for r in results]
        assert "api-patterns" in names

    def test_search_no_results(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        results = engine.search("nonexistent-xyz")
        assert results == []

    def test_search_annotates_installed(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        engine.add_package("base")
        results = engine.search("base")
        base_result = next(r for r in results if r.name == "base")
        assert base_result.installed is True

    def test_search_includes_registry(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        results = engine.search("base")
        base_result = next(r for r in results if r.name == "base")
        assert base_result.registry == "default"


# ---------------------------------------------------------------------------
# get_tree_data
# ---------------------------------------------------------------------------


class TestGetTreeData:
    def test_tree_structure(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        data = engine.get_tree_data()

        root_names = [n.name for n in data.roots]
        # base and session-mgmt are roots; git-conventions and api-patterns are children of base
        assert "base" in root_names
        assert "session-mgmt" in root_names
        assert "api-patterns" not in root_names
        assert "git-conventions" not in root_names

        base_node = next(n for n in data.roots if n.name == "base")
        child_names = sorted(c.name for c in base_node.children)
        assert child_names == ["api-patterns", "git-conventions"]


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_counts(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")

        status = engine.get_status()
        assert status.installed_count == 1
        assert status.available_count == 3  # git-conventions + api-patterns + session-mgmt
        assert status.total_files > 0
        assert status.total_lines > 0

    def test_status_includes_registries(
        self, initialized_project: tuple[KnowledgeTreeEngine, Path]
    ):
        engine, _ = initialized_project
        status = engine.get_status()
        assert len(status.registries) == 1
        assert status.registries[0].name == "default"


# ---------------------------------------------------------------------------
# get_info
# ---------------------------------------------------------------------------


class TestGetInfo:
    def test_info_installed(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.add_package("base")
        info = engine.get_info("base")

        assert info.name == "base"
        assert info.installed is True
        assert len(info.files) > 0
        assert sorted(info.children) == ["api-patterns", "git-conventions"]
        assert info.registry == "default"

    def test_info_not_installed(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        info = engine.get_info("base")

        assert info.name == "base"
        assert info.installed is False
        assert info.files == []

    def test_info_nonexistent(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="not found"):
            engine.get_info("nonexistent")

    def test_info_with_suggestion(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="Did you mean"):
            engine.get_info("bse")


# ---------------------------------------------------------------------------
# config get / set
# ---------------------------------------------------------------------------


class TestConfig:
    def test_get_config_default(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        assert engine.get_config("export_format") == ""

    def test_set_and_get_config(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        engine.set_config("export_format", "claude-code")
        assert engine.get_config("export_format") == "claude-code"

    def test_set_config_persists(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, project = initialized_project
        engine.set_config("export_format", "roo-code")

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.export_format == "roo-code"

    def test_get_unknown_key(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="Unknown config key"):
            engine.get_config("nonexistent")

    def test_set_unknown_key(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _ = initialized_project
        with pytest.raises(ValueError, match="Unknown config key"):
            engine.set_config("nonexistent", "value")


# ---------------------------------------------------------------------------
# validate_package
# ---------------------------------------------------------------------------


class TestValidatePackage:
    def test_valid_package(self, initialized_project: tuple[KnowledgeTreeEngine, Path]):
        engine, _project = initialized_project
        pkg_path = engine._registry_cache_dir("default") / "packages" / "base"
        result = engine.validate_package(pkg_path)

        assert result.valid is True
        assert result.errors == []

    def test_invalid_package_missing_yaml(self, tmp_path: Path):
        engine = KnowledgeTreeEngine(tmp_path)
        pkg_path = tmp_path / "bad-pkg"
        pkg_path.mkdir()

        result = engine.validate_package(pkg_path)
        assert result.valid is False
        assert any("Missing package.yaml" in e for e in result.errors)

    def test_invalid_package_missing_content_file(self, tmp_path: Path):
        engine = KnowledgeTreeEngine(tmp_path)
        pkg_path = tmp_path / "bad-pkg"
        pkg_path.mkdir()

        from knowledge_tree.models import ContentItem, PackageMetadata

        meta = PackageMetadata(
            name="bad-pkg",
            description="Test",
            authors=["Test"],
            classification="evergreen",
            content=[ContentItem(file="missing-file.md")],
        )
        meta.to_yaml_file(pkg_path / "package.yaml")

        result = engine.validate_package(pkg_path)
        assert result.valid is False
        assert any("not found" in e for e in result.errors)

    def test_validate_corrupted_yaml(self, tmp_path: Path):
        engine = KnowledgeTreeEngine(tmp_path)
        pkg_path = tmp_path / "corrupt-pkg"
        pkg_path.mkdir()
        (pkg_path / "package.yaml").write_text('": invalid: [broken')

        result = engine.validate_package(pkg_path)
        assert result.valid is False
        assert any("Invalid package.yaml" in e for e in result.errors)


# ---------------------------------------------------------------------------
# contribute
# ---------------------------------------------------------------------------


class TestContribute:
    @pytest.fixture
    def contribute_env(self, registry_repo, tmp_path):
        """Initialized project that returns engine, project, and bare repo."""
        bare, _ = registry_repo
        project = tmp_path / "contrib-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        return engine, project, bare

    @staticmethod
    def _make_md(tmp_path, name="my-knowledge.md", content="# My Knowledge\nUseful content.\n"):
        f = tmp_path / name
        f.write_text(content)
        return f

    def test_creates_community_package(self, contribute_env, tmp_path):
        engine, project, _ = contribute_env
        md = self._make_md(tmp_path)
        engine.contribute(md, "test-pkg")

        dest = project / ".knowledge-tree" / "cache" / "default" / "community" / "test-pkg"
        assert dest.is_dir()
        assert (dest / "my-knowledge.md").exists()
        assert (dest / "package.yaml").exists()

    def test_package_yaml_content(self, contribute_env, tmp_path):
        engine, project, _ = contribute_env
        md = self._make_md(tmp_path)
        engine.contribute(md, "test-pkg")

        from knowledge_tree.models import PackageMetadata

        meta = PackageMetadata.from_yaml_file(
            project
            / ".knowledge-tree"
            / "cache"
            / "default"
            / "community"
            / "test-pkg"
            / "package.yaml"
        )
        assert meta.name == "test-pkg"
        assert meta.classification == "seasonal"
        assert meta.status == "pending"
        assert [item.file for item in meta.content] == ["my-knowledge.md"]

    def test_to_existing_nests_correctly(self, contribute_env, tmp_path):
        engine, project, _ = contribute_env
        md = self._make_md(tmp_path)
        engine.contribute(md, "child-pkg", to_existing="base")

        dest = (
            project / ".knowledge-tree" / "cache" / "default" / "community" / "base" / "child-pkg"
        )
        assert dest.is_dir()
        assert (dest / "my-knowledge.md").exists()

    def test_creates_branch(self, contribute_env, tmp_path):
        engine, _, bare = contribute_env
        md = self._make_md(tmp_path)
        engine.contribute(md, "test-pkg")

        # Verify the branch exists in the bare repo
        branches = _run_git(["branch"], cwd=bare)
        assert "contribute/test-pkg" in branches

    def test_pushes_to_origin(self, contribute_env, tmp_path):
        engine, _, bare = contribute_env
        md = self._make_md(tmp_path)
        engine.contribute(md, "test-pkg")

        # Clone from bare on the new branch, verify file exists
        verify = tmp_path / "verify-clone"
        _run_git(
            ["clone", "--branch", "contribute/test-pkg", str(bare), str(verify)],
            cwd=tmp_path,
        )
        assert (verify / "community" / "test-pkg" / "my-knowledge.md").exists()

    def test_returns_mr_url(self, contribute_env, tmp_path):
        engine, _, _ = contribute_env
        md = self._make_md(tmp_path)
        url = engine.contribute(md, "test-pkg")

        assert isinstance(url, str)
        assert "contribute/test-pkg" in url

    def test_not_initialized(self, tmp_path):
        project = tmp_path / "empty-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        md = tmp_path / "test.md"
        md.write_text("# Test\n")

        with pytest.raises(FileNotFoundError):
            engine.contribute(md, "test-pkg")

    def test_file_not_found(self, contribute_env, tmp_path):
        engine, _, _ = contribute_env
        nonexistent = tmp_path / "does-not-exist.md"

        with pytest.raises(FileNotFoundError):
            engine.contribute(nonexistent, "test-pkg")

    def test_branch_already_exists(self, contribute_env, tmp_path):
        engine, _, _ = contribute_env
        md1 = self._make_md(tmp_path, "first.md", "# First\n")
        engine.contribute(md1, "test-pkg")

        md2 = self._make_md(tmp_path, "second.md", "# Second\n")
        with pytest.raises(RuntimeError, match="already exists"):
            engine.contribute(md2, "test-pkg")

    def test_preserves_file_content(self, contribute_env, tmp_path):
        engine, project, _ = contribute_env
        content = "# Detailed Knowledge\n\nWith multiple paragraphs.\n\n- Bullet 1\n- Bullet 2\n"
        md = self._make_md(tmp_path, content=content)
        engine.contribute(md, "test-pkg")

        copied = (
            project
            / ".knowledge-tree"
            / "cache"
            / "default"
            / "community"
            / "test-pkg"
            / "my-knowledge.md"
        )
        assert copied.read_text() == content

    def test_unshallow_already_full(self, registry_repo, tmp_path):
        bare, _ = registry_repo
        project = tmp_path / "full-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        # Init does a shallow clone by default; unshallow it manually first
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        from knowledge_tree import git_ops

        git_ops.unshallow(engine._registry_cache_dir("default"))

        md = tmp_path / "test.md"
        md.write_text("# Test\n")
        url = engine.contribute(md, "test-pkg")
        assert "contribute/test-pkg" in url


class TestRegistryRebuild:
    def test_rebuild(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        engine = KnowledgeTreeEngine(work)
        count = engine.registry_rebuild(work)

        assert count == 4  # base, git-conventions, api-patterns, session-mgmt
        assert (work / "registry.yaml").exists()

    def test_rebuild_preserves_parent(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        engine = KnowledgeTreeEngine(work)
        engine.registry_rebuild(work)

        from knowledge_tree.models import Registry

        registry = Registry.from_yaml_file(work / "registry.yaml")
        assert registry.packages["git-conventions"].parent == "base"

    def test_rebuild_preserves_tags(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        engine = KnowledgeTreeEngine(work)
        engine.registry_rebuild(work)

        from knowledge_tree.models import Registry

        registry = Registry.from_yaml_file(work / "registry.yaml")
        assert "core" in registry.packages["base"].tags

    def test_rebuild_empty_packages_dir(self, tmp_path):
        registry_dir = tmp_path / "empty-registry"
        registry_dir.mkdir()
        (registry_dir / "packages").mkdir()

        engine = KnowledgeTreeEngine(tmp_path)
        count = engine.registry_rebuild(registry_dir)

        assert count == 0
        assert (registry_dir / "registry.yaml").exists()

    def test_rebuild_skips_non_directories(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        # Add a stray file in packages/
        (work / "packages" / "stray-file.txt").write_text("stray")

        engine = KnowledgeTreeEngine(work)
        count = engine.registry_rebuild(work)
        assert count == 4  # still only the 4 real packages

    def test_rebuild_skips_dirs_without_package_yaml(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        # Add dir with no package.yaml
        (work / "packages" / "empty-pkg").mkdir()

        engine = KnowledgeTreeEngine(work)
        count = engine.registry_rebuild(work)
        assert count == 4

    def test_rebuild_dirname_differs_from_name(self, tmp_path):
        registry_dir = tmp_path / "mismatch-registry"
        registry_dir.mkdir()
        pkg_dir = registry_dir / "packages" / "dir-name"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: yaml-name\n"
            "description: Mismatched name\n"
            "authors:\n  - Test\n"
            "classification: evergreen\n"
        )

        engine = KnowledgeTreeEngine(tmp_path)
        count = engine.registry_rebuild(registry_dir)
        assert count == 1

        from knowledge_tree.models import Registry

        registry = Registry.from_yaml_file(registry_dir / "registry.yaml")
        # Keyed by YAML name, path uses dirname
        assert "yaml-name" in registry.packages
        assert registry.packages["yaml-name"].path == "packages/dir-name"

    def test_rebuild_preserves_existing_id(self, registry_repo: tuple[Path, Path]):
        _, work = registry_repo
        engine = KnowledgeTreeEngine(work)
        engine.registry_rebuild(work)

        from knowledge_tree.models import Registry

        registry = Registry.from_yaml_file(work / "registry.yaml")
        assert registry.id == "7348a577b60f490ba872367ed8e41371"

    def test_rebuild_generates_id_when_missing(self, tmp_path):
        registry_dir = tmp_path / "no-id-registry"
        registry_dir.mkdir()
        pkg_dir = registry_dir / "packages" / "simple"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: simple\n"
            "description: A simple package\n"
            "authors:\n  - Test\n"
            "classification: evergreen\n"
        )
        # registry.yaml with no id
        (registry_dir / "registry.yaml").write_text("packages: {}\n")

        engine = KnowledgeTreeEngine(tmp_path)
        engine.registry_rebuild(registry_dir)

        from knowledge_tree.models import Registry, _is_valid_uuid_hex

        registry = Registry.from_yaml_file(registry_dir / "registry.yaml")
        assert _is_valid_uuid_hex(registry.id)

    def test_rebuild_preserves_templates(self, tmp_path):
        registry_dir = tmp_path / "tpl-registry"
        registry_dir.mkdir()
        pkg_dir = registry_dir / "packages" / "simple"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: simple\n"
            "description: A simple package\n"
            "authors:\n  - Test\n"
            "classification: evergreen\n"
        )
        (registry_dir / "registry.yaml").write_text(
            "id: aabbccdd11223344aabbccdd11223344\n"
            "templates:\n"
            "  - source: templates/config.md\n"
            "    dest: my-dir/config.md\n"
            "packages:\n"
            "  old-pkg:\n"
            "    description: Will be replaced\n"
            "    classification: evergreen\n"
            "    path: packages/old-pkg\n"
        )

        engine = KnowledgeTreeEngine(tmp_path)
        engine.registry_rebuild(registry_dir)

        from knowledge_tree.models import Registry

        registry = Registry.from_yaml_file(registry_dir / "registry.yaml")
        assert registry.id == "aabbccdd11223344aabbccdd11223344"
        assert len(registry.templates) == 1
        assert registry.templates[0].source == "templates/config.md"
        assert registry.templates[0].dest == "my-dir/config.md"
        # Packages were rebuilt (old-pkg gone, simple added)
        assert "simple" in registry.packages
        assert "old-pkg" not in registry.packages

    def test_rebuild_generates_id_when_no_registry_yaml(self, tmp_path):
        registry_dir = tmp_path / "fresh-registry"
        registry_dir.mkdir()
        pkg_dir = registry_dir / "packages" / "simple"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: simple\n"
            "description: A simple package\n"
            "authors:\n  - Test\n"
            "classification: evergreen\n"
        )

        engine = KnowledgeTreeEngine(tmp_path)
        engine.registry_rebuild(registry_dir)

        from knowledge_tree.models import Registry, _is_valid_uuid_hex

        registry = Registry.from_yaml_file(registry_dir / "registry.yaml")
        assert _is_valid_uuid_hex(registry.id)


# ---------------------------------------------------------------------------
# Local directory backend
# ---------------------------------------------------------------------------


class TestLocalDirectory:
    def test_add_from_local_dir(self, registry_dir: Path, tmp_path: Path):
        project = tmp_path / "proj-local"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(str(registry_dir), name="default", install_packages=False)

        assert "base" in result.available_packages
        assert "git-conventions" in result.available_packages
        assert "api-patterns" in result.available_packages
        assert (project / ".knowledge-tree" / "cache" / "default" / "registry.yaml").exists()

    def test_config_has_local_type(self, registry_dir: Path, tmp_path: Path):
        project = tmp_path / "proj-local"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_dir), name="default", install_packages=False)

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.registries[0].type == "local"
        assert config.registries[0].ref == ""

    def test_add_package_local_ref(self, registry_dir: Path, tmp_path: Path):
        project = tmp_path / "proj-local"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_dir), name="default", install_packages=False)
        result = engine.add_package("base")

        assert "base" in result.installed

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.get_package_ref("base") == "local"

    def test_update_recopies(self, registry_dir: Path, tmp_path: Path):
        project = tmp_path / "proj-local"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_dir), name="default", install_packages=False)
        engine.add_package("base")

        # Add a new file to source
        new_pkg = registry_dir / "packages" / "new-pkg"
        new_pkg.mkdir()
        (new_pkg / "package.yaml").write_text(
            "name: new-pkg\n"
            "description: Dynamically added\n"
            "authors:\n  - Test\n"
            "classification: seasonal\n"
        )
        (new_pkg / "content.md").write_text("# New\n")

        # Update registry.yaml in source to include new package
        reg_path = registry_dir / "registry.yaml"
        reg_text = reg_path.read_text()
        reg_text += (
            "  new-pkg:\n"
            "    description: Dynamically added\n"
            "    classification: seasonal\n"
            "    path: packages/new-pkg\n"
        )
        reg_path.write_text(reg_text)

        result = engine.update()
        assert "default" in result.refs
        assert result.refs["default"] == "local"

        # The new package should now be discoverable
        info = engine.get_info("new-pkg")
        assert info.name == "new-pkg"


class TestArchive:
    def test_add_from_tar_gz(self, registry_archive_tar_gz: Path, tmp_path: Path):
        project = tmp_path / "proj-archive"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(
            str(registry_archive_tar_gz), name="default", install_packages=False
        )

        assert "base" in result.available_packages
        assert (project / ".knowledge-tree" / "cache" / "default" / "registry.yaml").exists()

    def test_add_from_zip(self, registry_archive_zip: Path, tmp_path: Path):
        project = tmp_path / "proj-zip"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(
            str(registry_archive_zip), name="default", install_packages=False
        )
        packages = result.available_packages

        assert "base" in packages

    def test_add_from_nested_archive(self, registry_archive_nested: Path, tmp_path: Path):
        project = tmp_path / "proj-nested"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        result = engine.add_registry(
            str(registry_archive_nested), name="default", install_packages=False
        )
        packages = result.available_packages

        assert "base" in packages
        assert (project / ".knowledge-tree" / "cache" / "default" / "packages" / "base").is_dir()

    def test_config_has_archive_type(self, registry_archive_tar_gz: Path, tmp_path: Path):
        project = tmp_path / "proj-archive"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_archive_tar_gz), name="default", install_packages=False)

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.registries[0].type == "archive"
        assert config.registries[0].ref == ""

    def test_add_package_archive_ref(self, registry_archive_tar_gz: Path, tmp_path: Path):
        project = tmp_path / "proj-archive"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_archive_tar_gz), name="default", install_packages=False)
        engine.add_package("base")

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        ref = config.get_package_ref("base")
        # archive ref should be 7-char hex from SHA-256
        assert ref is not None
        assert len(ref) == 7


class TestContributeNonGit:
    def test_contribute_local_raises(self, registry_dir: Path, tmp_path: Path):
        project = tmp_path / "proj-local"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_dir), name="default", install_packages=False)

        contrib_file = tmp_path / "my-knowledge.md"
        contrib_file.write_text("# My Knowledge\n")

        with pytest.raises(RuntimeError, match=r"(only supported for git|requires git|No git)"):
            engine.contribute(contrib_file, "my-pkg")

    def test_contribute_archive_raises(self, registry_archive_tar_gz: Path, tmp_path: Path):
        project = tmp_path / "proj-archive"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(registry_archive_tar_gz), name="default", install_packages=False)

        contrib_file = tmp_path / "my-knowledge.md"
        contrib_file.write_text("# My Knowledge\n")

        with pytest.raises(RuntimeError, match=r"(only supported for git|requires git|No git)"):
            engine.contribute(contrib_file, "my-pkg")


# ---------------------------------------------------------------------------
# Multi-registry
# ---------------------------------------------------------------------------


class TestMultiRegistry:
    @pytest.fixture
    def multi_project(self, registry_repo, second_registry_repo, tmp_path):
        """Project initialized with first registry, second registry added."""
        bare1, _ = registry_repo
        bare2, _ = second_registry_repo

        project = tmp_path / "multi-project"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare1), name="public", branch="main", install_packages=False)
        engine.add_registry(str(bare2), name="internal", branch="main", install_packages=False)
        return engine, project

    def test_add_from_second_registry(self, multi_project):
        engine, _project = multi_project
        result = engine.add_package("internal-rules")

        assert "internal-rules" in result.installed
        assert result.registry == "internal"

    def test_add_from_first_registry(self, multi_project):
        engine, _project = multi_project
        result = engine.add_package("base")

        assert "base" in result.installed
        assert result.registry == "public"

    def test_search_spans_registries(self, multi_project):
        engine, _ = multi_project
        results = engine.search("rules")
        names = [r.name for r in results]
        assert "internal-rules" in names

    def test_list_spans_registries(self, multi_project):
        engine, _ = multi_project
        engine.add_package("base")
        engine.add_package("internal-rules")

        results = engine.list_packages(available=False)
        names = [r.name for r in results]
        assert "base" in names
        assert "internal-rules" in names

    def test_status_lists_all_registries(self, multi_project):
        engine, _ = multi_project
        status = engine.get_status()
        reg_names = [r.name for r in status.registries]
        assert "public" in reg_names
        assert "internal" in reg_names

    def test_remove_registry(self, multi_project):
        engine, project = multi_project
        engine.remove_registry("internal")

        from knowledge_tree.models import ProjectConfig

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.get_registry("internal") is None
        assert not (project / ".knowledge-tree" / "cache" / "internal").exists()

    def test_remove_registry_with_packages_requires_force(self, multi_project):
        engine, _ = multi_project
        engine.add_package("internal-rules")

        with pytest.raises(ValueError, match="has installed packages"):
            engine.remove_registry("internal")

    def test_remove_registry_force(self, multi_project):
        engine, _project = multi_project
        engine.add_package("internal-rules")
        engine.remove_registry("internal", force=True)

    def test_remove_registry_force_cleans_packages_and_exports(self, multi_project):
        """Regression: force-remove must not leave orphaned package/export entries."""
        engine, project = multi_project
        from knowledge_tree.models import ProjectConfig

        # Install a package and export it
        engine.add_package("internal-rules")
        engine.export_package("internal-rules", "claude-code")

        # Sanity: package and export exist
        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert "internal-rules" in config.get_installed_names()
        assert any(e.name == "internal-rules" for e in config.get_exports())

        # Force-remove the registry
        engine.remove_registry("internal", force=True)

        # Reload and verify everything is gone
        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert "internal-rules" not in config.get_installed_names()
        assert not any(e.name == "internal-rules" for e in config.get_exports())
        assert config.get_registry("internal") is None

    def test_add_duplicate_registry_name_fails(self, multi_project):
        engine, _ = multi_project
        with pytest.raises(ValueError, match="already exists"):
            engine.add_registry("/tmp/fake", name="internal")


# ---------------------------------------------------------------------------
# Canonical registry ID
# ---------------------------------------------------------------------------


class TestCanonicalRegistryId:
    def test_add_registry_uses_canonical_id_on_fresh_project(self, registry_repo, tmp_path):
        """init() should read the id from registry.yaml."""
        bare, _ = registry_repo
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.registries[0].id == "7348a577b60f490ba872367ed8e41371"

    def test_add_registry_uses_canonical_id(self, registry_repo, tmp_path):
        """add_registry() should read the id from registry.yaml."""
        bare, _ = registry_repo
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="test-reg", branch="main", install_packages=False)

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        reg = config.get_registry("test-reg")
        assert reg is not None
        assert reg.id == "7348a577b60f490ba872367ed8e41371"

    def test_preview_uses_canonical_id(self, registry_repo, tmp_path):
        """preview_registry() should read the id from registry.yaml."""
        bare, _ = registry_repo
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.preview_registry(str(bare), name="test-reg", branch="main")

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        reg = config.get_registry("test-reg")
        assert reg is not None
        assert reg.id == "7348a577b60f490ba872367ed8e41371"

    def test_missing_id_raises(self, tmp_path):
        """Registry without id field should be rejected."""
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        # Create a registry dir with no id in registry.yaml
        reg_dir = tmp_path / "no-id-registry"
        reg_dir.mkdir()
        pkg_dir = reg_dir / "packages" / "example"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: example\ndescription: Test\nauthors:\n  - Test\n"
        )
        (pkg_dir / "content.md").write_text("# Content\n")
        (reg_dir / "registry.yaml").write_text(
            "packages:\n  example:\n    description: Test\n    path: packages/example\n"
        )

        with pytest.raises(ValueError, match="'id' is required"):
            engine.add_registry(str(reg_dir), install_packages=False)

    def test_invalid_id_raises(self, tmp_path):
        """Registry with non-UUID id should be rejected."""
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)

        reg_dir = tmp_path / "bad-id-registry"
        reg_dir.mkdir()
        pkg_dir = reg_dir / "packages" / "example"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            "name: example\ndescription: Test\nauthors:\n  - Test\n"
        )
        (pkg_dir / "content.md").write_text("# Content\n")
        (reg_dir / "registry.yaml").write_text(
            "id: not-a-valid-uuid\n"
            "packages:\n"
            "  example:\n"
            "    description: Test\n"
            "    path: packages/example\n"
        )

        with pytest.raises(ValueError, match="32-character lowercase hex"):
            engine.add_registry(str(reg_dir), install_packages=False)

    def test_id_collision_raises(self, registry_repo, second_registry_repo, tmp_path):
        """Two registries with the same id should error on second add."""
        bare, _ = registry_repo
        bare2, work2 = second_registry_repo

        # Overwrite second registry to use the same id as the first
        import subprocess

        (work2 / "registry.yaml").write_text(
            "id: 7348a577b60f490ba872367ed8e41371\n"
            "packages:\n"
            "  internal-rules:\n"
            "    description: Company internal coding rules\n"
            "    classification: evergreen\n"
            "    path: packages/internal-rules\n"
        )
        subprocess.run(["git", "add", "."], cwd=work2, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Use colliding id"],
            cwd=work2,
            capture_output=True,
        )
        subprocess.run(["git", "push", "origin", "main"], cwd=work2, capture_output=True)

        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)

        with pytest.raises(ValueError, match="collides with existing"):
            engine.add_registry(str(bare2), branch="main", name="internal")

    def test_packages_use_canonical_id(self, registry_repo, tmp_path):
        """Installed packages should reference the canonical registry id."""
        bare, _ = registry_repo
        project = tmp_path / "proj"
        project.mkdir()
        engine = KnowledgeTreeEngine(project)
        engine.add_registry(str(bare), name="default", branch="main", install_packages=False)
        engine.add_package("base")

        config = ProjectConfig.from_yaml_file(project / ".knowledge-tree" / "kt.yaml")
        assert config.packages[0].registry == "7348a577b60f490ba872367ed8e41371"


# ---------------------------------------------------------------------------
# Cache migration
# ---------------------------------------------------------------------------


class TestCacheMigration:
    """Migration tests removed — no users on old format yet."""

    pass
