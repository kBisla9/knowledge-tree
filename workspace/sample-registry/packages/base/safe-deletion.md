# Safe Deletion Practices

## Rule: Never Delete Without Confirmation

Before deleting any resource (file, database record, cloud resource), always:

1. **Verify the target exists** — check before acting
2. **Use soft deletes** where possible — mark as deleted, don't remove
3. **Log what was deleted** — include identifier, timestamp, and who triggered it
4. **Provide undo** — retain deleted data for a configurable grace period

## Examples

### Database Records

```sql
-- Prefer soft delete
UPDATE users SET deleted_at = NOW() WHERE id = 123;

-- NOT hard delete
DELETE FROM users WHERE id = 123;
```

### File Operations

```python
# Move to trash, don't unlink
import shutil
shutil.move(file_path, trash_dir / file_path.name)
```

## When Hard Delete Is Acceptable

- Temporary files created by the current process
- Cache files with a clear regeneration path
- Test fixtures during teardown
- Data subject to GDPR right-to-erasure (after soft delete grace period)
