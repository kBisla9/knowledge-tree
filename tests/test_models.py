"""Tests for Knowledge Tree data models."""

import os

import pytest

from knowledge_tree._yaml_helpers import load_yaml, save_yaml
from knowledge_tree.models import (
    PACKAGE_NAME_RE,
    ContentItem,
    ExportedPackage,
    InstalledPackage,
    PackageMetadata,
    ProjectConfig,
    Registry,
    RegistryEntry,
    RegistrySource,
    _levenshtein,
)

# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical_strings(self):
        assert _levenshtein("abc", "abc") == 0

    def test_empty_strings(self):
        assert _levenshtein("", "") == 0

    def test_one_empty(self):
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("", "abc") == 3

    def test_single_edit(self):
        assert _levenshtein("cat", "bat") == 1  # substitution
        assert _levenshtein("cat", "cats") == 1  # insertion
        assert _levenshtein("cats", "cat") == 1  # deletion

    def test_multiple_edits(self):
        assert _levenshtein("kitten", "sitting") == 3


# ---------------------------------------------------------------------------
# PACKAGE_NAME_RE
# ---------------------------------------------------------------------------


class TestPackageNameRegex:
    @pytest.mark.parametrize(
        "name",
        ["base", "git-conventions", "cloud-aws-lambda", "a1", "abc-123"],
    )
    def test_valid_names(self, name):
        assert PACKAGE_NAME_RE.match(name)

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "Base",  # uppercase
            "1abc",  # starts with digit
            "-abc",  # starts with hyphen
            "abc-",  # ends with hyphen
            "abc--def",  # double hyphen
            "abc_def",  # underscore
            "abc def",  # space
            "abc.def",  # dot
        ],
    )
    def test_invalid_names(self, name):
        assert not PACKAGE_NAME_RE.match(name)


# ---------------------------------------------------------------------------
# PackageMetadata
# ---------------------------------------------------------------------------


class TestPackageMetadata:
    def _valid_meta(self, **overrides) -> PackageMetadata:
        defaults = dict(
            name="test-pkg",
            description="A test package",
            authors=["Alice"],
            classification="evergreen",
        )
        defaults.update(overrides)
        return PackageMetadata(**defaults)

    def test_valid_package_no_errors(self):
        meta = self._valid_meta()
        assert meta.validate() == []

    def test_missing_name(self):
        meta = self._valid_meta(name="")
        errors = meta.validate()
        assert any("'name' is required" in e for e in errors)

    def test_invalid_name(self):
        meta = self._valid_meta(name="Invalid-Name")
        errors = meta.validate()
        assert any("Invalid package name" in e for e in errors)

    def test_missing_description(self):
        meta = self._valid_meta(description="")
        errors = meta.validate()
        assert any("'description' is required" in e for e in errors)

    def test_missing_authors(self):
        meta = self._valid_meta(authors=[])
        errors = meta.validate()
        assert any("author" in e.lower() for e in errors)

    def test_empty_classification_is_valid(self):
        """Empty classification is allowed (defaults to seasonal at load time)."""
        meta = self._valid_meta(classification="")
        errors = meta.validate()
        assert not any("classification" in e.lower() for e in errors)

    def test_invalid_classification(self):
        meta = self._valid_meta(classification="bogus")
        errors = meta.validate()
        assert any("Invalid classification" in e for e in errors)

    def test_seasonal_classification_valid(self):
        meta = self._valid_meta(classification="seasonal")
        assert meta.validate() == []

    def test_valid_status(self):
        for status in ["pending", "promoted", "archived"]:
            meta = self._valid_meta(status=status)
            assert meta.validate() == []

    def test_invalid_status(self):
        meta = self._valid_meta(status="bogus")
        errors = meta.validate()
        assert any("Invalid status" in e for e in errors)

    def test_none_status_is_valid(self):
        meta = self._valid_meta(status=None)
        assert meta.validate() == []

    def test_yaml_round_trip(self, tmp_path):
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(
            tags=["testing", "core"],
            depends_on=["base"],
            parent="root",
            created="2026-01-01",
            updated="2026-02-01",
            status="pending",
            promoted_to="main-pkg",
            promoted_date="2026-03-01",
        )
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)

        assert loaded.name == meta.name
        assert loaded.description == meta.description
        assert loaded.authors == meta.authors
        assert loaded.classification == meta.classification
        assert loaded.tags == meta.tags
        assert loaded.depends_on == meta.depends_on
        assert loaded.parent == meta.parent
        assert loaded.created == meta.created
        assert loaded.updated == meta.updated
        assert loaded.status == meta.status
        assert loaded.promoted_to == meta.promoted_to
        assert loaded.promoted_date == meta.promoted_date

    def test_yaml_omits_none_and_empty(self, tmp_path):
        path = tmp_path / "package.yaml"
        meta = self._valid_meta()
        meta.to_yaml_file(path)
        data = load_yaml(path)

        # These should be present
        assert "name" in data
        assert "description" in data

        # These should be absent (None or empty list)
        assert "parent" not in data
        assert "depends_on" not in data
        assert "suggests" not in data
        assert "tags" not in data
        assert "status" not in data
        assert "promoted_to" not in data

    def test_from_yaml_handles_missing_keys(self, tmp_path):
        path = tmp_path / "package.yaml"
        save_yaml({"name": "minimal"}, path)
        meta = PackageMetadata.from_yaml_file(path)
        assert meta.name == "minimal"
        assert meta.description == ""
        assert meta.authors == []
        assert meta.classification == "seasonal"
        assert meta.parent is None
        assert meta.depends_on == []
        assert meta.status is None

    def test_multiple_validation_errors(self):
        meta = PackageMetadata()  # all defaults = all empty
        errors = meta.validate()
        assert len(errors) >= 3  # name, description, authors


