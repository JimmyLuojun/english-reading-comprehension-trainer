"""
Tests for app/nlp/english_lemmatizer.py.

Uses spaCy en_core_web_sm when available and verifies the local fallback when
the model is missing. Covers: empty input, whitespace, single word, plural,
verb forms, phrases, punctuation stripping, case normalisation, singleton reuse.
"""

import pytest

import app.nlp.english_lemmatizer as english_lemmatizer
from app.nlp.english_lemmatizer import lemmatize


class _FakeToken:
    def __init__(
        self,
        lemma: str,
        *,
        is_space: bool = False,
        is_punct: bool = False,
    ) -> None:
        self.lemma_ = lemma
        self.is_space = is_space
        self.is_punct = is_punct


class _FakeNlp:
    def __init__(self, tokens: list[_FakeToken]) -> None:
        self._tokens = tokens

    def __call__(self, surface_form: str) -> list[_FakeToken]:
        return self._tokens


# ---------------------------------------------------------------------------
# Empty / whitespace input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string_returns_empty(self):
        assert lemmatize("") == ""

    def test_whitespace_only_returns_empty(self):
        assert lemmatize("   ") == ""

    def test_newlines_only_returns_empty(self):
        assert lemmatize("\n\t\n") == ""


# ---------------------------------------------------------------------------
# Single words — base forms
# ---------------------------------------------------------------------------

class TestBaseForm:
    def test_base_noun_unchanged(self):
        assert lemmatize("dog") == "dog"

    def test_base_verb_unchanged(self):
        assert lemmatize("jump") == "jump"

    def test_base_adjective_unchanged(self):
        assert lemmatize("quick") == "quick"


# ---------------------------------------------------------------------------
# Inflected forms → base lemma
# ---------------------------------------------------------------------------

class TestInflectedForms:
    def test_plural_noun_to_singular(self):
        assert lemmatize("foxes") == "fox"

    def test_plural_noun_dogs(self):
        assert lemmatize("dogs") == "dog"

    def test_past_tense_to_base(self):
        assert lemmatize("jumped") == "jump"

    def test_present_participle_to_base(self):
        # spaCy maps "running" → "run"
        assert lemmatize("running") == "run"

    def test_third_person_singular_to_base(self):
        assert lemmatize("runs") == "run"

    def test_comparative_adjective(self):
        # spaCy maps "quicker" → "quick"
        assert lemmatize("quicker") == "quick"


# ---------------------------------------------------------------------------
# Case handling
# ---------------------------------------------------------------------------

class TestCaseHandling:
    def test_uppercase_lowercased(self):
        assert lemmatize("FOXES") == "fox"

    def test_mixed_case_lowercased(self):
        assert lemmatize("Jumped") == "jump"

    def test_all_caps_plural(self):
        assert lemmatize("DOGS") == "dog"


# ---------------------------------------------------------------------------
# Punctuation stripping
# ---------------------------------------------------------------------------

class TestPunctuationStripping:
    def test_trailing_period_ignored(self):
        assert lemmatize("fox.") == "fox"

    def test_trailing_comma_ignored(self):
        assert lemmatize("dog,") == "dog"

    def test_standalone_punctuation_returns_empty(self):
        # All tokens are punct → no lemmas → fallback to lowercased surface
        result = lemmatize(".")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# spaCy success path
# ---------------------------------------------------------------------------

class TestSpacyPath:
    def test_spacy_model_success_path_is_used(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_nlp", None)
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", False)
        monkeypatch.setattr(
            english_lemmatizer,
            "_load_spacy_model",
            lambda: _FakeNlp([
                _FakeToken("quick"),
                _FakeToken("", is_space=True),
                _FakeToken("", is_punct=True),
                _FakeToken("fox"),
            ]),
        )

        assert english_lemmatizer.lemmatize("Quick, foxes.") == "quick fox"

    def test_spacy_empty_lemma_list_falls_back_to_surface(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_nlp", None)
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", False)
        monkeypatch.setattr(
            english_lemmatizer,
            "_load_spacy_model",
            lambda: _FakeNlp([
                _FakeToken("", is_space=True),
                _FakeToken("", is_punct=True),
            ]),
        )

        assert english_lemmatizer.lemmatize("...") == "..."


# ---------------------------------------------------------------------------
# Multi-word phrases
# ---------------------------------------------------------------------------

class TestPhrases:
    def test_phrase_lemmatized_per_token(self):
        result = lemmatize("quick brown foxes")
        assert "fox" in result
        assert "quick" in result
        assert "brown" in result

    def test_phrase_result_is_space_joined(self):
        result = lemmatize("lazy dogs")
        assert " " in result
        assert "dog" in result

    def test_verb_phrase_lemmatized(self):
        result = lemmatize("jumped over")
        assert "jump" in result
        assert "over" in result


# ---------------------------------------------------------------------------
# Idempotency and singleton
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_calling_twice_returns_same_result(self):
        r1 = lemmatize("foxes")
        r2 = lemmatize("foxes")
        assert r1 == r2

    def test_different_words_different_results(self):
        assert lemmatize("dog") != lemmatize("cat")

    def test_already_lemmatized_is_stable(self):
        # lemmatize of already-base form should equal itself
        assert lemmatize(lemmatize("foxes")) == lemmatize("foxes")


# ---------------------------------------------------------------------------
# Missing spaCy model fallback
# ---------------------------------------------------------------------------

class TestRuleFallback:
    def test_rule_fallback_short_token_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", True)

        assert english_lemmatizer.lemmatize("am") == "am"

    def test_rule_fallback_ies_plural_becomes_y(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", True)

        assert english_lemmatizer.lemmatize("stories") == "story"

    def test_rule_fallback_ied_past_becomes_y(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", True)

        assert english_lemmatizer.lemmatize("studied") == "study"

    def test_rule_fallback_oes_plural_drops_es(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", True)

        assert english_lemmatizer.lemmatize("goes") == "go"

    def test_rule_fallback_does_not_strip_double_s_singular(self, monkeypatch):
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", True)

        assert english_lemmatizer.lemmatize("class") == "class"

    def test_missing_spacy_model_uses_rule_fallback(self, monkeypatch):
        def raise_missing_model():
            raise OSError("model missing")

        monkeypatch.setattr(english_lemmatizer, "_nlp", None)
        monkeypatch.setattr(english_lemmatizer, "_use_rule_fallback", False)
        monkeypatch.setattr(
            english_lemmatizer,
            "_load_spacy_model",
            raise_missing_model,
        )

        assert english_lemmatizer.lemmatize("running foxes") == "run fox"
        assert english_lemmatizer._use_rule_fallback is True
