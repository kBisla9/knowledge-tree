# Git Commit Message Standards

## Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

## Types

| Type       | When to use                          |
|------------|--------------------------------------|
| `feat`     | New feature                          |
| `fix`      | Bug fix                              |
| `docs`     | Documentation only                   |
| `refactor` | Code change that neither fixes nor adds |
| `test`     | Adding or updating tests             |
| `chore`    | Build, CI, dependency updates        |

## Rules

1. **Subject line**: imperative mood, no period, max 72 characters
2. **Body**: explain *why*, not *what* — the diff shows what changed
3. **Footer**: reference issue numbers (`Closes #123`)
4. **Scope**: the module or area affected (`auth`, `billing`, `ci`)

## Examples

```
feat(auth): add JWT refresh token rotation

Refresh tokens are now rotated on each use to limit the window
of token theft. Old tokens are invalidated immediately.

Closes #456
```

```
fix(billing): prevent double-charge on retry

The idempotency key was not being passed on payment retries,
causing duplicate charges for ~0.1% of transactions.

Closes #789
```

## Branch Naming

- Feature: `feature/<ticket>-<short-description>`
- Bugfix: `fix/<ticket>-<short-description>`
- Release: `release/<version>`