# ---------------------------------------------------------------------------
# RegistryEntry
# ---------------------------------------------------------------------------


class TestRegistryEntry:
    def test_defaults(self):
        entry = RegistryEntry()
        assert entry.description == ""
        assert entry.classification == ""
        assert entry.tags == []
        assert entry.path == ""
        assert entry.parent is None
        assert entry.depends_on == []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _sample_registry() -> Registry:
    """Build a small in-memory registry for testing."""
    return Registry(
        packages={
            "base": RegistryEntry(
                description="Universal coding conventions",
                classification="evergreen",
                tags=["core", "conventions"],
                path="packages/base",
            ),
            "git-conventions": RegistryEntry(
                description="Git commit message standards",
                classification="evergreen",
                tags=["git", "conventions"],
                path="packages/git-conventions",
                parent="base",
            ),
            "api-patterns": RegistryEntry(
                description="REST API patterns and auth",
                classification="seasonal",
                tags=["api", "rest"],
                path="packages/api-patterns",
                depends_on=["base"],
            ),
        }
    )


class TestRegistry:
    def test_yaml_round_trip(self, tmp_path):
        path = tmp_path / "registry.yaml"
        reg = _sample_registry()
        reg.to_yaml_file(path)
        loaded = Registry.from_yaml_file(path)

        assert set(loaded.packages.keys()) == {"base", "git-conventions", "api-patterns"}
        assert loaded.packages["base"].description == "Universal coding conventions"
        assert loaded.packages["api-patterns"].depends_on == ["base"]
        assert loaded.packages["git-conventions"].parent == "base"

    def test_search_exact_name(self):
        reg = _sample_registry()
        results = reg.search("base")
        assert results[0][0] == "base"

    def test_search_name_contains(self):
        reg = _sample_registry()
        results = reg.search("git")
        names = [name for name, _ in results]
        assert "git-conventions" in names

    def test_search_description(self):
        reg = _sample_registry()
        results = reg.search("REST")
        names = [name for name, _ in results]
        assert "api-patterns" in names

    def test_search_tag(self):
        reg = _sample_registry()
        results = reg.search("core")
        names = [name for name, _ in results]
        assert "base" in names

    def test_search_no_results(self):
        reg = _sample_registry()
        results = reg.search("nonexistent-xyz")
        assert results == []

    def test_search_relevance_order(self):
        reg = _sample_registry()
        # "conventions" appears in tags and descriptions
        results = reg.search("conventions")
        names = [name for name, _ in results]
        # Both should be found
        assert "base" in names
        assert "git-conventions" in names

    def test_get_children(self):
        reg = _sample_registry()
        children = reg.get_children("base")
        assert children == ["git-conventions"]

    def test_get_children_none(self):
        reg = _sample_registry()
        children = reg.get_children("api-patterns")
        assert children == []

    def test_resolve_dependency_chain_no_deps(self):
        reg = _sample_registry()
        chain = reg.resolve_dependency_chain("base")
        assert chain == ["base"]

    def test_resolve_dependency_chain_simple(self):
        reg = _sample_registry()
        chain = reg.resolve_dependency_chain("api-patterns")
        assert chain == ["base", "api-patterns"]

    def test_resolve_dependency_chain_transitive(self):
        reg = _sample_registry()
        # Add a package that depends on api-patterns (which depends on base)
        reg.packages["advanced-api"] = RegistryEntry(
            description="Advanced API patterns",
            classification="seasonal",
            depends_on=["api-patterns"],
        )
        chain = reg.resolve_dependency_chain("advanced-api")
        assert chain == ["base", "api-patterns", "advanced-api"]

    def test_resolve_dependency_chain_circular(self):
        reg = Registry(
            packages={
                "a": RegistryEntry(depends_on=["b"]),
                "b": RegistryEntry(depends_on=["a"]),
            }
        )
        with pytest.raises(ValueError, match="Circular dependency"):
            reg.resolve_dependency_chain("a")

    def test_resolve_dependency_chain_missing_package(self):
        reg = _sample_registry()
        with pytest.raises(ValueError, match="not found"):
            reg.resolve_dependency_chain("nonexistent")

    def test_resolve_dependency_chain_missing_dep(self):
        reg = Registry(
            packages={
                "a": RegistryEntry(depends_on=["missing"]),
            }
        )
        with pytest.raises(ValueError, match="not found"):
            reg.resolve_dependency_chain("a")

    def test_resolve_missing_dep_with_suggestion(self):
        """Transitive dependency 'bse' (typo for 'base') should suggest 'base'."""
        reg = Registry(
            packages={
                "base": RegistryEntry(),
                "child": RegistryEntry(depends_on=["bse"]),
            }
        )
        with pytest.raises(ValueError, match=r"Did you mean.*base"):
            reg.resolve_dependency_chain("child")

    def test_resolve_missing_with_suggestion(self):
        reg = _sample_registry()
        with pytest.raises(ValueError, match="Did you mean"):
            reg.resolve_dependency_chain("bse")  # close to "base"

    def test_find_similar_names(self):
        reg = _sample_registry()
        similar = reg.find_similar_names("bse")
        assert "base" in similar

    def test_find_similar_names_no_match(self):
        reg = _sample_registry()
        similar = reg.find_similar_names("zzzzzzzzz")
        assert similar == []

    def test_rebuild_from_packages(self, tmp_path):
        # Create a mini packages directory with one package
        pkg_dir = tmp_path / "packages" / "test-pkg"
        pkg_dir.mkdir(parents=True)
        meta = PackageMetadata(
            name="test-pkg",
            description="A test",
            authors=["Bob"],
            classification="evergreen",
            tags=["testing"],
            parent=None,
            depends_on=["base"],
        )
        meta.to_yaml_file(pkg_dir / "package.yaml")

        reg = Registry()
        reg.rebuild_from_packages(tmp_path / "packages")

        assert "test-pkg" in reg.packages
        entry = reg.packages["test-pkg"]
        assert entry.description == "A test"
        assert entry.classification == "evergreen"
        assert entry.tags == ["testing"]
        assert entry.path == "packages/test-pkg"
        assert entry.depends_on == ["base"]

    def test_rebuild_skips_non_directories(self, tmp_path):
        pkg_dir = tmp_path / "packages"
        pkg_dir.mkdir()
        (pkg_dir / "random-file.txt").write_text("not a package")

        reg = Registry()
        reg.rebuild_from_packages(pkg_dir)
        assert len(reg.packages) == 0

    def test_rebuild_skips_dirs_without_yaml(self, tmp_path):
        pkg_dir = tmp_path / "packages" / "no-yaml"
        pkg_dir.mkdir(parents=True)

        reg = Registry()
        reg.rebuild_from_packages(tmp_path / "packages")
        assert len(reg.packages) == 0

    def test_rebuild_nonexistent_dir(self, tmp_path):
        reg = Registry()
        reg.rebuild_from_packages(tmp_path / "nonexistent")
        assert len(reg.packages) == 0

    def test_from_yaml_skips_non_dict_entries(self, tmp_path):
        path = tmp_path / "registry.yaml"
        save_yaml(
            {"packages": {"good": {"description": "ok"}, "bad": "not-a-dict"}},
            path,
        )
        reg = Registry.from_yaml_file(path)
        assert "good" in reg.packages
        assert "bad" not in reg.packages


