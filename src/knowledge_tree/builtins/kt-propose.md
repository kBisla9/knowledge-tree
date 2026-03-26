Propose local modifications to exported knowledge files back to their upstream registry.

Compares exported files against the registry cache to detect changes, lets you select which to include, then pushes them upstream — as a pull/merge request for git registries, or by writing directly for directory registries.

> **Important**: Run `/kt-propose` BEFORE running `kt update`. The `kt update` command regenerates exports from the upstream registry and will overwrite your local modifications.

---

## Phase 1: Read Project Configuration

Read the file `.knowledge-tree/kt.yaml` in the project root. Parse it as YAML. The structure is:

```yaml
export_format: claude-code    # "claude-code" or "roo-code"
registries:
  - id: f62db4dc945f4209a802f0de6ec168fc    # 32-char hex UUID
    name: my-registry                        # display name
    source: https://github.com/owner/reg.git # URL or path
    ref: main                                # branch (git) or empty
    type: git                                # "git", "local", or "archive"
packages:
  - name: base
    ref: abc1234
    registry: f62db4dc945f4209a802f0de6ec168fc   # UUID — matches a registry's id
  - name: git-conventions
    ref: abc1234
    registry: f62db4dc945f4209a802f0de6ec168fc
```

Extract these values:
1. `export_format` — determines where exported files live.
2. `registries` — each has `id`, `name`, `source`, `type`, `ref`.
3. `packages` — each has `name` and `registry` (UUID linking it to a registry).

Build a lookup mapping each package to its registry:
- For each entry in `packages`, find the registry whose `id` matches `package.registry`.
- Record: `package_name -> (registry_name, registry_type, registry_source, registry_ref)`.

**Stop conditions:**
- If `.knowledge-tree/kt.yaml` does not exist: tell the user "Project not initialized. Run `kt registry add <url>` to get started." and stop.
- If `export_format` is empty or missing: tell the user "No export format configured. Run `kt update --format <name>` to set one." and stop.
- If `packages` is empty: tell the user "No packages installed." and stop.

---

## Phase 2: Map Packages to Cache Source Paths

For each registry that has at least one installed package, read its registry index file:

**File:** `.knowledge-tree/cache/<registry_name>/registry.yaml`

```yaml
id: f62db4dc945f4209a802f0de6ec168fc
packages:
  base:
    description: Universal coding conventions
    classification: evergreen
    path: packages/base
  git-conventions:
    description: Git commit message standards
    path: packages/git-conventions
    parent: base
```

For each installed package, record two paths:

**Cache source directory** (where the original files live):
```
.knowledge-tree/cache/<registry_name>/<path_from_registry_yaml>/
```
Example: `.knowledge-tree/cache/my-registry/packages/base/`

This directory contains `package.yaml` and source content files like `file-management.md`, `safe-deletion.md`.

**Export path** (where the user-facing exported files live) — depends on `export_format`, detailed in Phase 3.

**Stop conditions:**
- If `.knowledge-tree/cache/<registry_name>/registry.yaml` does not exist: tell the user "Registry cache for '<name>' is missing. Run `kt update` to re-fetch." and skip that registry.
- If a package name from `kt.yaml` is not found in `registry.yaml`'s packages: skip it with a warning.

---

## Phase 3: Detect Changes

For each installed package, compare exported content against the cache originals.

### Claude Code (`export_format: claude-code`)

**Export path:** `.claude/skills/<registry_name>/<package_name>/SKILL.md`

The SKILL.md has this structure:

```markdown
---
name: base
description: "Universal coding conventions"
user-invocable: false
sources:
  - file-management.md
  - safe-deletion.md
---
<!-- Managed by Knowledge Tree — do not edit manually -->

<!-- kt-source: file-management.md -->
[content of file-management.md as it was at export time]

<!-- kt-source: safe-deletion.md -->
[content of safe-deletion.md as it was at export time]
```

**Parsing algorithm:**

1. Read the entire SKILL.md file.
2. Parse the YAML frontmatter (between the opening `---` line and the closing `---` line). Extract the `sources` list — this is the list of original filenames.
3. Scan the body (everything after the frontmatter) for all lines matching the pattern `<!-- kt-source: FILENAME -->`. Collect them in order.
4. For each `<!-- kt-source: FILENAME -->` marker, extract the content between it and the next marker (or end of file):
   - Start: the line immediately AFTER the marker line.
   - End: the line immediately BEFORE the next `<!-- kt-source:` line, or the last line of the file.
   - Trim: remove exactly one leading blank line and one trailing blank line from the extracted content if present (the exporter adds blank-line separators between sections).
5. For each extracted section with filename FILENAME:
   a. Read the original file from cache: `.knowledge-tree/cache/<registry_name>/<package_path>/FILENAME`
   b. Compare the extracted content against the original file content. Normalize both by stripping trailing whitespace from each line and ensuring a single trailing newline, then compare.
   c. If **different**: record as a **modification** `{registry_name, package_name, filename, original_content, modified_content}`
   d. If the **original file does not exist** in the cache: record as an **addition** `{registry_name, package_name, filename, content}`

