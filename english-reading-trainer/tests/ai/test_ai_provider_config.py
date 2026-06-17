"""
Tests for app/ai/ai_provider_config.py.

No network calls are made; tests only verify local environment resolution.
"""

from pathlib import Path

from app.ai.ai_provider_config import (
    get_ai_provider_settings,
    get_pro_analysis_model,
    get_sentence_analysis_model,
    load_ai_provider_env,
)


class TestLoadAiProviderEnv:
    def test_loads_supported_keys_from_env_file(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("TRAINER_MODEL", raising=False)
        monkeypatch.delenv("TRAINER_SENTENCE_MODEL", raising=False)
        monkeypatch.delenv("TRAINER_PRO_MODEL", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join([
                "OPENAI_API_KEY=sk-test",
                "OPENAI_BASE_URL=https://example.test/v1",
                "TRAINER_MODEL=test-model",
                "TRAINER_SENTENCE_MODEL=test-sentence-model",
                "TRAINER_PRO_MODEL=test-pro-model",
            ]),
            encoding="utf-8",
        )

        load_ai_provider_env(env_file)

        assert get_ai_provider_settings().api_key == "sk-test"
        assert get_ai_provider_settings().base_url == "https://example.test/v1"
        assert get_ai_provider_settings().model == "test-model"
        assert get_sentence_analysis_model() == "test-sentence-model"
        assert get_pro_analysis_model() == "test-pro-model"

    def test_existing_environment_wins(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-existing")
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-file", encoding="utf-8")

        load_ai_provider_env(env_file)

        assert get_ai_provider_settings().api_key == "sk-existing"

    def test_strips_export_and_quotes(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv("TRAINER_MODEL", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text('export TRAINER_MODEL="deepseek-reasoner"', encoding="utf-8")

        load_ai_provider_env(env_file)

        assert get_ai_provider_settings().model == "deepseek-reasoner"


class TestGetAiProviderSettings:
    def test_defaults_to_deepseek_when_env_is_absent(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("TRAINER_MODEL", raising=False)
        monkeypatch.delenv("TRAINER_SENTENCE_MODEL", raising=False)
        monkeypatch.delenv("TRAINER_PRO_MODEL", raising=False)
        monkeypatch.setattr(
            "app.ai.ai_provider_config._DEFAULT_ENV_FILE",
            tmp_path / "missing.env",
        )

        settings = get_ai_provider_settings()

        assert settings.api_key == ""
        assert settings.base_url == "https://api.deepseek.com/v1"
        assert settings.model == "deepseek-v4-flash"
        assert get_sentence_analysis_model() == "deepseek-v4-pro"
        assert get_pro_analysis_model() == "deepseek-v4-pro"

    def test_explicit_model_overrides_env(self, monkeypatch) -> None:
        monkeypatch.setenv("TRAINER_MODEL", "deepseek-v4-flash")

        settings = get_ai_provider_settings("custom-model")

        assert settings.model == "custom-model"

    def test_sentence_model_falls_back_to_pro_model(self, monkeypatch) -> None:
        monkeypatch.delenv("TRAINER_SENTENCE_MODEL", raising=False)
        monkeypatch.setenv("TRAINER_PRO_MODEL", "deepseek-custom-pro")
        monkeypatch.setattr(
            "app.ai.ai_provider_config._DEFAULT_ENV_FILE",
            Path("missing.env"),
        )

        assert get_sentence_analysis_model() == "deepseek-custom-pro"