# ---------------------------------------------------------------------------
# Registry ID validation
# ---------------------------------------------------------------------------


class TestRegistryId:
    def test_valid_uuid_hex(self):
        reg = Registry(id="a3f7b2c19e4d4a8fb1234567890abcde")
        assert reg.validate_id() == []

    def test_missing_id(self):
        reg = Registry(id="")
        errors = reg.validate_id()
        assert any("required" in e for e in errors)

    def test_too_short(self):
        reg = Registry(id="abc123")
        errors = reg.validate_id()
        assert any("32-character" in e for e in errors)

    def test_uppercase_rejected(self):
        reg = Registry(id="A3F7B2C19E4D4A8FB1234567890ABCDE")
        errors = reg.validate_id()
        assert any("32-character" in e for e in errors)

    def test_non_hex_rejected(self):
        reg = Registry(id="g348a577b60f490ba872367ed8e41371")
        errors = reg.validate_id()
        assert any("32-character" in e for e in errors)

    def test_yaml_round_trip_with_id(self, tmp_path):
        path = tmp_path / "registry.yaml"
        reg = Registry(
            id="a3f7b2c19e4d4a8fb1234567890abcde",
            packages={
                "base": RegistryEntry(description="Test", path="packages/base"),
            },
        )
        reg.to_yaml_file(path)
        loaded = Registry.from_yaml_file(path)
        assert loaded.id == "a3f7b2c19e4d4a8fb1234567890abcde"

    def test_yaml_round_trip_without_id(self, tmp_path):
        path = tmp_path / "registry.yaml"
        reg = Registry(
            packages={
                "base": RegistryEntry(description="Test", path="packages/base"),
            },
        )
        reg.to_yaml_file(path)
        loaded = Registry.from_yaml_file(path)
        assert loaded.id == ""