**Handling commands:** Some packages have `content_type: commands`. Their files are exported to a different location: `.claude/skills/<command-name>/SKILL.md` (top-level, not nested under registry/package). To detect these:
- Read the package's `package.yaml` from the cache source directory.
- If `content_type` is `commands`, look for exported files at `.claude/skills/<stem>/SKILL.md` where `<stem>` is the filename without extension for each content file.
- Parse these SKILL.md files the same way (they have `user-invocable: true` in frontmatter and `<!-- kt-source: FILENAME -->` markers).

**Fallback — no markers:**
If the SKILL.md body has NO `<!-- kt-source: -->` markers at all:
- Read the package's `package.yaml` from the cache. Count content files (files listed in `content`, or all `.md` files in the directory excluding `package.yaml`).
- If **exactly one** source file: treat the entire SKILL.md body (after frontmatter and managed-marker line) as that file's content. Compare against the original.
- If **multiple** source files: tell the user "Exports for package '<name>' don't have source markers. Run `kt update` to regenerate them, re-apply your changes, then run `/kt-propose` again." Skip this package.

---

### Roo Code (`export_format: roo-code`)

Roo Code exports files to up to three directories. Scan all of them.

**Rules — `.roo/rules/`**

Files are named: `kt-<registry>-<package>-<NN>-<stem>.md`

Each file has this structure:
```markdown
<!-- Managed by Knowledge Tree: registry "my-registry" package "base" -->
<!-- kt-source: file-management.md -->

[content of file-management.md]
```

For each `.md` file in `.roo/rules/` whose name starts with `kt-`:
1. Read the first line. Parse the managed comment to extract the registry name (text between `registry "` and `"`) and the package name (text between `package "` and `"`).
2. Check if this registry+package matches an installed package. If not, skip.
3. Read the second line. If it matches `<!-- kt-source: FILENAME -->`, use FILENAME as the source filename.
4. If no `kt-source` marker on line 2, derive the source filename: read the package's `package.yaml` from cache and match by stem. As a last resort, extract the stem after the `<NN>-` part of the export filename and append `.md`.
5. Extract the content: everything after the managed comment line(s) and the first blank line separator.
6. Read the original from cache and compare, same normalization as Claude Code.

**Skills — `.roo/skills/*/SKILL.md`**

For each `SKILL.md` inside `.roo/skills/`:
1. Read the file. Look for a managed comment containing `Managed by Knowledge Tree:`.
2. Parse `registry "NAME"` and `package "NAME"` from it.
3. Parse `<!-- kt-source: FILENAME -->` markers and extract sections — same algorithm as Claude Code.

**Commands — `.roo/commands/*.md`**

For each `.md` file in `.roo/commands/`:
1. Read the file. Look for a managed comment containing `Managed by Knowledge Tree:`.
2. Parse `registry "NAME"`, `package "NAME"`, and `command "NAME"` from it.
3. Look for a `<!-- kt-source: FILENAME -->` marker. Extract content and compare against cache.

---

## Phase 4: Present Changes

Group all detected changes by registry, then by package.

Present to the user in this format:

```
Detected local changes:

Registry: my-registry (git — https://github.com/owner/registry.git)
  base
    - file-management.md — modified
    - new-conventions.md — new file
  git-conventions
    - branching.md — modified

Registry: local-docs (directory — /path/to/local/docs)
  api-patterns
    - rest-api.md — modified
```

For each modification, briefly describe what changed (e.g., "added new section on error handling", "updated code examples"). Read both the original and modified content to produce this summary.

**If no changes are detected** across all packages: tell the user "No local modifications detected. All exported files match the registry cache." and stop.

---

## Phase 5: User Selection

Ask the user which changes to propose upstream.

All detected changes are pre-selected by default. Present them as a numbered list and ask:

```
All changes above will be included. Would you like to:
  - Proceed with all changes
  - Deselect specific items (tell me which to exclude)
  - See the full diff for any item before deciding
```

If the user asks to see a diff, show the unified diff between the original cache content and the modified export content for that file.

Once the user confirms their selection, proceed to Phase 6.

If the user selects changes from multiple registries, process each registry independently.

---

## Phase 6: Apply Changes

### For `type: archive` registries:

Tell the user: "Registry '<name>' is sourced from an archive file. Proposing changes to archive registries is not supported — there is no upstream to push to." Skip this registry.

---

### For `type: local` (directory) registries:

The registry source is a local directory path. Apply changes directly to the source files.

For each selected change:
1. Build the target path: `<registry_source>/<package_path>/<filename>`
   - `registry_source` = the `source` field from the registry in `kt.yaml` (e.g., `/path/to/local/docs`)
   - `package_path` = the `path` from `registry.yaml` (e.g., `packages/api-patterns`)
   - `filename` = the source filename (e.g., `rest-api.md`)
