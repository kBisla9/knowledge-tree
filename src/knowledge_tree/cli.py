"""CLI interface for Knowledge Tree."""

from __future__ import annotations

import functools
import os
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from knowledge_tree.engine import KnowledgeTreeEngine
from knowledge_tree.exporters import list_formats
from knowledge_tree.models import RegistryAddResult, RegistryPreview

console = Console()
err_console = Console(stderr=True)


def _get_engine() -> KnowledgeTreeEngine:
    return KnowledgeTreeEngine(Path.cwd())


def _is_debug() -> bool:
    """Check if debug mode is enabled via --debug flag or KT_DEBUG env var."""
    ctx = click.get_current_context(silent=True)
    if ctx and ctx.find_root().params.get("debug"):
        return True
    return os.environ.get("KT_DEBUG", "") not in ("", "0")


def _handle_error(func):
    """Decorator for common error handling across commands."""

    @functools.wraps(func)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        try:
            return ctx.invoke(func, *args, **kwargs)
        except FileNotFoundError as e:
            if _is_debug():
                raise
            err_console.print(f"[red]{e}[/red]")
            if "not initialized" in str(e).lower():
                err_console.print(
                    "[dim]Run [bold]kt registry add <url>[/bold] to get started.[/dim]"
                )
            raise SystemExit(1) from None
        except FileExistsError as e:
            if _is_debug():
                raise
            err_console.print(f"[yellow]{e}[/yellow]")
            raise SystemExit(1) from None
        except ValueError as e:
            if _is_debug():
                raise
            err_console.print(f"[red]{e}[/red]")
            msg = str(e).lower()
            if "not installed" in msg:
                err_console.print(
                    "[dim]Run [bold]kt status[/bold] to see installed packages.[/dim]"
                )
            elif "not found in registry" in msg or "not found in any registry" in msg:
                err_console.print("[dim]Run [bold]kt search <term>[/bold] to find packages.[/dim]")
            raise SystemExit(1) from None
        except RuntimeError as e:
            if _is_debug():
                raise
            err_console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1) from None
        except OSError as e:
            if _is_debug():
                raise
            err_console.print(f"[red]I/O error: {e}[/red]")
            raise SystemExit(1) from None
        except KeyboardInterrupt:
            err_console.print("\n[dim]Interrupted.[/dim]")
            raise SystemExit(130) from None

    return wrapper