# ---------------------------------------------------------------------------
# RegistrySource
# ---------------------------------------------------------------------------


class TestRegistrySource:
    def test_defaults(self):
        rs = RegistrySource()
        assert rs.id == ""
        assert rs.name == ""
        assert rs.source == ""
        assert rs.ref == ""
        assert rs.type == "git"

    def test_fields(self):
        rs = RegistrySource(
            id="abcd1234",
            name="internal",
            source="https://example.com/reg.git",
            ref="main",
            type="git",
        )
        assert rs.id == "abcd1234"
        assert rs.name == "internal"
        assert rs.source == "https://example.com/reg.git"
        assert rs.ref == "main"
        assert rs.type == "git"

    def test_local_type(self):
        rs = RegistrySource(id="ef567890", name="local-reg", source="/tmp/reg", type="local")
        assert rs.type == "local"
        assert rs.ref == ""


# ---------------------------------------------------------------------------
# InstalledPackage
# ---------------------------------------------------------------------------


class TestInstalledPackage:
    def test_defaults(self):
        pkg = InstalledPackage()
        assert pkg.name == ""
        assert pkg.ref == ""
        assert pkg.registry == ""

    def test_fields(self):
        pkg = InstalledPackage(name="base", ref="abc1234", registry="reg123")
        assert pkg.name == "base"
        assert pkg.ref == "abc1234"
        assert pkg.registry == "reg123"


# ---------------------------------------------------------------------------
# ProjectConfig
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ProjectConfig:
    """Helper to create a ProjectConfig with sensible defaults."""
    defaults = dict(
        registries=[
            RegistrySource(
                id="aabb1122",
                name="default",
                source="https://example.com/registry.git",
                ref="main",
                type="git",
            )
        ],
    )
    defaults.update(overrides)
    return ProjectConfig(**defaults)


