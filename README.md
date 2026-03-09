# Knowledge Tree

[![CI](https://github.com/kBisla9/knowledge-tree/actions/workflows/ci.yml/badge.svg)](https://github.com/kBisla9/knowledge-tree/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/kBisla9/knowledge-tree/branch/main/graph/badge.svg)](https://codecov.io/gh/kBisla9/knowledge-tree)
[![PyPI](https://img.shields.io/pypi/v/knowledge-tree)](https://pypi.org/project/knowledge-tree/)
[![Python](https://img.shields.io/pypi/pyversions/knowledge-tree)](https://pypi.org/project/knowledge-tree/)
[![License](https://img.shields.io/pypi/l/knowledge-tree)](LICENSE)

**npm for AI agent knowledge** — crowdsourced Markdown packages that give your AI coding agents the context they need.

## What is Knowledge Tree?

AI coding agents (Cursor, Claude Code, Copilot, etc.) are only as good as the context they have. Teams repeatedly explain the same conventions, patterns, and gotchas to their AI tools, project after project.

Knowledge Tree is a CLI tool (`kt`) that manages curated Markdown knowledge packages. Think `npm install`, but for knowledge. You point it at a registry — a git repo, a local directory, or an archive file — install what you need, and the content is automatically exported to your AI tool's native format (Claude Code skills, Roo Code rules) where agents can read it.

Registries are crowdsourced — teams curate packages for coding conventions, API patterns, framework guides, and more. Packages have dependencies, classification (evergreen vs seasonal), and a promotion pipeline from community contributions to curated packages.

## Quick Start

```bash
# 1. Install
pip install knowledge-tree

# 2. Initialize from a registry (git repo, local directory, or archive)
kt init https://github.com/your-org/knowledge-registry.git
kt init ./my-registry/            # local directory
kt init ./registry-export.tar.gz  # archive file (.tar.gz, .tgz, .zip)

# 3. Add more registries (optional — multi-registry support)
kt registry add https://github.com/your-org/internal-rules.git --name internal

# 4. Browse available packages
kt status --available

# 5. Install a package (dependencies auto-install)
kt add api-patterns
kt add company-standards --from internal  # from a specific registry

# 6. See what you have
kt tree
```

```
🌳 Knowledge Tree
├── 🌲 base (installed) — Universal coding conventions
│   └── 🌲 git-conventions — Git commit message standards
└── 🍂 api-patterns (installed) — REST API patterns and auth
```

Packages are automatically exported to your AI tool's native format (Claude Code, Roo Code) when a format is configured. Share the registry URL with your team — each member runs `kt init <url>` to get the same packages.

## Key Concepts

**Packages** — Named bundles of Markdown files with metadata (`package.yaml`). Each package lives in a directory with a name like `base`, `git-conventions`, or `api-patterns`. Packages can contain **knowledge** (context for AI agents) and **commands** (user-invocable slash commands like `/do-thing`).

**Registries** — Collections of packages with a `registry.yaml` index, a `packages/` directory (curated), and a `community/` directory (contributions). A registry can be a git repo (remote or local), a plain directory, or an archive file (`.tar.gz`, `.tgz`, `.zip`).

**Evergreen vs Seasonal** — Packages are classified as *evergreen* (stable conventions, long-term relevance) or *seasonal* (experimental, trend-based, may change). `kt update` notifies you about new evergreen packages.

**Relationships** — Three types:
- `parent` — organizational grouping (shown in `kt tree`)
- `depends_on` — functional dependency (auto-installed with `kt add`)
- `suggests` — optional recommendations (shown in `kt info`)

**Multi-Registry** — Projects can use multiple registries simultaneously. Each registry gets a name (default: "default") and all storage is namespaced by registry. Use `kt registry add/remove` to manage registries and `--from <registry>` on `kt add` when a package exists in multiple registries.

**Auto-Export** — When a tool format is configured (during `kt init` or via `kt config set export_format <format>`), packages are automatically exported on install and re-exported on update. Supported formats:
- `claude-code` — generates `.claude/skills/<registry>/<package>/SKILL.md` with YAML frontmatter
- `roo-code` — generates `.roo/rules/kt-<registry>-<package>-<nn>-<file>.md` with managed-by headers

Use `kt update --format <name>` or `kt update --switch-tool` to change formats (automatically unexports old format and re-exports in new format).

**Zero-Clutter Storage** — All KT state lives in a single `.knowledge-tree/` directory (config at `.knowledge-tree/kt.yaml`, registry caches at `.knowledge-tree/registries/<name>/`). Every directory KT creates gets its own `.gitignore` — nothing is committed to your repo, and your project's `.gitignore` is never modified.

## Commands

### Core Commands

| Command | Description |
|---------|-------------|
| `kt init [<url>]` | Initialize project; with URL, also adds registry and installs all packages |
| `kt add <package> [--from <registry>]` | Install a package and its dependencies (auto-exports) |
| `kt remove <package>` | Remove a package and clean up exports (warns about dependents) |
| `kt search <query>` | Search by name, description, or tags |
| `kt tree` | Show hierarchical package tree |
| `kt update [<package>]` | Pull latest, update installed packages (auto-re-exports) |
| `kt update --format <name>` | Switch export format (unexports old, re-exports new) |
| `kt update --switch-tool` | Interactively select a new export format |
| `kt status [--available] [--community]` | Show registries, packages, and project stats |
| `kt info <package>` | Detailed package information |

### Registry Management

| Command | Description |
|---------|-------------|
| `kt registry add <source> [--name <n>]` | Add a new registry (installs all packages, exports, applies templates) |
| `kt registry remove <name> [--force]` | Remove a registry (`--force` if packages are installed from it) |

### Authoring Commands

| Command | Description |
|---------|-------------|
| `kt author validate <path> [--all]` | Validate package structure |
| `kt author contribute <file> --name <n>` | Contribute to community (git registries only) |
| `kt author rebuild <path>` | Rebuild `registry.yaml` from packages directory |

### Configuration

| Command | Description |
|---------|-------------|
| `kt config get <key>` | Get a configuration value |
| `kt config set <key> <value>` | Set a configuration value |
| `kt config list` | List all configuration keys and values |
| `kt completion <shell>` | Output shell completion script (bash/zsh/fish) |

Run `kt --help` or `kt <command> --help` for full options.

## How It Works

**Initialization** — `kt init <source>` detects the source type automatically and caches the registry in `.knowledge-tree/registries/<name>/`:
- **Git repos** — shallow-cloned; tracks commit refs
- **Local directories** — copied into the cache
- **Archives** — extracted (handles root-level and nested layouts, with path-traversal protection for tar files)

It creates `.knowledge-tree/kt.yaml` (config), installs all packages from the registry, exports them to your chosen tool format, and applies any registry templates. Use `--name` to set a custom registry name (default: "default"). Use `--no-install` to register the source without installing packages.

**Multi-registry** — Add more registries with `kt registry add <source> --name <name>`. All storage is namespaced by registry name under `.knowledge-tree/registries/<name>/`. If a package name exists in multiple registries, use `kt add <package> --from <registry>` to disambiguate.

**Installing packages** — `kt add` resolves the full dependency chain and auto-exports content directly from the registry cache to your configured tool format (e.g., `.claude/skills/` for Claude Code, `.roo/rules/` for Roo Code). There is no intermediate step — exporters read from cache and write to tool directories.

**Updating** — `kt update` refreshes the cache from all registries (git pull, directory re-copy, or archive re-extraction), re-exports all installed packages, and alerts you to new evergreen packages you haven't installed yet.

**Contributing** — `kt author contribute` is only available for git-backed registries. It creates a branch and prepares a merge request URL.

## Creating a Registry

A registry is a directory (git repo, plain folder, or archive) with this structure:

```
your-registry/
  registry.yaml
  packages/
    base/
      package.yaml
      safe-deletion.md
      file-management.md
    api-patterns/
      package.yaml
      rest-conventions.md
      authentication.md
  community/
  CONTRIBUTING.md
```

Each package needs a `package.yaml`:

```yaml
name: base
description: Universal coding conventions and safe practices
authors:
  - Your Team
classification: evergreen
tags:
  - core
  - conventions
content:
  - safe-deletion.md
  - file-management.md
```

See [`workspace/sample-registry/`](workspace/sample-registry/) for a complete example. Use `kt author validate` to check package structure and `kt author rebuild` to regenerate the index.

For detailed guidance on registry creation including templates, content types, and advanced patterns like one-shot wire commands, see the Registry Authoring Guide in the project documentation.

To distribute a registry without git, you can tar/zip the directory and share the archive file — `kt init registry.tar.gz` will extract it automatically.

## Contributing

- **Knowledge packages** — See `CONTRIBUTING.md` in your registry for contribution guidelines
- **The `kt` tool** — Fork, branch, PR on [GitHub](https://github.com/kBisla9/knowledge-tree)
- Test suite: 478 tests using real git repos (no mocking), 91% coverage

## Development

```bash
git clone https://github.com/kBisla9/knowledge-tree.git
cd knowledge-tree
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

Requires Python 3.10+.

## License

MIT — see [LICENSE](LICENSE).