def _classification_icon(classification: str) -> str:
    if classification == "evergreen":
        return "\U0001f332"  # evergreen tree
    elif classification == "seasonal":
        return "\U0001f342"  # fallen leaf
    return ""


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option()
@click.option("--debug", "-d", is_flag=True, help="Show full tracebacks on error.")
def cli(debug):
    """Knowledge Tree - Crowdsourced knowledge management for AI agent context."""
    pass


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("registry_url", required=False, default=None)
@click.option("--branch", default="main", help="Registry branch (git only).")
@click.option("--name", default=None, help="Registry name (auto-derived from URL if omitted).")
@click.option(
    "--format",
    "tool_format",
    default=None,
    help="Tool format. Prompted if omitted.",
)
@click.option("--no-install", is_flag=True, help="Only register the source, skip install.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@_handle_error
def init(
    registry_url: str | None,
    branch: str,
    name: str | None,
    tool_format: str | None,
    no_install: bool,
    yes: bool,
):
    """Initialize a Knowledge Tree project.

    When REGISTRY_URL is provided, also adds the registry and installs all
    packages (same as kt registry add).
    """
    engine = _get_engine()

    if engine.knowledge_tree_dir.exists():
        raise FileExistsError(
            "Already initialized. Remove .knowledge-tree/ directory to re-initialize."
        )

    if registry_url is None:
        # Bare init — empty project
        engine.init(None)
        console.print("[green]Initialized Knowledge Tree.[/green]")
        console.print("  Empty project created (no registries).")
        console.print()
        console.print(
            "Run [bold]kt init <url>[/bold] or [bold]kt registry add <url>[/bold] to add a registry."
        )
        return

    # Prompt for tool format (before preview so we can show it)
    if not no_install and tool_format is None:
        tool_format = _prompt_tool_format(engine)

    if no_install or yes:
        # Non-interactive: go straight to add_registry
        label = name or registry_url
        with console.status(f"Initializing with registry '{label}'..."):
            result = engine.add_registry(
                registry_url,
                name=name,
                branch=branch,
                tool_format=tool_format,
                install_packages=not no_install,
            )
        if tool_format:
            engine.set_config("export_format", tool_format)
        console.print(f"[green]Initialized Knowledge Tree with registry '{result.name}'.[/green]")
        _print_registry_add_result(result, registry_url, no_install)
        return

    # Interactive: preview → confirm → execute
    label = name or registry_url
    with console.status(f"Fetching registry '{label}'..."):
        preview = engine.preview_registry(registry_url, name=name, branch=branch)

    selected = _confirm_registry_add(preview, tool_format or "")

    if selected is None:
        console.print("[dim]Cancelled.[/dim]")
        engine.remove_registry(preview.name, force=True)
        raise SystemExit(0)

    with console.status(f"Installing {len(selected)} packages..."):
        result = engine.add_registry(
            registry_url,
            name=name,
            branch=branch,
            tool_format=tool_format,
            install_packages=True,
            selected_packages=selected,
        )

    if tool_format:
        engine.set_config("export_format", tool_format)
    console.print(f"[green]Initialized Knowledge Tree with registry '{result.name}'.[/green]")
    _print_registry_add_result(result, registry_url, False)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("package")
@click.option("--from", "from_registry", default=None, help="Registry to install from.")
@click.option("--dry-run", is_flag=True, help="Show what would be installed without installing.")
@_handle_error
def add(package: str, from_registry: str | None, dry_run: bool):
    """Install a knowledge package and its ancestors."""
    engine = _get_engine()

    with console.status(f"{'Resolving' if dry_run else 'Installing'} {package}..."):
        result = engine.add_package(package, from_registry=from_registry, dry_run=dry_run)

    if dry_run:
        if result.installed:
            console.print("[bold]Would install:[/bold]")
            for name in result.installed:
                console.print(f"  [green]+[/green] {name}")
        if result.already_installed:
            for name in result.already_installed:
                console.print(f"  [dim]  {name} (already installed)[/dim]")
        if not result.installed:
            console.print("[dim]Nothing new to install.[/dim]")
        return

    if result.installed:
        for name in result.installed:
            console.print(f"  [green]+[/green] {name}")
    if result.already_installed:
        for name in result.already_installed:
            console.print(f"  [dim]  {name} (already installed)[/dim]")

    total = len(result.installed)
    if total:
        console.print(
            f"\n[green]Installed {total} package{'s' if total > 1 else ''} "
            f"from registry '{result.registry}'.[/green]"
        )
        if result.files_exported:
            console.print(f"[dim]{result.files_exported} files exported.[/dim]")
        elif result.installed:
            config = engine._load_config()
            if not config.export_format:
                console.print(
                    "[dim]No tool format configured — skipped export. "
                    "Run [bold]kt config set export_format <format>[/bold].[/dim]"
                )
    else:
        console.print("[dim]Nothing new to install.[/dim]")

    if result.warnings:
        for warn in result.warnings:
            console.print(f"  [yellow]⚠ {warn}[/yellow]")


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("package")
@_handle_error
def remove(package: str):
    """Remove an installed knowledge package."""
    engine = _get_engine()
    result = engine.remove_package(package)

    console.print(f"  [red]-[/red] {package}")

    if result.unexported:
        for fmt in result.unexported:
            console.print(f"  [dim]Cleaned up {fmt} export[/dim]")

    if result.children:
        console.print(
            f"\n[yellow]Warning:[/yellow] The following installed packages "
            f"are children of [bold]{package}[/bold]:"
        )
        for child in result.children:
            console.print(f"  - {child}")
        console.print("[dim]Consider removing them or re-adding this package.[/dim]")

    console.print(f"\n[green]Removed {package}.[/green]")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("query")
@_handle_error
def search(query: str):
    """Search for knowledge packages."""
    engine = _get_engine()
    results = engine.search(query)

    if not results:
        console.print(f"[dim]No packages match '{query}'.[/dim]")
        return

    table = Table(title=f"Search: {query}")
    table.add_column("Name", style="bold")
    table.add_column("Description")
    table.add_column("Type")
    table.add_column("Tags", style="dim")
    table.add_column("Registry", style="dim")
    table.add_column("Installed")

    for pkg in results:
        icon = _classification_icon(pkg.classification)
        installed = "[green]yes[/green]" if pkg.installed else "[dim]no[/dim]"
        table.add_row(
            pkg.name,
            pkg.description,
            f"{icon} {pkg.classification}",
            ", ".join(pkg.tags),
            pkg.registry,
            installed,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


@cli.command()
@_handle_error
def tree():
    """Show the knowledge package tree."""
    engine = _get_engine()
    data = engine.get_tree_data()

    rich_tree = Tree("\U0001f333 Knowledge Tree")

    def _add_nodes(parent_tree, nodes):
        for node in nodes:
            icon = _classification_icon(node.classification)
            status = " [green](installed)[/green]" if node.installed else ""
            label = f"{icon} [bold]{node.name}[/bold]{status}"
            if node.description:
                label += f" — {node.description}"
            branch = parent_tree.add(label)
            _add_nodes(branch, node.children)

    _add_nodes(rich_tree, data.roots)
    console.print(rich_tree)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("package", required=False, default=None)
@click.option("--format", "new_format", default=None, help="Switch tool format.")
@click.option("--switch-tool", is_flag=True, help="Interactively select tool format.")
@_handle_error
def update(package: str | None, new_format: str | None, switch_tool: bool):
    """Update registry and re-export packages.

    When PACKAGE is given, only that package is updated.
    Use --format or --switch-tool to change the export tool format.
    """
    engine = _get_engine()

    # Resolve format switch
    if switch_tool:
        new_format = _prompt_tool_format(engine)
    elif new_format:
        # Validate the format name
        valid_names = [name for name, _ in list_formats()]
        if new_format not in valid_names:
            err_console.print(
                f"[red]Unknown format: {new_format}[/red]\n"
                f"[dim]Available: {', '.join(valid_names)}[/dim]"
            )
            raise SystemExit(1)

    label = f"Updating {package}..." if package else "Updating..."
    with console.status(label):
        result = engine.update(package_name=package, new_format=new_format)

    # Format switch output
    if result.format_switched:
        old = result.old_format or "(none)"
        console.print(f"\n[green]Switched tool format: {old} → {result.new_format}[/green]")
        if result.files_re_exported:
            console.print(
                f"  Exported {result.files_re_exported} package(s) to {result.new_format}"
            )

    for reg_name, ref in result.refs.items():
        if ref == "local":
            console.print(f"[green]{reg_name}: Updated from local directory.[/green]")
        else:
            console.print(f"[green]{reg_name}: Updated to ref {ref}.[/green]")

    if result.updated_packages:
        console.print(f"  Updated: {', '.join(result.updated_packages)}")

    if result.failed_packages:
        console.print(f"\n[red]Failed to update:[/red] {', '.join(result.failed_packages)}")
        console.print("[dim]These packages were kept at their previous version.[/dim]")

    if result.new_evergreen:
        console.print(
            f"\n[yellow]New evergreen packages available:[/yellow] "
            f"{', '.join(result.new_evergreen)}"
        )
        console.print("[dim]Run [bold]kt add <package>[/bold] to install.[/dim]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--available", is_flag=True, help="Show available (not installed) packages.")
@click.option("--community", is_flag=True, help="Show community packages.")
@_handle_error
def status(available: bool, community: bool):
    """Show project status and packages."""
    engine = _get_engine()
    data = engine.get_status()

    # Section 1: Registries table
    if data.registries:
        reg_table = Table(title="Registries")
        reg_table.add_column("Name", style="bold")
        reg_table.add_column("Source")
        reg_table.add_column("Type")
        reg_table.add_column("Packages", justify="right")
        for reg in data.registries:
            reg_table.add_row(reg.name, reg.source, reg.type, str(reg.package_count))
        console.print(reg_table)

    # Section 2: Packages table
    results = engine.list_packages(available=available, community=community)
    if results:
        title = (
            "Community Packages"
            if community
            else ("Available Packages" if available else "Installed Packages")
        )
        pkg_table = Table(title=title)
        pkg_table.add_column("Name", style="bold")
        pkg_table.add_column("Description")
        pkg_table.add_column("Type")
        pkg_table.add_column("Tags", style="dim")
        pkg_table.add_column("Registry", style="dim")
        if not available and not community:
            pkg_table.add_column("Ref", style="dim")

        for pkg in results:
            icon = _classification_icon(pkg.classification)
            row = [
                pkg.name,
                pkg.description,
                f"{icon} {pkg.classification}",
                ", ".join(pkg.tags),
                pkg.registry,
            ]
            if not available and not community:
                row.append(pkg.ref)
            pkg_table.add_row(*row)
        console.print(pkg_table)
    else:
        if available:
            console.print("[dim]All packages are installed.[/dim]")
        elif community:
            console.print("[dim]No community packages found.[/dim]")
        else:
            console.print("[dim]No packages installed. Run [bold]kt add <package>[/bold].[/dim]")

    # Footer: summary stats
    parts = [f"{data.installed_count} installed, {data.available_count} available"]
    parts.append(f"{data.total_files} files, {data.total_lines} lines")
    if data.export_format:
        parts.append(f"Export: {data.export_format} ({data.exported_count} exported)")
    summary = " \u00b7 ".join(parts)
    console.print(f"\n[dim]{summary}[/dim]")


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("package")
@_handle_error
def info(package: str):
    """Show detailed information about a package."""
    engine = _get_engine()
    data = engine.get_info(package)

    icon = _classification_icon(data.classification)
    lines = [
        f"[bold]{data.name}[/bold] {icon} {data.classification}",
        f"{data.description}",
        "",
    ]

    if data.registry:
        lines.append(f"Registry: {data.registry}")
    if data.authors:
        lines.append(f"Authors: {', '.join(data.authors)}")
    if data.tags:
        lines.append(f"Tags: {', '.join(data.tags)}")
    if data.parent:
        lines.append(f"Parent: {data.parent}")
    if data.children:
        lines.append(f"Children: {', '.join(data.children)}")
    if data.ancestors:
        lines.append(f"Ancestors: {', '.join(data.ancestors)}")

    status_line = (
        f"[green]Installed[/green] (ref: {data.ref})"
        if data.installed
        else "[dim]Not installed[/dim]"
    )
    lines.append(f"\nStatus: {status_line}")

    if data.exported_to:
        lines.append(f"Exported to: {', '.join(data.exported_to)}")

    if data.files:
        lines.append("\nContent files:")
        for f in data.files:
            lines.append(f"  - {f.name} ({f.lines} lines)")

    console.print(Panel("\n".join(lines), border_style="blue"))


# ---------------------------------------------------------------------------
# author subgroup
# ---------------------------------------------------------------------------


@cli.group()
def author():
    """Registry authoring commands (validate, contribute, rebuild)."""
    pass


@author.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--all", "validate_all", is_flag=True, help="Validate all packages in directory.")
@_handle_error
def validate(path: Path, validate_all: bool):
    """Validate a knowledge package."""
    engine = _get_engine()

    if validate_all:
        # Validate all subdirectories as packages
        any_errors = False
        for pkg_dir in sorted(path.iterdir()):
            if not pkg_dir.is_dir():
                continue
            result = engine.validate_package(pkg_dir)
            if result.errors:
                console.print(f"[red]\u2717[/red] {pkg_dir.name}")
                for err in result.errors:
                    console.print(f"    [red]{err}[/red]")
                any_errors = True
            elif result.warnings:
                console.print(f"[yellow]![/yellow] {pkg_dir.name}")
                for warn in result.warnings:
                    console.print(f"    [yellow]{warn}[/yellow]")
            else:
                console.print(f"[green]\u2713[/green] {pkg_dir.name}")

        if any_errors:
            raise SystemExit(1)
    else:
        result = engine.validate_package(path)

        if result.errors:
            console.print(f"[red]Validation failed for {path.name}:[/red]")
            for err in result.errors:
                console.print(f"  [red]\u2717 {err}[/red]")
            raise SystemExit(1)

        if result.warnings:
            console.print(f"[yellow]Warnings for {path.name}:[/yellow]")
            for warn in result.warnings:
                console.print(f"  [yellow]! {warn}[/yellow]")

        console.print(f"[green]\u2713 {path.name} is valid.[/green]")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@cli.group()
def config():
    """Get or set project configuration."""


@config.command("get")
@click.argument("key")
@_handle_error
def config_get(key: str):
    """Get a configuration value."""
    engine = _get_engine()
    value = engine.get_config(key)
    if value:
        console.print(value)
    else:
        console.print("[dim](not set)[/dim]")


@config.command("set")
@click.argument("key")
@click.argument("value")
@_handle_error
def config_set(key: str, value: str):
    """Set a configuration value."""
    engine = _get_engine()
    engine.set_config(key, value)
    console.print(f"[green]Set {key} = {value}[/green]")


@config.command("list")
@_handle_error
def config_list():
    """List all configuration keys and their values."""
    engine = _get_engine()
    for key, description in sorted(engine._CONFIG_KEYS.items()):
        value = engine.get_config(key)
        display = value if value else "[dim](not set)[/dim]"
        console.print(f"  [bold]{key}[/bold] = {display}")
        console.print(f"    [dim]{description}[/dim]")


# ---------------------------------------------------------------------------
# tool format helpers
# ---------------------------------------------------------------------------


def _available_formats_str() -> str:
    return ", ".join(name for name, _ in list_formats())


def _prompt_tool_format(engine: KnowledgeTreeEngine) -> str:
    """Interactively prompt the user to select a tool format.

    Auto-detection is used to pre-select a default when possible.
    """
    formats = list_formats()
    detected = engine._detect_tool_format()

    # Find default index (1-based) if auto-detected
    default_idx: int | None = None
    for i, (name, _) in enumerate(formats, start=1):
        if name == detected:
            default_idx = i
            break

    console.print("\nWhich AI coding tool are you using?\n")
    for i, (_name, description) in enumerate(formats, start=1):
        label = f"{description} [dim](detected)[/dim]" if _name == detected else description
        console.print(f"  [bold][{i}][/bold] {label}")
    console.print()

    prompt_text = "Select"
    if default_idx is not None:
        choice = click.prompt(prompt_text, default=str(default_idx))
    else:
        choice = click.prompt(prompt_text)

    try:
        idx = int(choice)
        if 1 <= idx <= len(formats):
            selected = formats[idx - 1][0]
        else:
            raise ValueError
    except ValueError:
        # Try matching by name
        choice_lower = choice.lower().strip()
        matched = [name for name, _ in formats if name == choice_lower]
        if matched:
            selected = matched[0]
        else:
            err_console.print(f"[red]Invalid choice: {choice}[/red]")
            raise SystemExit(1) from None

    return selected


def _format_name_for_display(format_name: str) -> str:
    """Convert a format key like 'claude-code' to its display name like 'Claude Code'."""
    for name, description in list_formats():
        if name == format_name:
            return description
    return format_name


def _confirm_registry_add(
    preview: RegistryPreview,
    tool_format: str,
) -> list[str] | None:
    """Show an interactive confirmation screen for registry add.

    Returns list of selected package names, or ``None`` if the user cancels.
    """
    # Header panel
    console.print()
    console.print(
        Panel(
            f"[bold]{preview.name}[/bold]  ({preview.source_type})\n"
            f"Source: {preview.source}\n"
            f"Tool: [bold]{_format_name_for_display(tool_format)}[/bold]",
            title="Registry Preview",
            border_style="blue",
        )
    )

    # Packages table
    if preview.packages:
        table = Table(title=f"Packages ({len(preview.packages)})")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("Description")
        table.add_column("Type", style="dim")

        for i, pkg in enumerate(preview.packages, start=1):
            table.add_row(
                str(i),
                pkg.name,
                pkg.description,
                pkg.classification,
            )
        console.print(table)

    # Templates
    if preview.templates:
        console.print("\n[bold]Templates to create:[/bold]")
        for dest in preview.templates:
            console.print(f"  [green]+[/green] {dest}")
    if preview.templates_existing:
        for dest in preview.templates_existing:
            console.print(f"  [dim]  {dest} (already exists, skipped)[/dim]")

    # Confirmation prompt
    console.print()
    choice = click.prompt(
        "Proceed? [Y]es / [n]o / [s]elect packages",
        default="y",
        show_default=False,
    )
    choice = choice.strip().lower()

    if choice in ("n", "no"):
        return None

    if choice in ("s", "select"):
        return _select_packages(preview)

    # Default: install all
    return [pkg.name for pkg in preview.packages]


def _select_packages(preview: RegistryPreview) -> list[str] | None:
    """Interactive package selection. Returns selected names or ``None`` if cancelled."""
    selected = {pkg.name for pkg in preview.packages}  # all selected by default
    pkg_map = {p.name: p for p in preview.packages}

    console.print("\nEnter package numbers to toggle (comma-separated), or:")
    console.print(
        "  [bold]a[/bold] = select all  [bold]n[/bold] = select none  [bold]d[/bold] = done  [bold]q[/bold] = cancel"
    )

    while True:
        console.print()
        for i, pkg in enumerate(preview.packages, start=1):
            mark = "[green]x[/green]" if pkg.name in selected else " "
            console.print(f"  [{mark}] [bold]{i}[/bold]  {pkg.name} — {pkg.description}")

        console.print()
        response = click.prompt("Toggle", default="d").strip().lower()

        if response in ("q", "quit", "cancel"):
            return None
        if response in ("d", "done"):
            break
        if response in ("a", "all"):
            selected = {pkg.name for pkg in preview.packages}
            continue
        if response in ("n", "none"):
            selected.clear()
            continue

        # Parse comma-separated numbers
        try:
            nums = [int(x.strip()) for x in response.split(",")]
            for num in nums:
                if 1 <= num <= len(preview.packages):
                    name = preview.packages[num - 1].name
                    if name in selected:
                        selected.discard(name)
                    else:
                        selected.add(name)
                else:
                    console.print(f"[red]Invalid number: {num}[/red]")
        except ValueError:
            console.print("[red]Enter numbers separated by commas.[/red]")

    if not selected:
        console.print("[yellow]No packages selected.[/yellow]")
        return []

    # Auto-add missing ancestors with warning
    for name in list(selected):
        pkg = pkg_map[name]
        current = pkg.parent
        while current and current in pkg_map:
            if current not in selected:
                console.print(f"[yellow]Adding '{current}' (ancestor of '{name}')[/yellow]")
                selected.add(current)
            current = pkg_map[current].parent

    return sorted(selected)


def _print_registry_add_result(result: RegistryAddResult, source: str, no_install: bool) -> None:
    """Print the output of a registry add operation."""
    console.print(f"  Source: {source}")

    if no_install:
        console.print(f"  Available packages: {len(result.available_packages)}")
        return

    if result.packages_installed:
        console.print("\n[bold]Packages installed:[/bold]")
        for pkg in result.packages_installed:
            console.print(f"  [green]+[/green] {pkg}")

    if result.packages_skipped:
        for pkg in result.packages_skipped:
            console.print(f"  [dim]  {pkg} (already installed)[/dim]")

    if result.commands_installed:
        console.print("\n[bold]Commands:[/bold]")
        for cmd in result.commands_installed:
            console.print(f"  [green]/[/green] {cmd}")

    if result.templates_instantiated:
        console.print("\n[bold]Templates created:[/bold]")
        for path in result.templates_instantiated:
            console.print(f"  [green]+[/green] {path}")

    if result.templates_skipped:
        for path in result.templates_skipped:
            console.print(f"  [dim]  {path} (already exists)[/dim]")

    if result.files_exported:
        console.print(f"\n[dim]{result.files_exported} files exported.[/dim]")

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/yellow]")
        for warn in result.warnings:
            console.print(f"  [yellow]\u26a0 {warn}[/yellow]")


@author.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--name", required=True, help="Package name for the contribution.")
@click.option("--to", "to_existing", default=None, help="Contribute as child of existing package.")
@click.option("--from", "from_registry", default=None, help="Registry to contribute to.")
@_handle_error
def contribute(file: Path, name: str, to_existing: str | None, from_registry: str | None):
    """Contribute a knowledge file to the community."""
    engine = _get_engine()

    with console.status("Preparing contribution..."):
        mr_url = engine.contribute(
            file, name, to_existing=to_existing, registry_name=from_registry
        )

    console.print("[green]Contribution prepared![/green]")
    console.print("\nOpen this URL to create a merge/pull request:")
    console.print(f"  [bold blue]{mr_url}[/bold blue]")


# ---------------------------------------------------------------------------
# registry subcommands
# ---------------------------------------------------------------------------


@cli.group()
def registry():
    """Registry management commands."""
    pass


@registry.command(name="add")
@click.argument("source")
@click.option("--name", default=None, help="Registry name (auto-derived from URL if omitted).")
@click.option("--branch", default="main", help="Branch (git only).")
@click.option(
    "--format",
    "tool_format",
    default=None,
    help=f"Tool format ({_available_formats_str()}). Prompted if omitted.",
)
@click.option("--no-install", is_flag=True, help="Only register the source, skip install.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@_handle_error
def registry_add(
    source: str,
    name: str | None,
    branch: str,
    tool_format: str | None,
    no_install: bool,
    yes: bool,
):
    """Add a registry and install all its packages.

    Initializes the project if needed, installs all packages, exports them
    to your tool's format, and applies registry templates.
    """
    engine = _get_engine()

    # Resolve tool format
    if not no_install and tool_format is None:
        config = engine._load_config() if engine.knowledge_tree_dir.exists() else None
        existing_format = config.export_format if config else ""
        if existing_format:
            tool_format = existing_format
        else:
            tool_format = _prompt_tool_format(engine)
            engine.set_config("export_format", tool_format)

    if no_install or yes:
        # Non-interactive path
        label = name or source
        with console.status(f"Adding registry '{label}'..."):
            result = engine.add_registry(
                source,
                name=name,
                branch=branch,
                tool_format=tool_format,
                install_packages=not no_install,
            )
        console.print(f"[green]Added registry '{result.name}'.[/green]")
        _print_registry_add_result(result, source, no_install)
        return

    # Interactive: preview → confirm → execute
    # Track whether registry existed before preview (for cancellation cleanup)
    config = engine._load_config() if engine.knowledge_tree_dir.exists() else None
    was_new = config is None or not any(r.source == source for r in config.registries)

    label = name or source
    with console.status(f"Fetching registry '{label}'..."):
        preview = engine.preview_registry(source, name=name, branch=branch)

    selected = _confirm_registry_add(preview, tool_format or "")

    if selected is None:
        console.print("[dim]Cancelled.[/dim]")
        if was_new:
            engine.remove_registry(preview.name, force=True)
        raise SystemExit(0)

    with console.status(f"Installing {len(selected)} packages..."):
        result = engine.add_registry(
            source,
            name=name,
            branch=branch,
            tool_format=tool_format,
            install_packages=True,
            selected_packages=selected,
        )

    console.print(f"[green]Added registry '{result.name}'.[/green]")
    _print_registry_add_result(result, source, False)


@registry.command(name="remove")
@click.argument("name")
@click.option("--force", is_flag=True, help="Remove even if packages are installed from it.")
@_handle_error
def registry_remove(name: str, force: bool):
    """Remove a registry source."""
    engine = _get_engine()
    engine.remove_registry(name, force=force)
    console.print(f"[green]Removed registry '{name}'.[/green]")


@author.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@_handle_error
def rebuild(path: Path):
    """Rebuild registry.yaml from packages directory."""
    engine = _get_engine()
    count = engine.registry_rebuild(path)
    console.print(f"[green]Rebuilt registry with {count} packages.[/green]")


# ---------------------------------------------------------------------------
# completion
# ---------------------------------------------------------------------------

_SHELL_CLASSES = {
    "bash": "click.shell_completion.BashComplete",
    "zsh": "click.shell_completion.ZshComplete",
    "fish": "click.shell_completion.FishComplete",
}


@cli.command()
@click.argument("shell", type=click.Choice(sorted(_SHELL_CLASSES)))
def completion(shell: str):
    """Output shell completion script.

    Add to your shell profile to enable tab completion:

    \b
      bash: eval "$(kt completion bash)"
      zsh:  eval "$(kt completion zsh)"
      fish: kt completion fish | source
    """
    import importlib

    module_path, class_name = _SHELL_CLASSES[shell].rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    comp = cls(cli, {}, "kt", "_KT_COMPLETE")
    click.echo(comp.source())
