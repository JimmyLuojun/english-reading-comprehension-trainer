"""
Synchronize versioned Markdown prompt files into the prompt_versions table.

Prompt files are named like sentence_analysis.v1.md and carry matching
frontmatter. Existing prompt versions are immutable: changing prompt text must
create a new versioned file instead of rewriting a historical version.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.db_connection import DatabaseConnection

_PROMPT_FILENAME_RE = re.compile(
    r"^(?P<name>[a-z][a-z0-9_]*)\.(?P<version>v(?P<number>\d+))\.md$"
)


class PromptVersionSyncError(ValueError):
    """Raised when prompt files cannot be safely synchronized."""


@dataclass(frozen=True)
class PromptFile:
    """Parsed prompt file metadata and raw Markdown body."""

    name: str
    version: str
    version_number: int
    path: Path
    body_md: str


@dataclass(frozen=True)
class PromptSyncResult:
    """Summary of a prompt-version synchronization run."""

    inserted: int
    total_files: int
    active_versions: dict[str, str]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_frontmatter(text: str, path: Path) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptVersionSyncError(f"{path.name} is missing YAML frontmatter")

    closing_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = idx
            break

    if closing_index is None:
        raise PromptVersionSyncError(f"{path.name} has unterminated YAML frontmatter")

    values: dict[str, str] = {}
    for line in lines[1:closing_index]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_prompt_file(path: Path) -> PromptFile:
    match = _PROMPT_FILENAME_RE.match(path.name)
    if match is None:
        raise PromptVersionSyncError(
            f"{path.name} must be named <prompt_name>.v<number>.md"
        )

    body = path.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(body, path)
    name = match.group("name")
    version = match.group("version")
    if metadata.get("name") != name:
        raise PromptVersionSyncError(
            f"{path.name} frontmatter name must be {name!r}"
        )
    if metadata.get("version") != version:
        raise PromptVersionSyncError(
            f"{path.name} frontmatter version must be {version!r}"
        )

    return PromptFile(
        name=name,
        version=version,
        version_number=int(match.group("number")),
        path=path,
        body_md=body,
    )


def _load_prompt_files(prompts_dir: Path) -> list[PromptFile]:
    if not prompts_dir.exists():
        raise FileNotFoundError(prompts_dir)

    return sorted(
        (_parse_prompt_file(path) for path in prompts_dir.glob("*.md")),
        key=lambda item: (item.name, item.version_number),
    )


def sync_prompt_versions(
    db: DatabaseConnection,
    prompts_dir: str | Path,
) -> PromptSyncResult:
    """Upsert new prompt versions and mark the newest version per name active."""
    prompt_files = _load_prompt_files(Path(prompts_dir))
    grouped: dict[str, list[PromptFile]] = defaultdict(list)
    for prompt_file in prompt_files:
        grouped[prompt_file.name].append(prompt_file)

    active_versions = {
        name: max(files, key=lambda item: item.version_number).version
        for name, files in grouped.items()
    }

    inserted = 0
    with db.get_connection() as conn:
        for prompt_file in prompt_files:
            row = conn.execute(
                """SELECT body_md
                   FROM prompt_versions
                   WHERE name = ? AND version = ?""",
                (prompt_file.name, prompt_file.version),
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO prompt_versions
                       (name, version, body_md, created_at, is_active)
                       VALUES (?, ?, ?, ?, 0)""",
                    (
                        prompt_file.name,
                        prompt_file.version,
                        prompt_file.body_md,
                        _utcnow(),
                    ),
                )
                inserted += 1
            elif row["body_md"] != prompt_file.body_md:
                raise PromptVersionSyncError(
                    f"{prompt_file.path.name} differs from stored prompt version; "
                    "create a new versioned prompt file instead"
                )

        for name, active_version in active_versions.items():
            conn.execute(
                """UPDATE prompt_versions
                   SET is_active = CASE WHEN version = ? THEN 1 ELSE 0 END
                   WHERE name = ?""",
                (active_version, name),
            )

    return PromptSyncResult(
        inserted=inserted,
        total_files=len(prompt_files),
        active_versions=active_versions,
    )
