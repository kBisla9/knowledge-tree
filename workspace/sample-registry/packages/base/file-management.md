# File Management Conventions

## Directory Structure

Organize project files by function, not by type:

```
src/
  auth/
    handler.py
    middleware.py
    tests/
  billing/
    handler.py
    models.py
    tests/
```

Not by type:

```
# Avoid this
handlers/
models/
tests/
```

## Naming Rules

- Use lowercase with hyphens for directories: `user-auth/`, not `userAuth/`
- Use snake_case for Python files: `user_handler.py`
- Use kebab-case for config files: `deploy-config.yaml`
- Prefix private/internal files with underscore: `_helpers.py`

## File Size Guidelines

- Keep files under 300 lines. If a file exceeds this, split by responsibility.
- One module = one concept. A file named `utils.py` is a code smell.
- Test files mirror source files: `auth/handler.py` → `auth/tests/test_handler.py`

## Import Ordering

1. Standard library
2. Third-party packages
3. Local imports

Separate each group with a blank line.
