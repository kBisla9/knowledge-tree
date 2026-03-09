# Contributing to the Knowledge Tree Registry

Thank you for contributing knowledge that helps AI agents write better code!

## How to Contribute

### Quick Way (via CLI)

```bash
kt contribute my-knowledge.md --name my-package
```

This creates a branch, adds your file to `community/`, and gives you a merge request URL.

### Manual Way

1. Fork this repository
2. Create a branch: `contribute/your-package-name`
3. Add your package to `community/your-package-name/`
4. Include a `package.yaml` and your `.md` content files
5. Open a merge request

## Package Structure

```
community/your-package-name/
  package.yaml
  your-content.md
```

### package.yaml Template

```yaml
name: your-package-name
description: One-line description of what this teaches AI agents
authors:
  - Your Name
classification: seasonal
tags:
  - relevant
  - tags
content:
  - your-content.md
```

## Writing Guidelines

- Write for AI consumption: be concise, specific, and example-rich
- Include code examples with language tags
- Keep files under 100 lines — split large topics
- Use tables for reference data
- Focus on *what to do*, not *what not to do*

## Review Process

1. Community contributions land in `community/` (append-only)
2. Maintainers review periodically
3. Accepted packages are promoted to `packages/` (curated)
4. Promoted packages get `status: promoted` in their metadata

## Naming Rules

Package names must be lowercase kebab-case: `my-package`, `cloud-aws-lambda`