class TestProjectConfig:
    def test_yaml_round_trip(self, tmp_path):
        path = tmp_path / "kt.yaml"
        config = _make_config(
            packages=[
                InstalledPackage(name="base", ref="abc1234", registry="aabb1122"),
                InstalledPackage(name="api-patterns", ref="def5678", registry="aabb1122"),
            ],
        )
        config.to_yaml_file(path)
        loaded = ProjectConfig.from_yaml_file(path)

        assert len(loaded.registries) == 1
        assert loaded.registries[0].source == "https://example.com/registry.git"
        assert loaded.registries[0].name == "default"
        assert loaded.registries[0].ref == "main"
        assert len(loaded.packages) == 2
        assert loaded.packages[0].name == "base"
        assert loaded.packages[0].ref == "abc1234"
        assert loaded.packages[0].registry == "aabb1122"
        assert loaded.packages[1].name == "api-patterns"

    def test_defaults(self):
        config = ProjectConfig()
        assert config.registries == []
        assert config.packages == []

    def test_add_package_new(self):
        config = _make_config()
        config.add_package("base", "abc1234", registry="aabb1122")
        assert len(config.packages) == 1
        assert config.packages[0].name == "base"
        assert config.packages[0].ref == "abc1234"
        assert config.packages[0].registry == "aabb1122"

    def test_add_package_update_existing(self):
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="old", registry="aabb1122")]
        )
        config.add_package("base", "new", registry="aabb1122")
        assert len(config.packages) == 1
        assert config.packages[0].ref == "new"

    def test_remove_package_exists(self):
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="abc", registry="aabb1122")]
        )
        result = config.remove_package("base")
        assert result is True
        assert len(config.packages) == 0

    def test_remove_package_not_found(self):
        config = _make_config()
        result = config.remove_package("nonexistent")
        assert result is False

    def test_get_installed_names(self):
        config = _make_config(
            packages=[
                InstalledPackage(name="base", ref="a", registry="aabb1122"),
                InstalledPackage(name="api-patterns", ref="b", registry="aabb1122"),
            ]
        )
        names = config.get_installed_names()
        assert names == {"base", "api-patterns"}

    def test_get_installed_names_empty(self):
        config = _make_config()
        assert config.get_installed_names() == set()

    def test_get_package_ref_found(self):
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="abc1234", registry="aabb1122")]
        )
        assert config.get_package_ref("base") == "abc1234"

    def test_get_package_ref_not_found(self):
        config = _make_config()
        assert config.get_package_ref("nonexistent") is None

    def test_from_yaml_handles_missing_keys(self, tmp_path):
        path = tmp_path / "kt.yaml"
        save_yaml({}, path)
        config = ProjectConfig.from_yaml_file(path)
        assert config.registries == []
        assert config.packages == []

    # --- Registry helpers ---

    def test_get_registry(self):
        config = _make_config()
        reg = config.get_registry("default")
        assert reg is not None
        assert reg.id == "aabb1122"
        assert config.get_registry("nonexistent") is None

    def test_get_registry_by_id(self):
        config = _make_config()
        reg = config.get_registry_by_id("aabb1122")
        assert reg is not None
        assert reg.name == "default"
        assert config.get_registry_by_id("nonexistent") is None

    def test_add_registry(self):
        config = _make_config()
        new_reg = RegistrySource(id="ccdd3344", name="internal", source="/tmp/reg", type="local")
        config.add_registry(new_reg)
        assert len(config.registries) == 2
        assert config.get_registry("internal") is not None

    def test_add_registry_duplicate_name(self):
        config = _make_config()
        dup = RegistrySource(id="xxxx", name="default", source="/tmp/dup", type="local")
        with pytest.raises(ValueError, match="already exists"):
            config.add_registry(dup)

    def test_remove_registry(self):
        config = _make_config()
        assert config.remove_registry("default") is True
        assert len(config.registries) == 0
        assert config.remove_registry("nonexistent") is False

    def test_get_registry_names(self):
        config = _make_config()
        new_reg = RegistrySource(id="ccdd3344", name="internal", source="/tmp/reg", type="local")
        config.add_registry(new_reg)
        assert config.get_registry_names() == ["default", "internal"]

    def test_get_installed_packages_by_registry(self):
        config = _make_config(
            packages=[
                InstalledPackage(name="base", ref="a", registry="aabb1122"),
                InstalledPackage(name="internal-rules", ref="b", registry="ccdd3344"),
            ]
        )
        from_default = config.get_installed_packages_by_registry("aabb1122")
        assert len(from_default) == 1
        assert from_default[0].name == "base"

    def test_get_package_registry(self):
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="a", registry="aabb1122")]
        )
        assert config.get_package_registry("base") == "aabb1122"
        assert config.get_package_registry("nonexistent") is None

    # --- Old format migration ---

    def test_old_format_migration(self, tmp_path):
        """Old kt.yaml with flat registry/registry_ref/registry_type should migrate."""
        path = tmp_path / "kt.yaml"
        save_yaml(
            {
                "registry": "https://example.com/registry.git",
                "registry_ref": "v1",
                "registry_type": "git",
                "packages": [{"name": "base", "ref": "abc1234"}],
            },
            path,
        )
        config = ProjectConfig.from_yaml_file(path)

        assert len(config.registries) == 1
        assert config.registries[0].name == "default"
        assert config.registries[0].source == "https://example.com/registry.git"
        assert config.registries[0].ref == "v1"
        assert config.registries[0].type == "git"
        assert config.registries[0].id == ""  # no ID in legacy format
        # Packages should be assigned to the default registry
        assert len(config.packages) == 1
        assert config.packages[0].registry == config.registries[0].id

    def test_old_format_local_migration(self, tmp_path):
        path = tmp_path / "kt.yaml"
        save_yaml(
            {
                "registry": "/tmp/local-reg",
                "registry_ref": "",
                "registry_type": "local",
                "packages": [],
            },
            path,
        )
        config = ProjectConfig.from_yaml_file(path)
        assert config.registries[0].type == "local"
        assert config.registries[0].ref == ""


