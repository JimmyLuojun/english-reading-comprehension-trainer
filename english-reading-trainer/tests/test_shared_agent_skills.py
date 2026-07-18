"""Contract tests for project skills shared by Codex, Kimi, and Antigravity."""

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_SKILLS = PROJECT_ROOT / ".agents" / "skills"


def _read_skill(name: str) -> tuple[dict[str, str], str]:
    text = (SHARED_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---", 2)
    metadata = {
        key.strip(): value.strip()
        for line in frontmatter.strip().splitlines()
        for key, value in [line.split(":", 1)]
    }
    return metadata, body


@pytest.mark.parametrize("name", ["analyze-word", "analyze-sentence"])
def test_shared_skill_has_portable_frontmatter(name: str) -> None:
    metadata, body = _read_skill(name)

    assert metadata.keys() == {"name", "description"}
    assert metadata["name"] == name
    assert metadata["description"]
    assert body.strip()


@pytest.mark.parametrize(
    ("name", "prompt_command", "save_command"),
    [
        ("analyze-word", "ai prompt-word", "ai save-word"),
        ("analyze-sentence", "ai prompt-sentence", "ai save-sentence"),
    ],
)
def test_shared_skill_uses_application_cli_contract(
    name: str,
    prompt_command: str,
    save_command: str,
) -> None:
    _, body = _read_skill(name)

    assert ".venv/bin/python -m app.cli_entry" in body
    assert prompt_command in body
    assert save_command in body
    assert "--input-file" in body
    assert "python - <<" not in body
    assert "model=" not in body


def test_antigravity_rule_delegates_to_canonical_agents_file() -> None:
    rule = (PROJECT_ROOT / ".agents" / "rules" / "project-standards.md").read_text(
        encoding="utf-8"
    )

    assert "@../../AGENTS.md" in rule
    assert "canonical source" in rule
    assert "Always" in rule and "On" in rule
