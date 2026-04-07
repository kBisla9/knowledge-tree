# Knowledge Tree — Feature Reference

**Version**: 0.3.0
**Last updated**: 2026-03-26

Definitive reference for all Knowledge Tree features — every command, option, model, and behavior.

---

## 1. Overview

Knowledge Tree (`kt`) is a CLI tool that manages curated Markdown knowledge packages for AI coding agents. You point it at a registry (git repo, local directory, or archive file), select packages, and the content is exported directly to tool-specific directories (`.claude/skills/`, `.roo/rules/`) where AI agents read it.

**Core principles:**
- Registries are crowdsourced — teams curate packages, community members contribute
- Strict tree structure — `parent` is the sole relationship; the tree IS the dependency graph
- Auto-export — install a package and it immediately appears in your AI tool
- Zero-clutter — all state in `.knowledge-tree/`, everything gitignored via per-directory `.gitignore` files, your repo's `.gitignore` is never modified

---

## 2. Installation & Setup

```bash
pip install knowledge-tree    # PyPI
brew install kBisla9/tap/knowledge-tree  # Homebrew
```

Requires Python 3.10+. The CLI is available as both `kt` and `knowledge-tree`.

### Project Initialization

```bash
kt init [--format FORMAT] [--yes/-y]
```

Creates the `.knowledge-tree/` directory, sets the target AI export format (e.g., `claude-code`), and explicitly exports built-in commands and skills (like `/kt-propose`) into the tool's workspace. It is idempotent and safe to run again.

| Option | Description |
|--------|-------------|
| `--format FORMAT` | Export format: `claude-code` or `roo-code` (prompted interactively if omitted) |
| `--yes` / `-y` | Skip interactive prompt (requires `--format` to be provided) |

> **Note**: It is **not strictly necessary** to run `kt init` first. If you skip this and jump straight to `kt registry add <source>`, Knowledge Tree will auto-initialize the project and export the built-in tooling for you behind the scenes.

---

## 3. Registry Management

### `kt registry add <source>`

Add a registry and install packages. This is the primary entry point for new users.

```
kt registry add <source> [--name NAME] [--branch BRANCH] [--format FORMAT] [--no-install] [--yes/-y]
```

| Option | Description |
|--------|-------------|
| `<source>` | Git URL, local directory path, or archive file (.tar.gz, .tgz, .zip) |
| `--name NAME` | Display name for the registry (auto-derived from URL if omitted) |
| `--branch BRANCH` | Git branch (default: `main`) |
| `--format FORMAT` | Export format: `claude-code` or `roo-code` (prompted interactively if omitted) |
| `--no-install` | Register the source only, skip package installation |
| `--yes` / `-y` | Skip interactive confirmation (for CI/scripting) |

**What happens on `kt registry add`:**
1. Auto-initializes `.knowledge-tree/` if this is the first registry
2. Detects source type (git / local directory / archive)
3. Clones/copies/extracts to `.knowledge-tree/cache/<name>/`
4. Validates registry ID (32-char hex UUID, no collisions with existing registries)
5. Shows interactive preview: registry info + package tree with checkboxes
6. User selects packages via interactive tree
7. Installs selected packages (records in `kt.yaml`)
8. Exports to configured tool format
9. Instantiates registry-level templates (if any declared in `registry.yaml`)
10. **Rollback**: if auto-init happened and the add fails, `.knowledge-tree/` is cleaned up (best-effort)