# ---------------------------------------------------------------------------
# ExportedPackage
# ---------------------------------------------------------------------------


class TestExportedPackage:
    def test_defaults(self):
        exp = ExportedPackage()
        assert exp.name == ""
        assert exp.format == ""
        assert exp.ref == ""
        assert exp.registry == ""

    def test_fields(self):
        exp = ExportedPackage(
            name="base", format="claude-code", ref="abc1234", registry="aabb1122"
        )
        assert exp.name == "base"
        assert exp.format == "claude-code"
        assert exp.ref == "abc1234"
        assert exp.registry == "aabb1122"


# ---------------------------------------------------------------------------
# ProjectConfig export fields
# ---------------------------------------------------------------------------


class TestProjectConfigExports:
    def test_export_fields_default(self):
        config = _make_config()
        assert config.export_format == ""
        assert config.exports == []

    def test_yaml_round_trip_with_exports(self, tmp_path):
        path = tmp_path / "kt.yaml"
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="abc1234", registry="aabb1122")],
            export_format="claude-code",
            exports=[
                ExportedPackage(
                    name="base", format="claude-code", ref="abc1234", registry="aabb1122"
                ),
                ExportedPackage(
                    name="api-patterns", format="roo-code", ref="abc1234", registry="aabb1122"
                ),
            ],
        )
        config.to_yaml_file(path)
        loaded = ProjectConfig.from_yaml_file(path)

        assert loaded.export_format == "claude-code"
        assert len(loaded.exports) == 2
        assert loaded.exports[0].name == "base"
        assert loaded.exports[0].format == "claude-code"
        assert loaded.exports[1].name == "api-patterns"
        assert loaded.exports[1].format == "roo-code"

    def test_yaml_round_trip_without_exports(self, tmp_path):
        """Existing kt.yaml files without export fields should load fine."""
        path = tmp_path / "kt.yaml"
        config = _make_config(
            packages=[InstalledPackage(name="base", ref="abc1234", registry="aabb1122")],
        )
        config.to_yaml_file(path)
        loaded = ProjectConfig.from_yaml_file(path)

        assert loaded.export_format == ""
        assert loaded.exports == []

    def test_exports_omitted_from_yaml_when_empty(self, tmp_path):
        path = tmp_path / "kt.yaml"
        config = _make_config()
        config.to_yaml_file(path)
        data = load_yaml(path)
        assert "export_format" not in data
        assert "exports" not in data

    def test_add_export_new(self):
        config = _make_config()
        config.add_export("base", "claude-code", "abc1234", registry="aabb1122")
        assert len(config.exports) == 1
        assert config.exports[0].name == "base"
        assert config.exports[0].format == "claude-code"

    def test_add_export_update_existing(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="old", registry="aabb1122")
            ]
        )
        config.add_export("base", "claude-code", "new", registry="aabb1122")
        assert len(config.exports) == 1
        assert config.exports[0].ref == "new"

    def test_add_export_different_format(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="abc", registry="aabb1122")
            ]
        )
        config.add_export("base", "roo-code", "abc", registry="aabb1122")
        assert len(config.exports) == 2

    def test_remove_export_specific_format(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="abc"),
                ExportedPackage(name="base", format="roo-code", ref="abc"),
            ]
        )
        removed = config.remove_export("base", "claude-code")
        assert removed == 1
        assert len(config.exports) == 1
        assert config.exports[0].format == "roo-code"

    def test_remove_export_all_formats(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="abc"),
                ExportedPackage(name="base", format="roo-code", ref="abc"),
            ]
        )
        removed = config.remove_export("base")
        assert removed == 2
        assert config.exports == []

    def test_remove_export_nonexistent(self):
        config = _make_config()
        removed = config.remove_export("nonexistent")
        assert removed == 0

    def test_get_exports_all(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="abc"),
                ExportedPackage(name="api", format="roo-code", ref="abc"),
            ]
        )
        exports = config.get_exports()
        assert len(exports) == 2

    def test_get_exports_filtered(self):
        config = _make_config(
            exports=[
                ExportedPackage(name="base", format="claude-code", ref="abc"),
                ExportedPackage(name="api", format="roo-code", ref="abc"),
            ]
        )
        exports = config.get_exports("roo-code")
        assert len(exports) == 1
        assert exports[0].name == "api"

    def test_is_exported(self):
        config = _make_config(
            exports=[ExportedPackage(name="base", format="claude-code", ref="abc")]
        )
        assert config.is_exported("base") is True
        assert config.is_exported("base", "claude-code") is True
        assert config.is_exported("base", "roo-code") is False
        assert config.is_exported("nonexistent") is False


