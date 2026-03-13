"""Core engine for Knowledge Tree operations."""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path
from typing import ClassVar

from knowledge_tree import git_ops, registry_source
from knowledge_tree.exporters import get_exporter
from knowledge_tree.models import (
    AddResult,
    ContentItem,
    ExportAllResult,
    FileInfo,
    PackageExportResult,
    PackageInfo,
    PackageListEntry,
    PackageMetadata,
    ProjectConfig,
    Registry,
    RegistryAddResult,
    RegistryInfo,
    RegistryPreview,
    RegistryPreviewPackage,
    RegistrySource,
    RemoveResult,
    SearchResultEntry,
    StatusResult,
    TemplateMapping,
    TreeData,
    TreeNode,
    UnexportAllResult,
    UnexportPackageResult,
    UpdateResult,
    ValidateResult,
)

# Files to exclude when exporting from cache (not content files)
_NON_CONTENT_FILES = {"package.yaml"}


def _ensure_dir_gitignore(dir_path: Path) -> None:
    """Create a .gitignore with '*' inside a directory so git ignores its contents."""
    dir_path.mkdir(parents=True, exist_ok=True)
    gitignore = dir_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")


class KnowledgeTreeEngine:
    """Orchestrates all Knowledge Tree operations for a project."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.knowledge_tree_dir = project_root / ".knowledge-tree"
        self.config_path = self.knowledge_tree_dir / "kt.yaml"
        self.cache_dir = self.knowledge_tree_dir / "cache"

    def _registry_cache_dir(self, registry_name: str) -> Path:
        """Return the cache directory for a named registry."""
        return self.cache_dir / registry_name

    def _load_config(self) -> ProjectConfig:
        if not self.config_path.exists():
            raise FileNotFoundError("Not initialized. Run `kt init <url>` first.")
        self._migrate_if_needed()
        config = ProjectConfig.from_yaml_file(self.config_path)
        # Auto-save if migrated from old format (registries list wasn't in file)
        if config.registries and not self._has_new_format():
            config.to_yaml_file(self.config_path)
        return config

    def _has_new_format(self) -> bool:
        """Check if kt.yaml already uses the new registries format."""
        from knowledge_tree._yaml_helpers import load_yaml

        data = load_yaml(self.config_path)
        return "registries" in data

    def _migrate_if_needed(self) -> None:
        """Placeholder for future migrations. No migrations needed currently."""
        pass

    def _ensure_cache(self, reg: RegistrySource) -> Path:
        """Ensure the registry cache is present, re-fetching if missing.

        Returns the cache directory path.
        """
        cache_dir = self._registry_cache_dir(reg.name)
        if (cache_dir / "registry.yaml").exists():
            return cache_dir
        # Cache missing — re-fetch from source
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        registry_source.populate_cache(
            source=reg.source,
            dest=cache_dir,
            branch=reg.ref,
            source_type=reg.type,
        )
        return cache_dir

    def _load_registry(
        self,
        registry_name: str = "default",
        reg_source: RegistrySource | None = None,
    ) -> Registry:
        """Load a registry from cache. Re-fetches if reg_source is provided and cache is missing."""
        if reg_source is not None:
            self._ensure_cache(reg_source)
        cache_dir = self._registry_cache_dir(registry_name)
        registry_yaml = cache_dir / "registry.yaml"
        if not registry_yaml.exists():
            raise FileNotFoundError(
                f"Registry cache for '{registry_name}' not found. Run `kt init <url>` first."
            )
        return Registry.from_yaml_file(registry_yaml)

    def _load_all_registries(self, config: ProjectConfig) -> dict[str, Registry]:
        """Load all configured registries. Returns {name: Registry}. Re-fetches missing caches."""
        registries = {}
        for reg_source in config.registries:
            registries[reg_source.name] = self._load_registry(
                reg_source.name, reg_source=reg_source
            )
        return registries

    def _resolve_registry_id(self, registry: Registry, config: ProjectConfig | None = None) -> str:
        """Return the canonical ID from registry.yaml.

        Validates the ID format and checks for collision with existing registries.
        Raises ValueError if the ID is missing, invalid, or collides.
        """
        errors = registry.validate_id()
        if errors:
            raise ValueError(f"Invalid registry: {'; '.join(errors)}")
        if config is not None:
            existing = config.get_registry_by_id(registry.id)
            if existing is not None:
                raise ValueError(
                    f"Registry id '{registry.id}' collides with existing "
                    f"registry '{existing.name}' ({existing.source})."
                )
        return registry.id

    def _get_current_ref(self, reg_source: RegistrySource) -> str:
        """Get the current ref for a registry, based on backend type."""
        cache_dir = self._registry_cache_dir(reg_source.name)
        if reg_source.type == "git":
            return git_ops.get_short_ref(cache_dir)
        if reg_source.type == "archive":
            return reg_source.ref or "archive"
        return "local"

    def _get_package_source_dir(
        self,
        package_name: str,
        registry: Registry,
        registry_name: str,
    ) -> Path:
        """Return the source directory for a package in the registry cache."""
        entry = registry.packages.get(package_name)
        if entry is None:
            raise ValueError(f"Package '{package_name}' not found in registry.")
        cache_dir = self._registry_cache_dir(registry_name)
        src = cache_dir / entry.path
        if not src.is_dir():
            raise ValueError(f"Package directory not found in registry cache: {entry.path}")
        return src

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def init(
        self,
        registry_url: str | None = None,
        branch: str = "main",
        source_type: str | None = None,
        registry_name: str = "default",
    ) -> list[str]:
        """Initialize a Knowledge Tree project.

        Creates .knowledge-tree/ with kt.yaml and a .gitignore containing '*'.
        When *registry_url* is provided, populates the registry cache and
        returns the list of available packages.
        When *registry_url* is ``None``, creates an empty project and returns [].
        Raises FileExistsError if already initialized.
        """
        if self.knowledge_tree_dir.exists():
            raise FileExistsError(
                "Already initialized. Remove .knowledge-tree/ directory to re-initialize."
            )

        self.knowledge_tree_dir.mkdir(parents=True)
        _ensure_dir_gitignore(self.knowledge_tree_dir)

        if registry_url is None:
            config = ProjectConfig(registries=[], packages=[])
            config.to_yaml_file(self.config_path)
            return []

        if source_type is None:
            source_type = registry_source.detect_source_type(registry_url)

        cache_dir = self._registry_cache_dir(registry_name)
        try:
            registry_source.populate_cache(
                source=registry_url,
                dest=cache_dir,
                branch=branch,
                source_type=source_type,
            )
        except (RuntimeError, OSError, ValueError):
            # Population failed — clean up partial state so user can retry
            shutil.rmtree(self.knowledge_tree_dir, ignore_errors=True)
            raise

        registry = self._load_registry(registry_name)
        reg_id = self._resolve_registry_id(registry)
        reg = RegistrySource(
            id=reg_id,
            name=registry_name,
            source=registry_url,
            ref=branch if source_type == "git" else "",
            type=source_type,
        )
        config = ProjectConfig(
            registries=[reg],
            packages=[],
        )
        config.to_yaml_file(self.config_path)

        return sorted(registry.packages.keys())

    # ------------------------------------------------------------------
    # add_registry
    # ------------------------------------------------------------------

    def add_registry(
        self,
        source: str,
        name: str | None = None,
        branch: str = "main",
        tool_format: str | None = None,
        install_packages: bool = True,
        selected_packages: list[str] | None = None,
    ) -> RegistryAddResult:
        """Add a new registry source to the project.

        When *install_packages* is ``True`` (default), installs all packages,
        exports them (if *tool_format* provided), and instantiates registry-level
        templates.

        When *selected_packages* is provided, only those packages are installed
        and exported (instead of all packages in the registry).

        When *install_packages* is ``False``, only registers the source.
        """
        result = RegistryAddResult()

        # Auto-init if .knowledge-tree/ doesn't exist
        if not self.knowledge_tree_dir.exists():
            self.init()

        # Auto-derive name from URL if not provided
        if name is None:
            parts = source.rstrip("/").split("/")
            name = parts[-1].replace(".git", "") if parts else "default"

        config = self._load_config()

        # Check if this source is already registered
        existing_reg = None
        for r in config.registries:
            if r.source == source:
                existing_reg = r
                break

        if existing_reg:
            # Reuse existing registry
            name = existing_reg.name
        else:
            if config.get_registry(name) is not None:
                raise ValueError(f"Registry '{name}' already exists.")

            source_type = registry_source.detect_source_type(source)
            cache_dir = self._registry_cache_dir(name)

            registry_source.populate_cache(
                source=source,
                dest=cache_dir,
                branch=branch,
                source_type=source_type,
            )

            registry_obj = self._load_registry(name)
            reg_id = self._resolve_registry_id(registry_obj, config)
            reg = RegistrySource(
                id=reg_id,
                name=name,
                source=source,
                ref=branch if source_type == "git" else "",
                type=source_type,
            )
            config.add_registry(reg)
            config.to_yaml_file(self.config_path)

        result.name = name
        result.source = source

        registry = self._load_registry(name)
        result.available_packages = sorted(registry.packages.keys())

        if not install_packages:
            return result

        # Determine which packages to install
        if selected_packages is not None:
            packages_to_install = sorted(selected_packages)
        else:
            packages_to_install = sorted(registry.packages.keys())

        # Install packages from this registry
        for pkg_name in packages_to_install:
            try:
                add_result = self.add_package(pkg_name, from_registry=name)
                result.packages_installed.extend(add_result.installed)
                result.packages_skipped.extend(add_result.already_installed)
            except ValueError:
                result.packages_skipped.append(pkg_name)

        # Export packages if tool format provided
        if tool_format:
            cache_dir = self._registry_cache_dir(name)
            for pkg_name in packages_to_install:
                try:
                    export_result = self.export_package(pkg_name, tool_format)
                    result.files_exported += len(export_result.files_written)
                    result.warnings.extend(export_result.warnings)
                except (ValueError, OSError):
                    pass  # best-effort

            # Collect command names that were exported
            for pkg_name in packages_to_install:
                entry = registry.packages.get(pkg_name)
                if entry:
                    pkg_yaml = cache_dir / entry.path / "package.yaml"
                    if pkg_yaml.exists():
                        meta = PackageMetadata.from_yaml_file(pkg_yaml)
                        for cmd in meta.commands:
                            result.commands_installed.append(cmd.name)

        # Instantiate registry-level templates
        cache_dir = self._registry_cache_dir(name)
        if registry.templates:
            inst, skip = self._instantiate_templates(registry.templates, cache_dir)
            result.templates_instantiated.extend(inst)
            result.templates_skipped.extend(skip)

        return result

    # ------------------------------------------------------------------
    # preview_registry
    # ------------------------------------------------------------------

    def preview_registry(
        self,
        source: str,
        name: str | None = None,
        branch: str = "main",
    ) -> RegistryPreview:
        """Clone/cache a registry and return a preview of what would be installed.

        Performs the clone/copy step but does NOT install, export, or
        instantiate templates.  Intended to be called before ``add_registry()``
        so the CLI can show a confirmation screen.

        If the registry is already registered (same source URL), reuses it.
        """
        preview = RegistryPreview()

        # Auto-init if .knowledge-tree/ doesn't exist
        if not self.knowledge_tree_dir.exists():
            self.init()

        # Auto-derive name from URL if not provided
        if name is None:
            parts = source.rstrip("/").split("/")
            name = parts[-1].replace(".git", "") if parts else "default"

        config = self._load_config()

        # Check if this source is already registered
        existing_reg = None
        for r in config.registries:
            if r.source == source:
                existing_reg = r
                break

        if existing_reg:
            name = existing_reg.name
            preview.source_type = existing_reg.type
        else:
            if config.get_registry(name) is not None:
                raise ValueError(f"Registry '{name}' already exists.")

            source_type = registry_source.detect_source_type(source)
            cache_dir = self._registry_cache_dir(name)

            registry_source.populate_cache(
                source=source,
                dest=cache_dir,
                branch=branch,
                source_type=source_type,
            )

            registry_obj = self._load_registry(name)
            reg_id = self._resolve_registry_id(registry_obj, config)
            reg = RegistrySource(
                id=reg_id,
                name=name,
                source=source,
                ref=branch if source_type == "git" else "",
                type=source_type,
            )
            config.add_registry(reg)
            config.to_yaml_file(self.config_path)
            preview.source_type = source_type

        preview.name = name
        preview.source = source

        # Load registry to enumerate packages
        registry = self._load_registry(name)
        cache_dir = self._registry_cache_dir(name)

        for pkg_name in sorted(registry.packages.keys()):
            entry = registry.packages[pkg_name]
            # Load full metadata for content_type
            content_type = "knowledge"
            pkg_yaml = cache_dir / entry.path / "package.yaml"
            if pkg_yaml.exists():
                meta = PackageMetadata.from_yaml_file(pkg_yaml)
                content_type = meta.content_type or "knowledge"

            preview.packages.append(
                RegistryPreviewPackage(
                    name=pkg_name,
                    description=entry.description,
                    classification=entry.classification or "seasonal",
                    content_type=content_type,
                    tags=list(entry.tags),
                    parent=entry.parent,
                )
            )

        # Templates — check which destinations already exist
        for tmpl in registry.templates:
            dest = self.project_root / tmpl.dest
            if dest.exists():
                preview.templates_existing.append(tmpl.dest)
            else:
                preview.templates.append(tmpl.dest)

        return preview

    # ------------------------------------------------------------------
    # remove_registry
    # ------------------------------------------------------------------

    def remove_registry(self, name: str, force: bool = False) -> None:
        """Remove a registry source and optionally its installed packages."""
        config = self._load_config()

        reg = config.get_registry(name)
        if reg is None:
            raise ValueError(f"Registry '{name}' not found.")

        # Check if any installed packages come from this registry
        from_this = config.get_installed_packages_by_registry(reg.id)
        if from_this and not force:
            names = ", ".join(pkg.name for pkg in from_this)
            raise ValueError(
                f"Registry '{name}' has installed packages: {names}. "
                f"Use --force to remove anyway, or remove packages first."
            )

        # Remove installed packages from this registry
        if from_this:
            for pkg in list(from_this):
                self.remove_package(pkg.name)
            # Reload config — remove_package() saves its own copy each iteration,
            # so our original snapshot is stale.
            config = self._load_config()

        # Remove cache dir
        cache_dir = self._registry_cache_dir(name)
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

        config.remove_registry(name)
        config.to_yaml_file(self.config_path)

    # ------------------------------------------------------------------
    # add_package
    # ------------------------------------------------------------------

    def add_package(
        self,
        package_name: str,
        from_registry: str | None = None,
        dry_run: bool = False,
    ) -> AddResult:
        """Install a package and its dependencies.

        Registers the package in kt.yaml. When *dry_run* is ``True``, resolves
        the dependency chain and reports what would be installed without writing
        anything to disk.
        """
        config = self._load_config()
        all_registries = self._load_all_registries(config)

        # Find which registries contain this package
        found_in: list[str] = []
        for reg_name, registry in all_registries.items():
            if package_name in registry.packages:
                found_in.append(reg_name)

        if not found_in:
            # Try to find similar names across all registries
            all_similar: list[str] = []
            for registry in all_registries.values():
                all_similar.extend(registry.find_similar_names(package_name))
            msg = f"Package '{package_name}' not found in any registry."
            if all_similar:
                unique = sorted(set(all_similar))
                msg += f" Did you mean: {', '.join(unique)}?"
            raise ValueError(msg)

        # Resolve which registry to use
        if from_registry:
            if from_registry not in all_registries:
                raise ValueError(f"Registry '{from_registry}' not found.")
            if from_registry not in found_in:
                raise ValueError(
                    f"Package '{package_name}' not found in registry '{from_registry}'."
                )
            target_reg_name = from_registry
        elif len(found_in) == 1:
            target_reg_name = found_in[0]
        else:
            raise ValueError(
                f"Package '{package_name}' found in multiple registries: "
                f"{', '.join(found_in)}. "
                f"Use --from <registry> to specify which one."
            )

        registry = all_registries[target_reg_name]
        reg_source = config.get_registry(target_reg_name)
        chain = registry.resolve_ancestor_chain(package_name)

        installed_names = config.get_installed_names()
        newly_installed: list[str] = []
        already_installed: list[str] = []
        ref = self._get_current_ref(reg_source)

        for name in chain:
            if name in installed_names:
                # Check if installed from the same registry
                existing_reg = config.get_package_registry(name)
                if existing_reg != reg_source.id:
                    existing_reg_source = config.get_registry_by_id(existing_reg)
                    existing_name = existing_reg_source.name if existing_reg_source else "unknown"
                    raise ValueError(
                        f"Package '{name}' is already installed from registry "
                        f"'{existing_name}'. Package '{package_name}' from registry "
                        f"'{target_reg_name}' also requires '{name}'. "
                        f"Remove '{name}' first or ensure registries don't "
                        f"share package names."
                    )
                already_installed.append(name)
                continue

            if not dry_run:
                config.add_package(name, ref, registry=reg_source.id)
            installed_names.add(name)
            newly_installed.append(name)

        if not dry_run:
            config.to_yaml_file(self.config_path)

        result = AddResult(
            installed=newly_installed,
            already_installed=already_installed,
            registry=target_reg_name,
        )

        # Auto-export newly installed packages if tool format is configured
        if not dry_run and newly_installed:
            config = self._load_config()
            if config.export_format:
                for pkg in newly_installed:
                    try:
                        export_result = self.export_package(pkg, config.export_format)
                        result.files_exported += len(export_result.files_written)
                        result.warnings.extend(export_result.warnings)
                    except (ValueError, OSError):
                        pass  # best-effort

        return result

    # ------------------------------------------------------------------
    # remove_package
    # ------------------------------------------------------------------

    def remove_package(self, package_name: str) -> RemoveResult:
        """Remove a package."""
        config = self._load_config()
        all_registries = self._load_all_registries(config)

        if package_name not in config.get_installed_names():
            # Try similar names across all registries
            all_similar: list[str] = []
            for registry in all_registries.values():
                all_similar.extend(registry.find_similar_names(package_name))
            msg = f"Package '{package_name}' is not installed."
            if all_similar:
                unique = sorted(set(all_similar))
                msg += f" Did you mean: {', '.join(unique)}?"
            raise ValueError(msg)

        # Find the registry this package came from
        pkg_reg_id = config.get_package_registry(package_name)
        pkg_reg_source = config.get_registry_by_id(pkg_reg_id) if pkg_reg_id else None
        pkg_reg_name = pkg_reg_source.name if pkg_reg_source else "default"

        # Check if any installed children exist
        installed_children = []
        reg = all_registries.get(pkg_reg_name)
        if reg:
            for child_name in reg.get_children(package_name):
                if child_name in config.get_installed_names():
                    installed_children.append(child_name)

        # Clean up any exports for this package
        exported_formats: list[str] = []
        for exp in config.get_exports():
            if exp.name == package_name:
                try:
                    reg_name = pkg_reg_name
                    if exp.registry:
                        exp_reg = config.get_registry_by_id(exp.registry)
                        if exp_reg:
                            reg_name = exp_reg.name
                    exporter = get_exporter(exp.format, self.project_root)
                    exporter.unexport_package(package_name, registry_name=reg_name)
                    exported_formats.append(exp.format)
                except (ValueError, OSError):
                    pass  # best-effort cleanup
        config.remove_export(package_name)

        config.remove_package(package_name)
        config.to_yaml_file(self.config_path)

        return RemoveResult(removed=True, children=installed_children, unexported=exported_formats)

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    def update(
        self,
        package_name: str | None = None,
        new_format: str | None = None,
    ) -> UpdateResult:
        """Refresh registry caches and re-export installed packages.

        When *package_name* is provided, only that package is re-exported
        (its registry is still refreshed).  When ``None``, all installed
        packages are updated.
        When *new_format* is provided, switches the export format: unexports
        old format and re-exports all installed packages in the new format.
        Raises ValueError if *package_name* is given but not installed.
        """
        config = self._load_config()
        all_updated: list[str] = []
        all_failed: list[str] = []
        all_new_evergreen: list[str] = []
        refs_by_registry: dict[str, str] = {}
        installed_names = config.get_installed_names()

        # Handle format switch
        format_switched = False
        old_format = ""
        if new_format and new_format != config.export_format:
            old_format = config.export_format
            if old_format:
                self.unexport_all(old_format)
            config.export_format = new_format
            config.to_yaml_file(self.config_path)
            format_switched = True

        if package_name and package_name not in installed_names:
            raise ValueError(f"Package '{package_name}' is not installed.")

        # When targeting a single package, only refresh its registry
        if package_name:
            target_pkg = next(p for p in config.packages if p.name == package_name)
            target_registries = [r for r in config.registries if r.id == target_pkg.registry]
        else:
            target_registries = config.registries

        for reg_source in target_registries:
            cache_dir = self._registry_cache_dir(reg_source.name)
            try:
                # Nuke and re-fetch for a clean cache
                if cache_dir.exists():
                    shutil.rmtree(cache_dir)
                short_ref = registry_source.populate_cache(
                    source=reg_source.source,
                    dest=cache_dir,
                    branch=reg_source.ref,
                    source_type=reg_source.type,
                )
            except (RuntimeError, OSError, FileNotFoundError) as exc:
                warnings.warn(
                    f"Failed to refresh registry '{reg_source.name}': {exc}",
                    stacklevel=2,
                )
                continue

            refs_by_registry[reg_source.name] = short_ref

            registry = self._load_registry(reg_source.name)

            # Update ref for packages from THIS registry
            for pkg in config.packages:
                if pkg.registry != reg_source.id:
                    continue
                if package_name and pkg.name != package_name:
                    continue
                if pkg.name not in registry.packages:
                    continue
                try:
                    config.add_package(pkg.name, short_ref, registry=reg_source.id)
                    all_updated.append(pkg.name)
                except (ValueError, OSError) as exc:
                    all_failed.append(pkg.name)
                    warnings.warn(
                        f"Failed to update '{pkg.name}': {exc}",
                        stacklevel=2,
                    )

            # Detect new evergreen from this registry (skip for selective update)
            if not package_name:
                for name, entry in registry.packages.items():
                    if name not in installed_names and entry.classification == "evergreen":
                        all_new_evergreen.append(name)

        config.to_yaml_file(self.config_path)

        # Auto-re-export: all installed if format switched, else just updated
        files_re_exported = 0
        if config.export_format:
            pkgs_to_export = list(installed_names) if format_switched else all_updated
            for pkg in pkgs_to_export:
                try:
                    self.export_package(pkg, config.export_format, force=True)
                    files_re_exported += 1
                except (ValueError, OSError):
                    pass  # best-effort

        return UpdateResult(
            updated_packages=all_updated,
            failed_packages=all_failed,
            refs=refs_by_registry,
            new_evergreen=sorted(all_new_evergreen),
            files_re_exported=files_re_exported,
            format_switched=format_switched,
            old_format=old_format,
            new_format=new_format or "",
        )

    # ------------------------------------------------------------------
    # list_packages
    # ------------------------------------------------------------------

    def list_packages(
        self,
        available: bool = False,
        community: bool = False,
    ) -> list[PackageListEntry]:
        """List packages across all registries."""
        config = self._load_config()
        installed_names = config.get_installed_names()
        results: list[PackageListEntry] = []

        if community:
            for reg_source in config.registries:
                cache_dir = self._registry_cache_dir(reg_source.name)
                community_dir = cache_dir / "community"
                if community_dir.is_dir():
                    for pkg_dir in sorted(community_dir.iterdir()):
                        if not pkg_dir.is_dir():
                            continue
                        yaml_path = pkg_dir / "package.yaml"
                        if yaml_path.exists():
                            meta = PackageMetadata.from_yaml_file(yaml_path)
                            results.append(
                                PackageListEntry(
                                    name=meta.name,
                                    description=meta.description,
                                    classification=meta.classification,
                                    tags=meta.tags,
                                    status=meta.status or "pending",
                                    installed=meta.name in installed_names,
                                    source="community",
                                    registry=reg_source.name,
                                )
                            )
            return results

        for reg_source in config.registries:
            registry = self._load_registry(reg_source.name)
            for name, entry in sorted(registry.packages.items()):
                is_installed = name in installed_names
                if available and is_installed:
                    continue
                if not available and not is_installed:
                    continue
                results.append(
                    PackageListEntry(
                        name=name,
                        description=entry.description,
                        classification=entry.classification,
                        tags=entry.tags,
                        installed=is_installed,
                        ref=config.get_package_ref(name) or "",
                        source="registry",
                        registry=reg_source.name,
                    )
                )

        return results

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[SearchResultEntry]:
        """Search packages across all registries."""
        config = self._load_config()
        installed_names = config.get_installed_names()
        results: list[SearchResultEntry] = []

        for reg_source in config.registries:
            registry = self._load_registry(reg_source.name)
            for name, entry in registry.search(query):
                results.append(
                    SearchResultEntry(
                        name=name,
                        description=entry.description,
                        classification=entry.classification,
                        tags=entry.tags,
                        installed=name in installed_names,
                        registry=reg_source.name,
                    )
                )

        return results

    # ------------------------------------------------------------------
    # get_tree_data
    # ------------------------------------------------------------------

    def get_tree_data(self) -> TreeData:
        """Build nested tree structure for rendering."""
        config = self._load_config()
        installed_names = config.get_installed_names()
        all_roots: list[TreeNode] = []

        for reg_source in config.registries:
            registry = self._load_registry(reg_source.name)

            # Build tree for this registry
            nodes: dict[str, TreeNode] = {}
            for name, entry in registry.packages.items():
                nodes[name] = TreeNode(
                    name=name,
                    description=entry.description,
                    classification=entry.classification,
                    installed=name in installed_names,
                    children=[],
                    registry=reg_source.name,
                )

            # Link parents
            roots: list[TreeNode] = []
            for name, entry in registry.packages.items():
                node = nodes[name]
                if entry.parent and entry.parent in nodes:
                    nodes[entry.parent].children.append(node)
                else:
                    roots.append(node)

            # Sort
            roots.sort(key=lambda n: n.name)
            for node in nodes.values():
                node.children.sort(key=lambda n: n.name)

            all_roots.extend(roots)

        return TreeData(roots=all_roots)

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def get_status(self) -> StatusResult:
        """Get project status summary."""
        config = self._load_config()
        installed_names = config.get_installed_names()

        total_available = 0
        reg_pkg_counts: dict[str, int] = {}
        for reg_source in config.registries:
            registry = self._load_registry(reg_source.name)
            count = len(registry.packages)
            reg_pkg_counts[reg_source.name] = count
            total_available += count

        # Count files from registry cache for installed packages
        total_files = 0
        total_lines = 0
        for reg_source in config.registries:
            registry = self._load_registry(reg_source.name)
            for pkg in config.get_installed_packages_by_registry(reg_source.id):
                entry = registry.packages.get(pkg.name)
                if entry is None:
                    continue
                try:
                    src = self._get_package_source_dir(pkg.name, registry, reg_source.name)
                    for f in src.iterdir():
                        if f.is_file() and f.name not in _NON_CONTENT_FILES:
                            total_files += 1
                            total_lines += len(f.read_text().splitlines())
                except (ValueError, OSError):
                    pass

        return StatusResult(
            registries=[
                RegistryInfo(
                    name=r.name,
                    source=r.source,
                    ref=r.ref,
                    type=r.type,
                    package_count=reg_pkg_counts.get(r.name, 0),
                )
                for r in config.registries
            ],
            installed_count=len(installed_names),
            available_count=total_available - len(installed_names),
            total_files=total_files,
            total_lines=total_lines,
            export_format=config.export_format,
            exported_count=len(config.exports),
        )

    # ------------------------------------------------------------------
    # get_info
    # ------------------------------------------------------------------

    def get_info(self, package_name: str) -> PackageInfo:
        """Get detailed info for a package."""
        config = self._load_config()
        all_registries = self._load_all_registries(config)

        # Find which registry has this package
        target_reg_name = None
        target_registry = None
        for reg_name, registry in all_registries.items():
            if package_name in registry.packages:
                target_reg_name = reg_name
                target_registry = registry
                break

        if target_registry is None:
            all_similar: list[str] = []
            for registry in all_registries.values():
                all_similar.extend(registry.find_similar_names(package_name))
            msg = f"Package '{package_name}' not found in any registry."
            if all_similar:
                unique = sorted(set(all_similar))
                msg += f" Did you mean: {', '.join(unique)}?"
            raise ValueError(msg)

        entry = target_registry.packages[package_name]
        is_installed = package_name in config.get_installed_names()

        # Load full metadata from cache
        cache_dir = self._registry_cache_dir(target_reg_name)
        pkg_yaml = cache_dir / entry.path / "package.yaml"
        meta = PackageMetadata.from_yaml_file(pkg_yaml) if pkg_yaml.exists() else None

        # Count content files from cache
        files_info: list[FileInfo] = []
        if is_installed:
            try:
                src = self._get_package_source_dir(package_name, target_registry, target_reg_name)
                for f in sorted(src.iterdir()):
                    if f.is_file() and f.name not in _NON_CONTENT_FILES:
                        lines = len(f.read_text().splitlines())
                        files_info.append(FileInfo(name=f.name, lines=lines))
            except (ValueError, OSError):
                pass

        children = target_registry.get_children(package_name)
        ancestors = target_registry.resolve_ancestor_chain(package_name)
        ancestors.remove(package_name)  # remove self

        # Export status
        export_formats = [exp.format for exp in config.exports if exp.name == package_name]

        return PackageInfo(
            name=package_name,
            description=entry.description,
            classification=entry.classification,
            tags=entry.tags,
            parent=entry.parent,
            children=children,
            ancestors=ancestors,
            installed=is_installed,
            ref=config.get_package_ref(package_name) or "",
            files=files_info,
            authors=meta.authors if meta else [],
            created=meta.created if meta else None,
            updated=meta.updated if meta else None,
            exported_to=export_formats,
            registry=target_reg_name,
        )

    # ------------------------------------------------------------------
    # config get / set
    # ------------------------------------------------------------------

    # Keys that can be read/written via ``kt config``.
    _CONFIG_KEYS: ClassVar[dict[str, str]] = {
        "export_format": "Default export format (e.g. claude-code, roo-code)",
    }

    def get_config(self, key: str) -> str:
        """Return the value of a config key (empty string if unset)."""
        if key not in self._CONFIG_KEYS:
            available = ", ".join(sorted(self._CONFIG_KEYS))
            raise ValueError(f"Unknown config key '{key}'. Valid keys: {available}")
        config = self._load_config()
        return getattr(config, key)

    def set_config(self, key: str, value: str) -> None:
        """Set a config key and persist to kt.yaml."""
        if key not in self._CONFIG_KEYS:
            available = ", ".join(sorted(self._CONFIG_KEYS))
            raise ValueError(f"Unknown config key '{key}'. Valid keys: {available}")
        config = self._load_config()
        setattr(config, key, value)
        config.to_yaml_file(self.config_path)

    # ------------------------------------------------------------------
    # validate_package
    # ------------------------------------------------------------------

    def validate_package(self, package_path: Path) -> ValidateResult:
        """Validate a package at the given path."""
        errors: list[str] = []
        warn_list: list[str] = []

        yaml_path = package_path / "package.yaml"
        if not yaml_path.exists():
            errors.append("Missing package.yaml")
            return ValidateResult(valid=False, errors=errors, warnings=warn_list)

        try:
            meta = PackageMetadata.from_yaml_file(yaml_path)
        except ValueError as exc:
            errors.append(f"Invalid package.yaml: {exc}")
            return ValidateResult(valid=False, errors=errors, warnings=warn_list)

        errors.extend(meta.validate())

        # Check content files exist
        if meta.content:
            for item in meta.content:
                if not (package_path / item.file).exists():
                    errors.append(f"Content file '{item.file}' listed but not found")
        else:
            # No explicit content list — check for any .md files (recursive)
            md_files = list(package_path.rglob("*.md"))
            if not md_files:
                warn_list.append("No content list in package.yaml and no .md files found")

        return ValidateResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warn_list,
        )

    # ------------------------------------------------------------------
    # validate_registry
    # ------------------------------------------------------------------

    def validate_registry(self, registry_path: Path) -> ValidateResult:
        """Validate a registry.yaml at the given path."""
        errors: list[str] = []
        warn_list: list[str] = []

        yaml_path = registry_path / "registry.yaml"
        if not yaml_path.exists():
            errors.append("Missing registry.yaml")
            return ValidateResult(valid=False, errors=errors, warnings=warn_list)

        try:
            reg = Registry.from_yaml_file(yaml_path)
        except ValueError as exc:
            errors.append(f"Invalid registry.yaml: {exc}")
            return ValidateResult(valid=False, errors=errors, warnings=warn_list)

        errors.extend(reg.validate_id())
        errors.extend(reg.validate_tree())

        return ValidateResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warn_list,
        )

    # ------------------------------------------------------------------
    # export_package
    # ------------------------------------------------------------------

    def export_package(
        self,
        package_name: str,
        export_format: str,
        force: bool = False,
    ) -> PackageExportResult:
        """Export a single installed package to a tool-specific format.

        Reads directly from the registry cache and writes to the tool directory.
        Ensures the tool output directory has a .gitignore.
        """
        config = self._load_config()
        all_registries = self._load_all_registries(config)

        if package_name not in config.get_installed_names():
            all_similar: list[str] = []
            for registry in all_registries.values():
                all_similar.extend(registry.find_similar_names(package_name))
            msg = f"Package '{package_name}' is not installed."
            if all_similar:
                unique = sorted(set(all_similar))
                msg += f" Did you mean: {', '.join(unique)}?"
            raise ValueError(msg)

        # Find which registry this package is from
        pkg_reg_id = config.get_package_registry(package_name)
        pkg_reg_source = config.get_registry_by_id(pkg_reg_id) if pkg_reg_id else None
        reg_name = pkg_reg_source.name if pkg_reg_source else "default"

        registry = all_registries.get(reg_name)
        cache_dir = self._registry_cache_dir(reg_name)

        exporter = get_exporter(export_format, self.project_root)

        # Source is directly from cache
        source_dir = cache_dir
        if registry:
            entry = registry.packages.get(package_name)
            if entry:
                source_dir = cache_dir / entry.path

        # Load metadata from cache for the exporter
        meta = PackageMetadata(name=package_name, description="")
        if registry:
            entry = registry.packages.get(package_name)
            if entry:
                pkg_yaml = cache_dir / entry.path / "package.yaml"
                if pkg_yaml.exists():
                    meta = PackageMetadata.from_yaml_file(pkg_yaml)

        result = exporter.export_package(
            package_name, source_dir, meta, force=force, registry_name=reg_name
        )

        # Ensure tool output directories have .gitignore
        if result.files_written:
            self._ensure_tool_gitignore(export_format)
            ref = self._get_current_ref(pkg_reg_source) if pkg_reg_source else ""
            config.add_export(package_name, export_format, ref, registry=pkg_reg_id or "")
            # Save default format if not already set
            if not config.export_format:
                config.export_format = export_format
            config.to_yaml_file(self.config_path)

        return PackageExportResult(
            exported=bool(result.files_written),
            files_written=[str(f) for f in result.files_written],
            files_skipped=[str(f) for f in result.files_skipped],
            warnings=list(result.warnings),
        )

    def _ensure_tool_gitignore(self, export_format: str) -> None:
        """Ensure the tool output directory has a .gitignore with '*'."""
        if export_format == "claude-code":
            _ensure_dir_gitignore(self.project_root / ".claude")
        elif export_format == "roo-code":
            _ensure_dir_gitignore(self.project_root / ".roo")

    # ------------------------------------------------------------------
    # export_all
    # ------------------------------------------------------------------

    def export_all(
        self,
        export_format: str,
        force: bool = False,
    ) -> ExportAllResult:
        """Export all installed packages to a tool-specific format."""
        config = self._load_config()
        installed_names = sorted(config.get_installed_names())

        exported: list[str] = []
        skipped: list[str] = []
        total_files = 0
        all_warnings: list[str] = []

        for name in installed_names:
            result = self.export_package(name, export_format, force=force)
            if result.exported:
                exported.append(name)
                total_files += len(result.files_written)
            elif result.files_skipped:
                skipped.append(name)
            all_warnings.extend(result.warnings)

        return ExportAllResult(
            exported=exported,
            skipped=skipped,
            total_files=total_files,
            warnings=all_warnings,
        )

    # ------------------------------------------------------------------
    # unexport_package
    # ------------------------------------------------------------------

    def unexport_package(
        self,
        package_name: str,
        export_format: str | None = None,
    ) -> UnexportPackageResult:
        """Remove exported files for a package.

        If export_format is None, removes exports in all formats.
        """
        config = self._load_config()
        files_removed: list[str] = []

        exports_to_remove = config.get_exports(export_format)
        exports_to_remove = [e for e in exports_to_remove if e.name == package_name]

        if not exports_to_remove:
            return UnexportPackageResult(removed=False, files_removed=[])

        for exp in exports_to_remove:
            # Resolve registry name for the export
            reg_name = "default"
            if exp.registry:
                reg_source = config.get_registry_by_id(exp.registry)
                if reg_source:
                    reg_name = reg_source.name

            exporter = get_exporter(exp.format, self.project_root)
            result = exporter.unexport_package(package_name, registry_name=reg_name)
            files_removed.extend(str(f) for f in result.files_removed)
            config.remove_export(package_name, exp.format)

        config.to_yaml_file(self.config_path)
        return UnexportPackageResult(removed=True, files_removed=files_removed)

    # ------------------------------------------------------------------
    # unexport_all
    # ------------------------------------------------------------------

    def unexport_all(self, export_format: str | None = None) -> UnexportAllResult:
        """Remove all exported files."""
        config = self._load_config()
        exports = config.get_exports(export_format)

        removed: list[str] = []
        total_files = 0

        # Get unique package names
        names = sorted({e.name for e in exports})
        for name in names:
            result = self.unexport_package(name, export_format)
            if result.removed:
                removed.append(name)
                total_files += len(result.files_removed)

        return UnexportAllResult(removed=removed, total_files=total_files)

    # ------------------------------------------------------------------
    # wire
    # ------------------------------------------------------------------

    def _detect_tool_format(self) -> str | None:
        """Auto-detect tool format from project markers."""
        if (self.project_root / ".claude").is_dir():
            return "claude-code"
        if (self.project_root / ".roo").is_dir():
            return "roo-code"
        return None

    def _instantiate_templates(
        self,
        templates: list[TemplateMapping],
        source_base: Path,
    ) -> tuple[list[str], list[str]]:
        """Copy template files to project root. Skip destinations that exist.

        Also ensures a .gitignore is placed in each destination directory
        that KT creates.

        Returns (instantiated, skipped) lists of destination paths.
        """
        instantiated: list[str] = []
        skipped: list[str] = []
        gitignored_dirs: set[Path] = set()

        for tmpl in templates:
            dest = self.project_root / tmpl.dest
            if dest.exists():
                skipped.append(tmpl.dest)
                continue

            src = source_base / tmpl.source
            if not src.exists():
                skipped.append(tmpl.dest)
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            instantiated.append(tmpl.dest)

            # Ensure the top-level directory created by this template has a .gitignore
            rel = Path(tmpl.dest)
            if len(rel.parts) > 1:
                top_dir = self.project_root / rel.parts[0]
                if top_dir not in gitignored_dirs:
                    _ensure_dir_gitignore(top_dir)
                    gitignored_dirs.add(top_dir)

        return instantiated, skipped

    # ------------------------------------------------------------------
    # contribute (Phase 2)
    # ------------------------------------------------------------------

    def contribute(
        self,
        file_path: Path,
        name: str,
        to_existing: str | None = None,
        registry_name: str | None = None,
    ) -> str:
        """Contribute a knowledge file to the community directory.

        Returns the MR/PR URL string.
        Only supported for git-based registries.
        """
        config = self._load_config()

        # Find target registry
        if registry_name:
            reg_source = config.get_registry(registry_name)
            if reg_source is None:
                raise ValueError(f"Registry '{registry_name}' not found.")
        else:
            # Default: first git registry
            reg_source = None
            for r in config.registries:
                if r.type == "git":
                    reg_source = r
                    break
            if reg_source is None:
                raise RuntimeError("No git-based registry configured. Contributing requires git.")

        if reg_source.type != "git":
            raise RuntimeError(
                "Contributing is only supported for git-based registries. "
                f"Registry '{reg_source.name}' uses '{reg_source.type}'."
            )

        cache_dir = self._registry_cache_dir(reg_source.name)

        # Unshallow the cache so we can push
        git_ops.unshallow(cache_dir)

        # Create branch
        branch_name = f"contribute/{name}"
        git_ops.create_branch(cache_dir, branch_name)

        # Determine destination
        if to_existing:
            dest_dir = cache_dir / "community" / to_existing / name
        else:
            dest_dir = cache_dir / "community" / name
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy file
        shutil.copy2(file_path, dest_dir / file_path.name)

        # Generate package.yaml
        meta = PackageMetadata(
            name=name,
            description=f"Community contribution: {name}",
            authors=["Contributor"],
            classification="seasonal",
            status="pending",
            content=[ContentItem(file=file_path.name)],
        )
        meta.to_yaml_file(dest_dir / "package.yaml")

        # Commit and push
        git_ops.add_and_commit(
            cache_dir,
            [str(dest_dir.relative_to(cache_dir))],
            f"Add community package: {name}",
        )
        git_ops.push_branch(cache_dir, branch_name)

        # Generate MR URL
        remote_url = git_ops.run_git(["remote", "get-url", "origin"], cwd=cache_dir)
        return git_ops.get_mr_url(remote_url, branch_name)

    # ------------------------------------------------------------------
    # registry_rebuild (Phase 2)
    # ------------------------------------------------------------------

    def registry_rebuild(self, registry_path: Path) -> int:
        """Rebuild registry.yaml from packages directory.

        Preserves the existing registry id if present, otherwise generates one.
        Returns the number of packages found.
        """
        import uuid

        yaml_path = registry_path / "registry.yaml"

        # Preserve existing id and templates (or generate a new id)
        existing_id = ""
        existing_templates: list = []
        if yaml_path.exists():
            try:
                existing = Registry.from_yaml_file(yaml_path)
                existing_id = existing.id
                existing_templates = existing.templates
            except ValueError:
                pass  # Corrupted file — will be overwritten

        packages_dir = registry_path / "packages"
        registry = Registry()
        registry.id = existing_id if existing_id else uuid.uuid4().hex
        registry.templates = existing_templates
        registry.rebuild_from_packages(packages_dir)
        registry.to_yaml_file(yaml_path)
        return len(registry.packages)
