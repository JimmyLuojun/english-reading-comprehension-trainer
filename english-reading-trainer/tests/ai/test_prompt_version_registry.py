"""
Tests for app/ai/prompt_version_registry.py.

Uses real SQLite and temporary prompt directories to verify prompt version
synchronization, active-version selection, and immutable historical versions.
"""

from pathlib import Path

import pytest

from app.ai.prompt_version_registry import (
    PromptVersionSyncError,
    sync_prompt_versions,
)
from app.db_connection import DatabaseConnection

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
REAL_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@pytest.fixture()
def db(tmp_path: Path) -> DatabaseConnection:
    conn = DatabaseConnection(tmp_path / "test.db")
    conn.apply_migrations(MIGRATIONS_DIR)
    return conn


def _write_prompt(
    prompts_dir: Path,
    name: str,
    version: str,
    body: str = "Prompt body.",
) -> Path:
    path = prompts_dir / f"{name}.{version}.md"
    path.write_text(
        f"---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"reason: test prompt\n"
        f"---\n\n"
        f"# {name} {version}\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


class TestSyncPromptVersions:
    def test_sync_real_prompt_files_inserts_expected_rows(
        self, db: DatabaseConnection
    ) -> None:
        result = sync_prompt_versions(db, REAL_PROMPTS_DIR)

        assert result.inserted == 5
        assert result.total_files == 5
        assert result.active_versions == {
            "profile_summary": "v1",
            "sentence_analysis_diagnose": "v1",
            "sentence_analysis_predict": "v1",
            "word_analysis": "v2",
        }
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]
            active_count = conn.execute(
                "SELECT COUNT(*) FROM prompt_versions WHERE is_active = 1"
            ).fetchone()[0]
        assert count == 5
        assert active_count == 4

    def test_sync_is_idempotent(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _write_prompt(prompts_dir, "sentence_analysis", "v1")

        first = sync_prompt_versions(db, prompts_dir)
        second = sync_prompt_versions(db, prompts_dir)

        assert first.inserted == 1
        assert second.inserted == 0
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]
        assert count == 1

    def test_newest_version_is_active(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _write_prompt(prompts_dir, "sentence_analysis", "v1")
        _write_prompt(prompts_dir, "sentence_analysis", "v2")

        result = sync_prompt_versions(db, prompts_dir)

        assert result.active_versions == {"sentence_analysis": "v2"}
        with db.get_connection() as conn:
            rows = conn.execute(
                """SELECT version, is_active
                   FROM prompt_versions
                   WHERE name = 'sentence_analysis'
                   ORDER BY version"""
            ).fetchall()
        assert [(row["version"], row["is_active"]) for row in rows] == [
            ("v1", 0),
            ("v2", 1),
        ]

    def test_removed_prompt_name_is_deactivated(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        old_path = _write_prompt(prompts_dir, "sentence_analysis", "v1")
        sync_prompt_versions(db, prompts_dir)
        old_path.unlink()
        _write_prompt(prompts_dir, "sentence_analysis_predict", "v1")

        sync_prompt_versions(db, prompts_dir)

        with db.get_connection() as conn:
            rows = conn.execute(
                """SELECT name, is_active
                   FROM prompt_versions
                   ORDER BY name"""
            ).fetchall()
        assert [(row["name"], row["is_active"]) for row in rows] == [
            ("sentence_analysis", 0),
            ("sentence_analysis_predict", 1),
        ]

    def test_version_sort_uses_numeric_order(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        _write_prompt(prompts_dir, "word_analysis", "v2")
        _write_prompt(prompts_dir, "word_analysis", "v10")

        result = sync_prompt_versions(db, prompts_dir)

        assert result.active_versions == {"word_analysis": "v10"}

    def test_existing_version_body_is_immutable(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        path = _write_prompt(prompts_dir, "profile_summary", "v1", "Original body.")
        sync_prompt_versions(db, prompts_dir)
        path.write_text(
            "---\n"
            "name: profile_summary\n"
            "version: v1\n"
            "reason: rewritten\n"
            "---\n\n"
            "# Changed\n\n"
            "Changed body.\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="new versioned prompt"):
            sync_prompt_versions(db, prompts_dir)

    def test_frontmatter_name_must_match_filename(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        path = _write_prompt(prompts_dir, "sentence_analysis", "v1")
        path.write_text(
            "---\nname: word_analysis\nversion: v1\nreason: bad\n---\n\nBody\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="frontmatter name"):
            sync_prompt_versions(db, prompts_dir)

    def test_frontmatter_version_must_match_filename(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        path = _write_prompt(prompts_dir, "sentence_analysis", "v1")
        path.write_text(
            "---\nname: sentence_analysis\nversion: v2\nreason: bad\n---\n\nBody\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="frontmatter version"):
            sync_prompt_versions(db, prompts_dir)

    def test_invalid_filename_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "sentence_analysis.md").write_text(
            "---\nname: sentence_analysis\nversion: v1\n---\n\nBody\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="must be named"):
            sync_prompt_versions(db, prompts_dir)

    def test_missing_frontmatter_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "sentence_analysis.v1.md").write_text(
            "# Prompt without frontmatter\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="missing YAML"):
            sync_prompt_versions(db, prompts_dir)

    def test_unterminated_frontmatter_raises(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "sentence_analysis.v1.md").write_text(
            "---\nname: sentence_analysis\nversion: v1\n",
            encoding="utf-8",
        )

        with pytest.raises(PromptVersionSyncError, match="unterminated"):
            sync_prompt_versions(db, prompts_dir)

    def test_frontmatter_ignores_lines_without_colons(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "sentence_analysis.v1.md").write_text(
            "---\n"
            "name: sentence_analysis\n"
            "this line is ignored\n"
            "version: v1\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )

        result = sync_prompt_versions(db, prompts_dir)

        assert result.inserted == 1

    def test_missing_prompt_directory_raises(self, db: DatabaseConnection) -> None:
        with pytest.raises(FileNotFoundError):
            sync_prompt_versions(db, Path("does-not-exist"))

    def test_empty_prompt_directory_is_noop(
        self, db: DatabaseConnection, tmp_path: Path
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        result = sync_prompt_versions(db, prompts_dir)

        assert result.inserted == 0
        assert result.total_files == 0
        assert result.active_versions == {}
