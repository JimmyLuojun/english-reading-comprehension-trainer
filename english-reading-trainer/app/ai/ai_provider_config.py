"""
AI provider configuration for OpenAI-compatible APIs.

Loads local environment values from ``.env`` and exposes the provider settings
used by direct LLM calls. Existing process environment variables take priority
over values from ``.env``.
"""

import os
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"
_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-v4-flash"
_DEFAULT_SENTENCE_MODEL = "deepseek-v4-pro"
_DEFAULT_PRO_MODEL = "deepseek-v4-pro"
_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "TRAINER_MODEL",
    "TRAINER_SENTENCE_MODEL",
    "TRAINER_PRO_MODEL",
)


@dataclass(frozen=True)
class AIProviderSettings:
    api_key: str
    base_url: str
    model: str


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.removeprefix("export ").strip()
    value = value.strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return key, value


def load_ai_provider_env(env_file: Path | None = None) -> None:
    """Load provider environment variables from a dotenv-style file."""
    path = env_file or _DEFAULT_ENV_FILE
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue

        key, value = parsed
        if key in _ENV_KEYS and key not in os.environ:
            os.environ[key] = value


def get_ai_provider_settings(model: str | None = None) -> AIProviderSettings:
    """Return effective OpenAI-compatible provider settings."""
    load_ai_provider_env()
    return AIProviderSettings(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("OPENAI_BASE_URL", _DEFAULT_BASE_URL),
        model=model or os.environ.get("TRAINER_MODEL", _DEFAULT_MODEL),
    )


def get_sentence_analysis_model(model: str | None = None) -> str:
    """Return the model used for sentence-level AI diagnosis."""
    load_ai_provider_env()
    return (
        model
        or os.environ.get("TRAINER_SENTENCE_MODEL")
        or os.environ.get("TRAINER_PRO_MODEL")
        or _DEFAULT_SENTENCE_MODEL
    )


def get_pro_analysis_model(model: str | None = None) -> str:
    """Return the high-accuracy model for explicit Pro reanalysis."""
    load_ai_provider_env()
    return model or os.environ.get("TRAINER_PRO_MODEL", _DEFAULT_PRO_MODEL)
