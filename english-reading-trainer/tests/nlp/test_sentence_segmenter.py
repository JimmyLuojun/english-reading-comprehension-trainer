"""
Unit tests for app/nlp/sentence_segmenter.py.

No I/O, no DB — pure segmentation logic.
Covers: empty input, single sentence, multi-sentence, abbreviations,
quoted speech, ellipsis, parentheses, offset accuracy, normalize_for_hash.
"""

import pytest

import app.nlp.sentence_segmenter as sentence_segmenter
from app.nlp.sentence_segmenter import (
    SegmentedSentence,
    normalize_for_hash,
    segment_sentences,
)


class _FakeSegmenter:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def segment(self, text: str) -> list[str]:
        return self._tokens


# ---------------------------------------------------------------------------
# Empty / whitespace input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string_returns_empty_list(self) -> None:
        assert segment_sentences("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert segment_sentences("   \n\t  ") == []

    def test_newline_only_returns_empty_list(self) -> None:
        assert segment_sentences("\n\n\n") == []


# ---------------------------------------------------------------------------
# Single sentence
# ---------------------------------------------------------------------------

class TestSingleSentence:
    def test_simple_statement(self) -> None:
        result = segment_sentences("The cat sat on the mat.")
        assert len(result) == 1
        assert result[0].text == "The cat sat on the mat."

    def test_question(self) -> None:
        result = segment_sentences("What is the capital of France?")
        assert len(result) == 1
        assert result[0].text == "What is the capital of France?"

    def test_exclamation(self) -> None:
        result = segment_sentences("This is remarkable!")
        assert len(result) == 1

    def test_no_terminal_punctuation(self) -> None:
        result = segment_sentences("A sentence without punctuation")
        assert len(result) == 1
        assert result[0].text == "A sentence without punctuation"


# ---------------------------------------------------------------------------
# Multiple sentences
# ---------------------------------------------------------------------------

class TestMultipleSentences:
    def test_two_sentences(self) -> None:
        result = segment_sentences("Hello world. Goodbye world.")
        assert len(result) == 2
        assert result[0].text == "Hello world."
        assert result[1].text == "Goodbye world."

    def test_three_sentences(self) -> None:
        result = segment_sentences("One. Two. Three.")
        assert len(result) == 3

    def test_mixed_punctuation(self) -> None:
        result = segment_sentences("Is this a question? Yes, it is! Great.")
        assert len(result) == 3

    def test_sentences_with_extra_spaces(self) -> None:
        result = segment_sentences("First sentence.  Second sentence.")
        assert len(result) == 2
        assert result[0].text == "First sentence."
        assert result[1].text == "Second sentence."


# ---------------------------------------------------------------------------
# Abbreviation handling (key correctness requirement)
# ---------------------------------------------------------------------------

class TestAbbreviations:
    def test_mr_abbreviation(self) -> None:
        result = segment_sentences("Hello Mr. Smith. How are you?")
        assert len(result) == 2
        assert "Mr. Smith" in result[0].text

    def test_dr_abbreviation(self) -> None:
        result = segment_sentences("She visited Dr. Johnson yesterday. He was helpful.")
        assert len(result) == 2
        assert "Dr. Johnson" in result[0].text

    def test_us_abbreviation(self) -> None:
        result = segment_sentences("The U.S. economy grew last year. Analysts were pleased.")
        assert len(result) == 2

    def test_etc_abbreviation(self) -> None:
        result = segment_sentences("He bought apples, oranges, etc. She bought nothing.")
        assert len(result) == 2

    def test_vs_abbreviation(self) -> None:
        result = segment_sentences("The case was Smith vs. Jones. It was dismissed.")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Complex sentence structures
# ---------------------------------------------------------------------------

class TestComplexSentences:
    def test_sentence_with_quoted_speech(self) -> None:
        text = 'She said, "I am fine." He nodded.'
        result = segment_sentences(text)
        assert len(result) == 2

    def test_sentence_with_parentheses(self) -> None:
        result = segment_sentences(
            "The result (see Table 1) was significant. The authors concluded this."
        )
        assert len(result) == 2

    def test_sentence_with_ellipsis(self) -> None:
        result = segment_sentences("He paused... then continued. She waited.")
        # pysbd may treat ellipsis differently; accept 2 or 3 sentences
        assert len(result) >= 2

    def test_long_complex_sentence(self) -> None:
        text = (
            "The report, which the committee had spent three months compiling, "
            "was dismissed by the board without explanation. "
            "No one could understand why."
        )
        result = segment_sentences(text)
        assert len(result) == 2
        assert "committee" in result[0].text

    def test_sentence_with_semicolon(self) -> None:
        result = segment_sentences(
            "The weather was cold; the wind was strong. We stayed inside."
        )
        # semicolons don't end sentences
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Character offset accuracy
# ---------------------------------------------------------------------------

class TestCharacterOffsets:
    def test_offsets_are_non_negative(self) -> None:
        result = segment_sentences("First. Second. Third.")
        for s in result:
            assert s.char_start >= 0
            assert s.char_end > s.char_start

    def test_offsets_increase_monotonically(self) -> None:
        result = segment_sentences("First. Second. Third.")
        for i in range(1, len(result)):
            assert result[i].char_start >= result[i - 1].char_end

    def test_text_recoverable_from_offsets(self) -> None:
        original = "Hello world. Goodbye world."
        result = segment_sentences(original)
        for seg in result:
            extracted = original[seg.char_start:seg.char_end].strip()
            assert extracted == seg.text

    def test_single_sentence_offset_covers_text(self) -> None:
        text = "The quick brown fox."
        result = segment_sentences(text)
        assert len(result) == 1
        assert result[0].char_start == 0
        assert result[0].char_end <= len(text)

    def test_multisentence_offsets_do_not_overlap(self) -> None:
        text = "Sentence one. Sentence two. Sentence three."
        result = segment_sentences(text)
        for i in range(1, len(result)):
            assert result[i].char_start >= result[i - 1].char_end


# ---------------------------------------------------------------------------
# Defensive pysbd token handling
# ---------------------------------------------------------------------------

class TestSegmenterTokenFallbacks:
    def test_whitespace_and_empty_tokens_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sentence_segmenter,
            "_get_segmenter",
            lambda: _FakeSegmenter([" ", "", "Alpha.", " Beta."]),
        )

        result = segment_sentences(" Alpha. Beta.")

        assert [segment.text for segment in result] == ["Alpha.", "Beta."]

    def test_lstripped_token_is_used_when_raw_token_is_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sentence_segmenter,
            "_get_segmenter",
            lambda: _FakeSegmenter(["  Alpha.", " Beta."]),
        )

        result = segment_sentences("Alpha. Beta.")

        assert [segment.text for segment in result] == ["Alpha.", "Beta."]
        assert result[0].char_start == 0

    def test_unrecoverable_token_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sentence_segmenter,
            "_get_segmenter",
            lambda: _FakeSegmenter(["Missing.", "Alpha."]),
        )

        result = segment_sentences("Alpha.")

        assert [segment.text for segment in result] == ["Alpha."]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_list(self) -> None:
        assert isinstance(segment_sentences("Hello."), list)

    def test_elements_are_segmented_sentence(self) -> None:
        result = segment_sentences("Hello world.")
        assert isinstance(result[0], SegmentedSentence)

    def test_text_field_is_stripped(self) -> None:
        result = segment_sentences("  Hello world.  ")
        assert result[0].text == result[0].text.strip()


# ---------------------------------------------------------------------------
# normalize_for_hash
# ---------------------------------------------------------------------------

class TestNormalizeForHash:
    def test_lowercases_text(self) -> None:
        assert normalize_for_hash("Hello World") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert normalize_for_hash("hello   world") == "hello world"

    def test_strips_leading_trailing(self) -> None:
        assert normalize_for_hash("  hello  ") == "hello"

    def test_collapses_newlines(self) -> None:
        assert normalize_for_hash("hello\nworld") == "hello world"

    def test_collapses_tabs(self) -> None:
        assert normalize_for_hash("hello\tworld") == "hello world"

    def test_identical_after_normalize(self) -> None:
        a = normalize_for_hash("The Cat Sat On The Mat.")
        b = normalize_for_hash("the cat sat on the mat.")
        assert a == b

    def test_different_sentences_differ(self) -> None:
        a = normalize_for_hash("The cat sat.")
        b = normalize_for_hash("The dog ran.")
        assert a != b

    def test_empty_string(self) -> None:
        assert normalize_for_hash("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_for_hash("   ") == ""