# ---------------------------------------------------------------------------
# _yaml_helpers
# ---------------------------------------------------------------------------


class TestYamlHelpers:
    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("")
        data = load_yaml(path)
        assert data == {}

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "file.yaml"
        save_yaml({"key": "value"}, path)
        assert path.exists()
        data = load_yaml(path)
        assert data["key"] == "value"

    def test_round_trip_preserves_types(self, tmp_path):
        path = tmp_path / "types.yaml"
        original = {
            "string": "hello",
            "number": 42,
            "boolean": True,
            "list": [1, 2, 3],
            "nested": {"a": "b"},
        }
        save_yaml(original, path)
        loaded = load_yaml(path)
        assert loaded["string"] == "hello"
        assert loaded["number"] == 42
        assert loaded["boolean"] is True
        assert loaded["list"] == [1, 2, 3]
        assert loaded["nested"]["a"] == "b"

    def test_load_corrupted_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text('": invalid: [broken')
        with pytest.raises(ValueError, match="Corrupted YAML"):
            load_yaml(path)

    def test_load_nonexistent_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_yaml(tmp_path / "nope.yaml")

    @pytest.mark.skipif(not hasattr(os, "chmod"), reason="chmod not available")
    def test_save_readonly_directory(self, tmp_path):
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        os.chmod(readonly, 0o444)
        try:
            with pytest.raises(OSError):
                save_yaml({"k": "v"}, readonly / "sub" / "file.yaml")
        finally:
            os.chmod(readonly, 0o755)

    @pytest.mark.skipif(not hasattr(os, "chmod"), reason="chmod not available")
    def test_load_permission_denied(self, tmp_path):
        path = tmp_path / "secret.yaml"
        path.write_text("key: value\n")
        os.chmod(path, 0o000)
        try:
            with pytest.raises(PermissionError):
                load_yaml(path)
        finally:
            os.chmod(path, 0o644)


# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------


class TestContentItem:
    def test_defaults(self):
        item = ContentItem()
        assert item.file == ""
        assert item.description == ""
        assert item.export_hints == {}

    def test_with_all_fields(self):
        item = ContentItem(
            file="api-ref.md",
            description="API reference",
            export_hints={"roo-code": "skills"},
        )
        assert item.file == "api-ref.md"
        assert item.description == "API reference"
        assert item.export_hints == {"roo-code": "skills"}


# ---------------------------------------------------------------------------
# PackageMetadata — content_type and export_hints
# ---------------------------------------------------------------------------