2. **Modification**: Write the modified content to the target path, overwriting the existing file.
3. **Addition**: Create the new file at the target path. Then read `<registry_source>/<package_path>/package.yaml`, add the new filename to its `content` list, and save it back.

After applying, tell the user:
```
Applied changes directly to local registry at <source_path>:
  - api-patterns/rest-api.md (modified)
```

---

### For `type: git` registries:

Create a branch in the registry cache, apply changes, push, and generate a PR/MR URL.

**Step 1 — Prepare the cache repo:**

Run these commands in `.knowledge-tree/cache/<registry_name>/`:

```bash
# Ensure we're on the tracked branch with a clean state
git checkout <ref>
git pull origin <ref>
```

Where `<ref>` is the registry's `ref` field from `kt.yaml` (typically `main`).

If `git pull` fails (e.g., merge conflict from a previous failed propose), reset and retry:
```bash
git reset --hard origin/<ref>
git clean -fd
```

**Step 2 — Create a proposal branch:**

Generate the branch name:
- If changes span 1-3 packages: `propose/<package1>-<package2>-<package3>`
- If changes span 4+ packages: `propose/updates-<YYYY-MM-DD>`

```bash
git checkout -b <branch_name>
```

**Step 3 — Apply changes to source files:**

For each selected change:
1. Determine the file path relative to the cache root: `<package_path>/<filename>`
   Example: `packages/base/file-management.md`
2. **Modification**: Write the modified content to the file, overwriting it.
3. **Addition**: Create the new file. Read `<package_path>/package.yaml`, add the new filename to the `content` list, and save.
4. Stage:
   ```bash
   git add <package_path>/<filename>
   git add <package_path>/package.yaml   # only if it was modified (additions)
   ```

**Step 4 — Commit:**

```bash
git commit -m "Propose changes to <package-list>"
```

Where `<package-list>` is a comma-separated list of affected package names. Example: `"Propose changes to base, git-conventions"`.

**Step 5 — Push:**

```bash
git push -u origin <branch_name>
```

If push fails, tell the user:
```
Push failed — ensure you have write access to the remote (<source_url>).
The branch '<branch_name>' has been created locally in the cache at:
  .knowledge-tree/cache/<registry_name>/
You can push it manually when access is resolved.
```
Then skip to cleanup (Step 7).

**Step 6 — Generate PR/MR URL:**

Read the remote URL:
```bash
git remote get-url origin
```

Convert the remote URL to a web URL:
- SSH format `git@HOST:USER/REPO.git` -> `https://HOST/USER/REPO`
- HTTPS format `https://HOST/USER/REPO.git` -> strip `.git` suffix

Build the PR creation URL based on the hosting provider:
- **GitHub** (remote contains `github.com`): `https://github.com/<user>/<repo>/compare/<branch_name>?expand=1`
- **GitLab** (remote contains `gitlab`): `https://gitlab.com/<user>/<repo>/-/merge_requests/new?merge_request[source_branch]=<branch_name>`
- **Bitbucket** (remote contains `bitbucket`): `https://bitbucket.org/<user>/<repo>/pull-requests/new?source=<branch_name>`
- **Other**: tell the user "Create a PR/MR from branch '<branch_name>' at your git host."

**Step 7 — Switch back to tracked branch:**
```bash
git checkout <ref>
```

---

## Phase 7: Report

After processing all registries, present a final summary.

For git registries:
```
Proposed changes to my-registry:
  base — file-management.md (modified), new-conventions.md (added)
  git-conventions — branching.md (modified)

  Branch: propose/base-git-conventions
  PR: https://github.com/owner/registry/compare/propose/base-git-conventions?expand=1

  Open the URL above to create a pull request for the registry maintainers to review.
```

For directory registries:
```
Applied changes to local-docs (/path/to/docs):
  api-patterns — rest-api.md (modified)
  Files were written directly to the source directory.
```

---

## Error Reference

| Condition | Response |
|-----------|----------|
| `.knowledge-tree/kt.yaml` not found | "Project not initialized. Run `kt registry add <url>` to get started." Stop. |
| `export_format` is empty | "No export format set. Run `kt update --format <name>` first." Stop. |
| `packages` list is empty | "No packages installed." Stop. |
| Registry cache directory missing | "Cache for '<name>' is missing. Run `kt update`." Skip registry. |
| `registry.yaml` missing in cache | Same as above. |
| Exported SKILL.md not found for a package | Skip silently — package may not be exported. |
| No `kt-source` markers + multiple source files | "Run `kt update` to regenerate exports with source markers." Skip package. |
| No changes detected across all packages | "No local modifications detected." Stop. |
| Archive registry has changes | "Archive registries don't support upstream proposals." Skip. |
| Git push fails (auth / permissions) | Show error. Tell user branch exists locally. Continue with other registries. |
| `package.yaml` missing in cache source dir | Skip package with warning: "Cannot read metadata for '<name>'." |
| Git checkout/pull fails in cache | "Cache repo is in an unexpected state. Run `kt update` to reset it." Skip registry. |
