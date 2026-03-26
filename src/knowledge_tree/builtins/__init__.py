"""Built-in knowledge commands and skills shipped with the kt CLI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuiltinEntry:
    """Metadata for a built-in command or skill."""

    filename: str
    content_type: str  # "commands" or "skills"
    description: str


BUILTINS: list[BuiltinEntry] = [
    BuiltinEntry(
        filename="kt-propose.md",
        content_type="commands",
        description="",  # extracted from file content
    ),
    BuiltinEntry(
        filename="kt-reference.md",
        content_type="skills",
        description="Knowledge Tree (kt) CLI reference — use when performing kt operations",
    ),
]