class TestPackageMetadataContentTypes:
    def _valid_meta(self, **overrides) -> PackageMetadata:
        defaults = dict(
            name="test-pkg",
            description="A test package",
            authors=["Alice"],
            classification="evergreen",
        )
        defaults.update(overrides)
        return PackageMetadata(**defaults)

    # --- content_type validation ---

    def test_content_type_knowledge_valid(self):
        meta = self._valid_meta(content_type="knowledge")
        assert meta.validate() == []

    def test_content_type_skills_valid(self):
        meta = self._valid_meta(content_type="skills")
        assert meta.validate() == []

    def test_content_type_empty_valid(self):
        meta = self._valid_meta(content_type="")
        assert meta.validate() == []

    def test_content_type_invalid(self):
        meta = self._valid_meta(content_type="bogus")
        errors = meta.validate()
        assert any("Invalid content_type" in e for e in errors)

    # --- export_hints validation ---

    def test_export_hints_valid(self):
        meta = self._valid_meta(export_hints={"roo-code": "skills"})
        assert meta.validate() == []

    def test_export_hints_commands_valid(self):
        meta = self._valid_meta(export_hints={"roo-code": "commands"})
        assert meta.validate() == []

    def test_export_hints_invalid_value(self):
        meta = self._valid_meta(export_hints={"roo-code": "bogus"})
        errors = meta.validate()
        assert any("Invalid export_hints value" in e for e in errors)

    # --- per-file export_hints validation ---

    def test_per_file_hints_valid(self):
        meta = self._valid_meta(
            content=[ContentItem(file="a.md", export_hints={"roo-code": "skills"})]
        )
        assert meta.validate() == []

    def test_per_file_hints_invalid(self):
        meta = self._valid_meta(
            content=[ContentItem(file="a.md", export_hints={"roo-code": "bogus"})]
        )
        errors = meta.validate()
        assert any("Invalid export_hints value" in e and "a.md" in e for e in errors)

    # --- YAML round-trip ---

    def test_yaml_round_trip_string_content(self, tmp_path):
        """Plain string content items survive round-trip as ContentItem."""
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(content=[ContentItem(file="overview.md")])
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)
        assert len(loaded.content) == 1
        assert loaded.content[0].file == "overview.md"
        assert loaded.content[0].description == ""
        assert loaded.content[0].export_hints == {}

    def test_yaml_round_trip_rich_content(self, tmp_path):
        """Rich content items with description and hints survive round-trip."""
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(
            content=[
                ContentItem(file="overview.md"),
                ContentItem(
                    file="api-ref.md",
                    description="API reference",
                    export_hints={"roo-code": "skills"},
                ),
            ]
        )
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)
        assert len(loaded.content) == 2
        assert loaded.content[0].file == "overview.md"
        assert loaded.content[1].file == "api-ref.md"
        assert loaded.content[1].description == "API reference"
        assert loaded.content[1].export_hints == {"roo-code": "skills"}

    def test_yaml_round_trip_content_type(self, tmp_path):
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(content_type="skills")
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)
        assert loaded.content_type == "skills"

    def test_yaml_round_trip_export_hints(self, tmp_path):
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(export_hints={"roo-code": "skills"})
        meta.to_yaml_file(path)
        loaded = PackageMetadata.from_yaml_file(path)
        assert loaded.export_hints == {"roo-code": "skills"}

    def test_yaml_omits_empty_new_fields(self, tmp_path):
        """New fields omitted from YAML when at defaults."""
        path = tmp_path / "package.yaml"
        meta = self._valid_meta()
        meta.to_yaml_file(path)
        data = load_yaml(path)
        assert "content_type" not in data
        assert "export_hints" not in data

    def test_yaml_simple_content_written_as_strings(self, tmp_path):
        """ContentItems with only file field serialize as plain strings."""
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(content=[ContentItem(file="a.md"), ContentItem(file="b.md")])
        meta.to_yaml_file(path)
        data = load_yaml(path)
        assert data["content"] == ["a.md", "b.md"]

    def test_yaml_rich_content_written_as_dicts(self, tmp_path):
        """ContentItems with extra fields serialize as dicts."""
        path = tmp_path / "package.yaml"
        meta = self._valid_meta(
            content=[
                ContentItem(file="a.md", description="Desc", export_hints={"roo-code": "skills"})
            ]
        )
        meta.to_yaml_file(path)
        data = load_yaml(path)
        assert isinstance(data["content"][0], dict)
        assert data["content"][0]["file"] == "a.md"
        assert data["content"][0]["description"] == "Desc"
        assert data["content"][0]["export_hints"] == {"roo-code": "skills"}

    def test_backward_compat_string_content_loads(self, tmp_path):
        """Existing YAML with content as plain string list loads correctly."""
        path = tmp_path / "package.yaml"
        save_yaml(
            {
                "name": "test-pkg",
                "description": "Test",
                "authors": ["Alice"],
                "classification": "evergreen",
                "content": ["overview.md", "reference.md"],
            },
            path,
        )
        loaded = PackageMetadata.from_yaml_file(path)
        assert len(loaded.content) == 2
        assert loaded.content[0].file == "overview.md"
        assert loaded.content[1].file == "reference.md"

    def test_backward_compat_no_content_type(self, tmp_path):
        """Missing content_type defaults to empty string."""
        path = tmp_path / "package.yaml"
        save_yaml(
            {
                "name": "test-pkg",
                "description": "Test",
                "authors": ["A"],
                "classification": "seasonal",
            },
            path,
        )
        loaded = PackageMetadata.from_yaml_file(path)
        assert loaded.content_type == ""
        assert loaded.export_hints == {}