**Interactive package selection:**
After preview, users see a numbered tree of all packages with checkboxes (all selected by default).
- Toggling a child ON auto-selects all its ancestors (since they're required dependencies)
- With `--yes`/`-y`, all packages are installed without prompting

**Source type detection:**
- URLs are recognized as **git** resources
- Paths ending in archive extensions (.tar.gz, .zip, etc.) are recognized as **archive** resources
- Local directories are treated depending on the presence of a `.git` folder

**Archive root detection:** When extracting archives, KT looks for `registry.yaml` or `packages/` at the archive root. If not found, it checks one level deep for a single top-level directory containing the registry (common when GitHub generates tarballs with a wrapper directory).

### `kt registry remove <name>`

Remove a registry source.

```
kt registry remove <name> [--force]
```

| Option | Description |
|--------|-------------|
| `<name>` | Registry display name |
| `--force` | Remove even if packages are installed (also removes those packages and their exports) |

Without `--force`, the command blocks if any packages from this registry are installed.

---

## 4. Package Management

### `kt add <package>`

Install a knowledge package and its ancestor chain.

```
kt add <package> [--from REGISTRY] [--dry-run]
```

| Option | Description |
|--------|-------------|
| `<package>` | Package name |
| `--from REGISTRY` | Registry to install from (required if package exists in multiple registries) |
| `--dry-run` | Show what would be installed without installing |

**Behaviors:**
- Resolves the full ancestor chain via `parent` links (root → ... → parent → self)
- Installs all ancestors that aren't already installed
- Auto-exports if an export format is configured (respects existing user files — does NOT force-overwrite)
- If the export format isn't set yet, it's auto-persisted to config on first export
- Fuzzy matching: if the package name isn't found, suggests similar names ("Did you mean: base?")

### `kt remove <package>`

Remove an installed package.

```
kt remove <package>
```

**Behaviors:**
- Auto-unexports from all configured formats (best-effort)
- Warns about installed child packages that depend on this one (does NOT auto-remove children)
- Fuzzy matching on package name if not found

### `kt update [PACKAGE]`

Update registries and re-export packages.

```
kt update [PACKAGE] [--format FORMAT] [--switch-tool]
```

| Option | Description |
|--------|-------------|
| `[PACKAGE]` | Specific package to update (updates all if omitted) |
| `--format FORMAT` | Switch to a new export format (unexports old, re-exports new) |
| `--switch-tool` | Interactively select a new export format |

**What happens on `kt update`:**
1. Nukes registry cache and re-fetches (full clone for git, re-copy for local, re-extract for archive)
2. Updates package refs in `kt.yaml`
3. Re-exports all installed packages with `force=True` (overwrites local modifications)
4. Reports new evergreen packages that became available since last update
5. Partial failure resilience: if one package fails to update, continues with the rest

**Format switching** (`--format` or `--switch-tool`):
1. Unexports all packages from old format
2. Updates `export_format` in config
3. Re-exports all packages in new format

---

## 5. Export System

Exports transform knowledge packages into the native format of the target AI tool. Export is **automatic** — triggered by `kt add`, `kt update`, and `kt registry add`.

### Supported Formats

#### `claude-code`

Exports to `.claude/skills/<registry>/<package>/SKILL.md`.

- **Single-file export**: one `SKILL.md` per package with YAML frontmatter + all content files inlined in the body
- Frontmatter fields: `name`, `description`, `user-invocable`, `sources`
- Knowledge/skills packages: `user-invocable: false` (loaded by the agent automatically)
- Commands: exported separately — see [Command Export](#command-export) below

#### `roo-code`

Exports to `.roo/` with content routed by type:

| Content type | Output location | Format |
|-------------|----------------|--------|
| knowledge | `.roo/rules/kt-<registry>-<package>-<nn>-<stem>.md` | Numbered rule files (always loaded) |
| skills | `.roo/skills/<stem>/SKILL.md` | Skill directory with frontmatter description (on-demand) |
| commands | `.roo/commands/<name>.md` | Command file |

### Command Export

Commands are handled differently from knowledge/skills content. They are discovered from:
1. The `commands` list in `package.yaml` (explicit command declarations)
2. Content files in packages with `content_type: commands`

**Claude Code command export:**
- Each command gets its own top-level directory: `.claude/skills/<command-name>/SKILL.md`
- NOT nested under registry/package — commands are user-facing, so they live at the top level
- Frontmatter: `user-invocable: true` (appears as a slash command the user can invoke)

**Roo Code command export:**
- Commands export to `.roo/commands/<name>.md`

### Content Type Resolution

Each content file's effective type is resolved in priority order:
1. **Per-file `export_hints`**: declared inline in the `content` list of `package.yaml` (highest priority)
2. **Package-level `export_hints`**: declared at the top level of `package.yaml`
3. **Package `content_type` field**: the package-wide default
4. **Fallback**: `knowledge`

Example `package.yaml` showing all levels:

```yaml
name: my-package
content_type: knowledge          # Package-level default
export_hints:
  claude-code: skills            # Package-level override for Claude Code
content:
  - file: setup-guide.md
    export_hints:
      claude-code: commands      # Per-file override (highest priority)
  - general-rules.md             # Uses package-level default
```

### Managed Markers

Exported files contain HTML comment markers that identify them as KT-managed. These markers are used for conflict detection during export:
- **Marker present**: file was written by KT, safe to overwrite
- **Marker absent**: file was user-created or user-modified, skipped (unless `force=True`)

On `kt add`: exports with `force=False` — respects user-created files.
On `kt update`: exports with `force=True` — overwrites everything, including locally modified files.

### Source Tracking

Exported files include source tracking metadata that maps inlined content back to its original source files. This enables `/kt-propose` to detect which source files were modified and reverse-map changes from exports back to registry source files.

**Two layers of tracking:**

1. **Frontmatter `sources` list** — ordered list of original filenames in the YAML frontmatter:

   ```yaml
   ---
   name: base
   description: "Universal coding conventions"
   sources:
     - file-management.md
     - safe-deletion.md
   ---
   ```

2. **Inline source tracking markers** — HTML comments placed around inlined file content indicating its source file origin.

**Format-specific details:**

| Format | Frontmatter `sources` | Inline markers |
|--------|----------------------|----------------|
| Claude Code | In SKILL.md YAML frontmatter | Before each section in SKILL.md body |
| Roo Code (rules) | N/A (one file per source) | Second line of each rule file |
| Roo Code (skills) | In SKILL.md YAML frontmatter | Before each section in SKILL.md body |
| Roo Code (commands) | N/A (one file per command) | After managed comment line |

**Fallback behavior**: If an exported file has no source markers (e.g., exported before v0.3.0), `/kt-propose` falls back to whole-file comparison for single-source packages and asks the user to `kt update` for multi-source packages.

### Auto-Export Behavior

| Operation | Export behavior | Force? |
|-----------|----------------|--------|
| `kt add` | Exports newly installed packages | No (skips user-created files) |
| `kt update` | Re-exports all updated packages | Yes (overwrites everything) |
| `kt registry add` | Exports all selected packages | No |
| `kt update --format` | Unexports old format, re-exports all in new format | Yes |

### Gitignore Handling

KT never modifies the project's `.gitignore`. Instead, it creates per-directory `.gitignore` files containing `*` in every directory it manages:
- `.knowledge-tree/.gitignore`
- `.claude/.gitignore` (created on first Claude Code export)
- `.roo/.gitignore` (created on first Roo Code export)
- Template output directories (if templates create new directories)

---

## 6. Status & Discovery

### `kt status`

Unified dashboard showing project state.

```
kt status [--available] [--community]
```

| Flag | Description |
|------|-------------|
| (none) | Show registries + installed packages |
| `--available` | Also show packages that are available but not installed |
| `--community` | Also show community packages |

**Output includes:**
- Registries table (name, source, type, package count)
- Packages table (name, description, type, tags, registry)
- Summary footer (installed count, available count, total files, total lines, export format)

### `kt tree`

Show the hierarchical package tree.

```
kt tree
```

Displays all packages organized by parent/child relationships with icons:
- Tree icons for evergreen packages, leaf icons for seasonal
- Installation status markers
- Package descriptions

### `kt info <package>`

Detailed information about a specific package.

```
kt info <package>
```

**Output includes:** name, classification, description, registry, authors, tags, parent, children, ancestors, installation status (with pinned ref), export formats, content files (with line counts), and suggested packages.

### `kt search <query>`

Search packages by name, description, or tags.

```
kt search <query>
```

Returns a scored results table across all registries. Matches against package name, description, and tags.

### Fuzzy Matching

When a package or registry name isn't found, KT uses fuzzy matching algorithms to suggest similar names. This applies to `kt add`, `kt remove`, `kt info`, and `kt search`.

---

## 7. Registry Authoring

Commands under `kt author` are for registry creators, not end-users.

### `kt author validate <path>`

Validate package or registry structure.

```
kt author validate <path> [--all]
```

| Option | Description |
|--------|-------------|
| `<path>` | Path to a package directory |
| `--all` | Validate all packages in the directory |

**Validates:**
- Required fields: `name`, `description`, `authors`
- Name format: lowercase kebab-case
- Classification values: `evergreen` or `seasonal`
- Content type values: `knowledge`, `skills`, or `commands`
- Tree structure: no circular `parent` references
- Export hints: valid tool names and content types
- Content files: listed files exist on disk

### `kt author rebuild <path>`

Rebuild `registry.yaml` from the packages directory.

```
kt author rebuild <path>
```

Scans `packages/` subdirectories, reads each `package.yaml`, and regenerates `registry.yaml`. Preserves existing registry `id` and `templates` fields. Auto-generates a UUID if `id` is missing.

**Known limitation:** If one package has corrupted YAML, the entire rebuild aborts (no per-package skip).

### `kt author contribute <file>`

Contribute a knowledge file to a registry's community directory.

```
kt author contribute <file> --name NAME [--to PARENT] [--from REGISTRY]
```

| Option | Description |
|--------|-------------|
| `<file>` | Path to Markdown file to contribute |
| `--name NAME` | Package name for the contribution (required) |
| `--to PARENT` | Contribute as child of existing package |
| `--from REGISTRY` | Target registry (uses first git registry if omitted) |

**What happens:**
1. Validates the target is a git-based registry (local/archive registries don't support contributions)
2. Creates a `contribute/<name>` branch in the registry cache (already a full clone, push-ready)
3. Copies file to `community/<name>/` (or `community/<parent>/<name>/` if `--to` is used)
4. Generates `package.yaml` with `status: pending`, `classification: seasonal`
5. Commits and pushes the branch
6. Returns a merge/pull request URL (auto-detects GitHub/GitLab/Bitbucket from remote URL)

**Scope**: This command is for contributing **new community packages** only. It does not support proposing changes to existing curated packages. For modifying existing packages, use `/kt-propose`.

### `/kt-propose` — Propose Changes to Existing Packages

A built-in slash command that detects local modifications to exported knowledge files and proposes them back to the upstream registry. Unlike `kt author contribute` (which creates new community packages), `/kt-propose` modifies existing curated packages.

**Invocation:** Type `/kt-propose` in your AI agent (Claude Code or Roo Code). The agent executes the instructions — the agent IS the interactive UI.

> **Important**: Run `/kt-propose` BEFORE `kt update`. The `kt update` command overwrites local modifications.

**7-phase workflow:**

1. **Read config** — Parse `.knowledge-tree/kt.yaml` to find registries, packages, and export format
2. **Map to cache** — For each installed package, locate its cache source directory via `registry.yaml` paths
3. **Detect changes** — Parse exported files using source tracking markers to split inlined content back into individual source files, then diff each against the original in the registry cache
4. **Present changes** — Group by registry and package, show modification summaries
5. **User selection** — All changes pre-selected; user can deselect, view diffs, or proceed
6. **Apply changes** — Per registry type:
   - **Git**: create branch (`propose/<packages>`), commit, push, generate PR URL (GitHub/GitLab/Bitbucket)
   - **Local directory**: write changes directly to source files
   - **Archive**: not supported (no upstream to push to)
7. **Report** — Summary with PR URLs (git) or confirmation of direct writes (local)

**Git registry flow details:**
- Branch naming: `propose/<pkg1>-<pkg2>-<pkg3>` (1–3 packages) or `propose/updates-<YYYY-MM-DD>` (4+)
- Uses the full clone in `.knowledge-tree/cache/` (push-ready, no unshallow needed)
- Auto-detects hosting provider from remote URL for PR link generation
- If push fails (no write access), the branch is preserved locally for manual push

**Local directory flow:**
- Changes are written directly to the source directory — immediate, no branching or review gate
- New files are added to `package.yaml`'s content list automatically

### One-Shot Wire Commands

A registry authoring pattern for delivering complex integrations. A command-type package ships a Markdown file containing step-by-step instructions that an AI agent executes once to set up an integration (creating files, modifying configs, etc.).

The pattern:
1. Package has `content_type: commands` and declares a command (e.g., `/setup-tool`)
2. The command's Markdown contains detailed file-creation and configuration instructions
3. User installs the package, runs the slash command, agent follows the instructions
4. The command file can be removed after execution (one-shot)

See the sample registry at `workspace/sample-registry/` for structure examples.

### Community Directory

Registries use a two-tier structure:
- `packages/` — curated packages maintained by registry authors
- `community/` — append-only directory for user contributions (via `kt author contribute`)

Community packages have `status: pending` and can be promoted to curated packages by registry maintainers (setting `status: promoted`, `promoted_to`, `promoted_date`).

---

## 8. Configuration & Environment

### `kt config get <key>`

Get a configuration value. Returns the value or "(not set)".

### `kt config set <key> <value>`

Set a configuration value.

### `kt config list`

List all known configuration keys with descriptions and current values.

**Known config keys:**

| Key | Description | Values |
|-----|-------------|--------|
| `export_format` | Default tool format for auto-export | `claude-code`, `roo-code` |

### `kt completion <shell>`

Output shell completion script.

```bash
eval "$(kt completion bash)"     # Bash
eval "$(kt completion zsh)"      # Zsh
kt completion fish | source      # Fish
```

### Global Options

| Flag | Description |
|------|-------------|
| `--version` | Show version (reads from installed package metadata) |
| `--debug` / `-d` | Show full tracebacks on error |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `KT_DEBUG` | Set to any value to enable debug mode (equivalent to `--debug` flag) |

### Auto-Format Detection

If no export format is configured but `.claude/` or `.roo/` directories exist in the project, KT auto-detects the tool format from these directories. This detection is used as a hint during `kt registry add`.

---

## 9. Package Model

A package is a named directory inside `packages/` (or `community/`) containing a `package.yaml` and content files (Markdown).

### `package.yaml` Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Lowercase kebab-case identifier (must match directory name) |
| `description` | Yes | One-line description |
| `authors` | Yes | List of author names |
| `classification` | No | `evergreen` or `seasonal` (default: `seasonal`) |
| `parent` | No | Name of parent package (must be in the same registry) |
| `suggests` | No | List of recommended related packages (informational only, shown in `kt info`) |
| `tags` | No | List of tags for search |
| `audience` | No | Target audience description |
| `content` | No | Ordered list of content files — see [Content List Format](#content-list-format) |
| `content_type` | No | Package-wide default: `knowledge`, `skills`, or `commands` (default: `knowledge`) |
| `export_hints` | No | Package-level per-tool type overrides (e.g., `claude-code: skills`) |
| `commands` | No | List of command declarations — see [Commands List Format](#commands-list-format) |
| `modes` | No | List of agent mode persona declarations |
| `status` | No | `pending`, `promoted`, or `archived` |
| `promoted_to` | No | Name of the curated package this was promoted to |
| `promoted_date` | No | Date of promotion |
| `created` | No | Creation date |
| `updated` | No | Last update date |

### Content List Format

The `content` field accepts two formats:

**Simple** — just filenames:
```yaml
content:
  - safe-deletion.md
  - file-management.md
```

**Rich** — with descriptions and per-file export hints:
```yaml
content:
  - file: safe-deletion.md
    description: Rules for safe file deletion
    export_hints:
      claude-code: knowledge
      roo-code: skills
  - file: setup-command.md
    export_hints:
      claude-code: commands
```

### Commands List Format

The `commands` field declares user-invocable slash commands. The corresponding file is always `commands/<name>.md` inside the package directory.

**Simple** — just command names:
```yaml
commands:
  - do-thing
```

**Rich** — with description:
```yaml
commands:
  - name: do-thing
    description: Runs the thing setup process
```

Both forms expect the file at `<package-dir>/commands/do-thing.md`.

### Content Types

| Type | Description | Claude Code export | Roo Code export |
|------|-------------|-------------------|----------------|
| `knowledge` | Passive context loaded automatically by agents (default) | `.claude/skills/<reg>/<pkg>/SKILL.md` | `.roo/rules/kt-<reg>-<pkg>-*.md` (always loaded) |
| `skills` | On-demand capabilities the agent can invoke | `.claude/skills/<reg>/<pkg>/SKILL.md` | `.roo/skills/<name>/SKILL.md` (on-demand via description) |
| `commands` | User-invocable slash commands (e.g., `/start-session`) | `.claude/skills/<cmd>/SKILL.md` (top-level, user-invocable) | `.roo/commands/<name>.md` |
| `modes` | Agent personas (e.g., "Architect") | `.claude/skills/<mode>/SKILL.md` (top-level, user-invocable) | `.roomodes` file (automatically appears in UI) |

### Tree Structure

Packages form a strict tree via `parent` relationships:
- Each package has at most one parent
- Root packages have no parent
- Installing a child auto-installs the full ancestor chain (root → ... → parent → self)
- Removing a parent warns about installed children (does not auto-remove)
- No `depends_on` field — the tree IS the dependency graph
- No cross-registry dependencies — a package's parent must be in the same registry

### Classification

- **Evergreen**: stable conventions, long-term relevance. `kt update` notifies about new evergreen packages that become available.
- **Seasonal**: experimental, trend-based, may change frequently. Default when `classification` is omitted from `package.yaml`.

---

## 10. Registry Model

A registry is a collection of packages with an index file. It can be hosted as a git repo, a local directory, or distributed as an archive file.

### `registry.yaml` Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | 32-character lowercase hex UUID (canonical identity) |
| `packages` | Yes | Dict mapping package names to entries (each has: `description`, `classification`, `tags`, `path`, `parent`) |
| `templates` | No | List of template mappings for files copied to the user's project during `registry add` |

### Registry ID

- Mandatory 32-char lowercase hex string (e.g., `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`)
- Declared by the registry author in `registry.yaml`
- Validated on `kt registry add` — checked for formatting and collisions with existing registries
- Provides stable identity across renames, URL changes, and forks
- `kt author rebuild` preserves the existing ID; auto-generates one if missing

### Registry Sources

| Type | Detection | Cache strategy | Ref tracking |
|------|-----------|---------------|--------------|
| git | Configured Git URLs or local dirs containing `.git` | Full clone (push-ready for `/kt-propose`) | Git commit short hash |
| local | Plain directories (no `.git`) | Full copy | `"local"` marker |
| archive | Archive files (local path or remote URL) | Download (if URL) + extract | Content hash |

### Templates

Registry-level install configuration. Declared in `registry.yaml`:

```yaml
templates:
  - source: templates/.gitignore
    dest: agent-session-management/.gitignore
  - source: templates/config.yaml
    dest: .config/tool.yaml
```

- Templates are instantiated once during `kt registry add`
- Source paths are relative to the registry root
- Destination paths are relative to the user's project root
- If the destination file already exists, the template is **skipped** (no overwrite)
- `kt author rebuild` preserves the `templates` field from existing `registry.yaml`

### Two-Tier Registry Structure

```
my-registry/
  registry.yaml              # Index: id, packages, templates, gitignore
  packages/                  # Curated packages (maintained by registry authors)
    base/
      package.yaml
      content.md
    child/
      package.yaml
      content.md
  community/                 # Community contributions (append-only)
    user-contributed/
      package.yaml
      content.md
  templates/                 # Optional template files
    .gitignore
  CONTRIBUTING.md
```

- `packages/` — curated, quality-controlled by registry maintainers
- `community/` — open for contributions via `kt author contribute`, packages have `status: pending`
- Promotion flow: registry maintainers move community packages to `packages/` and set `status: promoted`

---

## 11. Storage Layout

All KT state lives in a single `.knowledge-tree/` directory. No intermediate directories, no repo `.gitignore` modification.

```
project/
  .knowledge-tree/                 # All KT state (gitignored via internal .gitignore)
    .gitignore                     # Contains "*"
    kt.yaml                       # Project config (personal, not committed)
    cache/
      <registry-name>/            # Disposable registry cache
        registry.yaml
        packages/
          <package>/
            package.yaml
            content.md
        community/
  .claude/                         # Claude Code exports (gitignored via internal .gitignore)
    .gitignore                     # Contains "*"
    skills/
      <registry>/<package>/SKILL.md     # Knowledge/skills packages
      <command-name>/SKILL.md           # Commands (top-level, user-invocable)
  .roo/                            # Roo Code exports (gitignored via internal .gitignore)
    .gitignore                     # Contains "*"
    rules/kt-<reg>-<pkg>-<nn>-<stem>.md  # Knowledge (always loaded)
    skills/<stem>/SKILL.md               # Skills (on-demand)
    commands/<name>.md                   # Commands
```

**Disposable cache**: the registry cache at `.knowledge-tree/cache/` is auto-re-fetched if missing. `kt update` nukes and re-clones rather than doing incremental pulls.

**kt.yaml** tracks:
- `registries`: list of registry sources (each with: source URL, type, branch, ref, canonical ID, display name)
- `packages`: list of installed packages (each with: name, pinned ref, registry ID)
- `export_format`: default tool format (e.g., `claude-code`)
- `exports`: list of exported packages (each with: name, format, ref, registry name)

---

## 12. Workflows

### First-Time Setup

```bash
kt registry add https://github.com/org/registry.git
# → Auto-initializes .knowledge-tree/
# → Shows preview with package tree
# → Prompts for export format (claude-code / roo-code)
# → Interactive package selection (all selected by default)
# → Installs selected packages + exports to chosen format
```

### Adding Packages After Setup

```bash
kt status --available         # See what's available
kt add api-patterns           # Install (ancestors auto-install, auto-exports)
kt add internal-rules --from company  # From a specific registry
kt add --dry-run api-patterns # Preview what would be installed
```

### Keeping Up To Date

```bash
kt update                     # Refresh all registries, re-export everything
kt update api-patterns        # Update a specific package only
```

### Switching AI Tools

```bash
kt update --switch-tool       # Interactive format selection
kt update --format roo-code   # Direct format switch
# → Unexports old format, re-exports in new format
```

### Multi-Registry

```bash
kt registry add https://github.com/org/standards.git --name standards
kt registry add https://github.com/team/internal.git --name internal
kt add coding-rules --from standards
kt add deploy-guide --from internal
kt status                     # Shows all registries and packages
```

### Proposing Changes to Existing Packages

```bash
# 1. Edit exported knowledge files in your AI tool's directory
#    (e.g., .claude/skills/my-registry/base/SKILL.md)

# 2. Run the slash command BEFORE kt update
/kt-propose
# → Agent detects changes via source tracking markers
# → Shows diff summary, lets you select which changes to include
# → For git registries: creates branch, pushes, gives you a PR URL
# → For local registries: writes changes directly to source directory

# 3. After proposing, update to get latest from upstream
kt update
```

### Contributing to a Registry

```bash
# Add a NEW community package (new file → new package in community/)
kt author contribute my-guide.md --name my-guide
kt author contribute my-guide.md --name my-guide --to existing-package
# → Creates branch, commits, pushes, returns PR URL
```

### Registry Authoring

```bash
# Create packages in packages/<name>/ with package.yaml + content files
kt author validate packages/my-package/     # Validate one package
kt author validate packages/ --all          # Validate all packages
kt author rebuild .                         # Regenerate registry.yaml from packages/
```

### CI / Scripting (Non-Interactive)

```bash
# Skip all prompts with --yes
kt registry add https://github.com/org/registry.git --name org --format claude-code --yes
kt update
```

---

*See `workspace/sample-registry/` for a complete registry example.*
