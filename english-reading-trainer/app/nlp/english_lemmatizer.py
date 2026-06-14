"""
English lemmatizer using spaCy en_core_web_sm.

Singleton model is loaded lazily on first call to lemmatize().
Disables parser and ner since only the tagger + lemmatizer are needed.
"""

from __future__ import annotations

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    return _nlp


def lemmatize(surface_form: str) -> str:
    """
    Return the spaCy lemma for surface_form.

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
    doc = nlp(surface_form)
    lemmas = [
        token.lemma_.lower()
        for token in doc
        if not token.is_space and not token.is_punct
    ]
    return " ".join(lemmas) if lemmas else surface_form.lower()
