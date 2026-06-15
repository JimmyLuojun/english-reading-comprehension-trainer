"""
English lemmatizer with a spaCy model first and local rules as fallback.

The preferred path uses the local `en_core_web_sm` model. If the model is not
installed, a small deterministic fallback keeps tests and offline usage working
for the common inflections this project needs for similar-card matching.
"""

from __future__ import annotations

import re
from typing import Any

_SPACY_MODEL = "en_core_web_sm"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_DOUBLED_CONSONANTS = ("bb", "dd", "gg", "ll", "mm", "nn", "pp", "rr", "tt")

_nlp = None
_use_rule_fallback = False


def _load_spacy_model() -> Any:
    import spacy

    return spacy.load(_SPACY_MODEL, disable=["parser", "ner"])


def _get_nlp() -> Any | None:
    global _nlp, _use_rule_fallback
    if _use_rule_fallback:
        return None
    if _nlp is None:
        try:
            _nlp = _load_spacy_model()
        except (ImportError, OSError):
            _use_rule_fallback = True
            return None
    return _nlp


def _lemmatize_with_spacy(surface_form: str, nlp: Any) -> str:
    doc = nlp(surface_form)
    lemmas = [
        token.lemma_.lower()
        for token in doc
        if not token.is_space and not token.is_punct
    ]
    return " ".join(lemmas) if lemmas else surface_form.lower()


def _lemmatize_with_rules(surface_form: str) -> str:
    tokens = _TOKEN_RE.findall(surface_form)
    return " ".join(_lemmatize_token(token) for token in tokens)


def _lemmatize_token(token: str) -> str:
    if len(token) <= 2:
        return token
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if _ends_with_any(token, ("ches", "shes", "sses", "xes", "zes", "oes")):
        return token[:-2]
    if token.endswith("ing") and len(token) > 5:
        return _strip_doubled_consonant(token[:-3])
    if token.endswith("ied") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("ed") and len(token) > 4:
        return _strip_doubled_consonant(token[:-2])
    if token.endswith("er") and len(token) > 4:
        return _strip_doubled_consonant(token[:-2])
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _ends_with_any(value: str, suffixes: tuple[str, ...]) -> bool:
    return any(value.endswith(suffix) for suffix in suffixes)


def _strip_doubled_consonant(value: str) -> str:
    if _ends_with_any(value, _DOUBLED_CONSONANTS):
        return value[:-1]
    return value


def lemmatize(surface_form: str) -> str:
    """
    Return a normalized lemma for surface_form.

    Rules:
    - Empty or whitespace-only input returns "".
    - Punctuation tokens are ignored.
    - Result is lowercased.
    - Multi-word phrases: lemmas of content tokens joined by single spaces.
    """
    surface_form = surface_form.strip().lower()
    if not surface_form:
        return ""
    nlp = _get_nlp()
    if nlp is not None:
        return _lemmatize_with_spacy(surface_form, nlp)
    return _lemmatize_with_rules(surface_form)
