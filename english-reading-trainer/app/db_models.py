"""
Data model constants and type definitions for the reading trainer database.

All enums here are the single source of truth — migration SQL and application
code must stay in sync with these values.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations (closed sets — do not add values without updating migrations)
# ---------------------------------------------------------------------------

class SourceFormat(str, Enum):
    TXT  = "txt"
    EPUB = "epub"


class LexicalType(str, Enum):
    WORD        = "word"
    PHRASE      = "phrase"
    COLLOCATION = "collocation"


class CardType(str, Enum):
    SENTENCE = "sentence"
    WORD     = "word"


class ReviewOutcome(str, Enum):
    PASS    = "pass"
    PARTIAL = "partial"
    FAIL    = "fail"


class MasteryState(str, Enum):
    NEW      = "new"
    LEARNING = "learning"
    MATURE   = "mature"
    LAPSED   = "lapsed"


class ErrorLayer(str, Enum):
    GRAMMAR   = "grammar"
    LEXICAL   = "lexical"
    DISCOURSE = "discourse"


# ---------------------------------------------------------------------------
# Closed error-type codes — matches §2 of design.md exactly
# ---------------------------------------------------------------------------

ERROR_TYPES: list[dict] = [
    # Grammar layer
    {"code": "G01", "name": "长主语识别失败",              "layer": ErrorLayer.GRAMMAR},
    {"code": "G02", "name": "后置定语修饰对象判断错",       "layer": ErrorLayer.GRAMMAR},
    {"code": "G03", "name": "嵌套从句边界混乱",            "layer": ErrorLayer.GRAMMAR},
    {"code": "G04", "name": "倒装 / 强调结构",             "layer": ErrorLayer.GRAMMAR},
    {"code": "G05", "name": "非谓语动词（分词 / 不定式）作用判断错", "layer": ErrorLayer.GRAMMAR},
    {"code": "G06", "name": "省略 / 替代识别失败",         "layer": ErrorLayer.GRAMMAR},
    {"code": "G07", "name": "平行结构对应失败",            "layer": ErrorLayer.GRAMMAR},
    # Lexical layer
    {"code": "L01", "name": "多义词在当前语境的义项判断错", "layer": ErrorLayer.LEXICAL},
    {"code": "L02", "name": "假朋友 / 形近词混淆",         "layer": ErrorLayer.LEXICAL},
    {"code": "L03", "name": "搭配（动名 / 形名 / 介词）不熟", "layer": ErrorLayer.LEXICAL},
    {"code": "L04", "name": "词根 / 词族联想不足",         "layer": ErrorLayer.LEXICAL},
    {"code": "L05", "name": "习语 / 固定短语未识别",        "layer": ErrorLayer.LEXICAL},
    {"code": "L06", "name": "学术词汇陌生",               "layer": ErrorLayer.LEXICAL},
    # Discourse layer
    {"code": "D01", "name": "代词指代对象判断错（it / they / which / that）", "layer": ErrorLayer.DISCOURSE},
    {"code": "D02", "name": "让步 / 对比逻辑（while / although / however）误读", "layer": ErrorLayer.DISCOURSE},
    {"code": "D03", "name": "因果 / 推论连词误读",         "layer": ErrorLayer.DISCOURSE},
    {"code": "D04", "name": "信息焦点（主述位）判断错",     "layer": ErrorLayer.DISCOURSE},
    {"code": "D05", "name": "篇章衔接（this / these / such）回指失败", "layer": ErrorLayer.DISCOURSE},
]

# All valid error codes — used for validation
VALID_ERROR_CODES: frozenset[str] = frozenset(e["code"] for e in ERROR_TYPES)

# ---------------------------------------------------------------------------
# SM-2 defaults
# ---------------------------------------------------------------------------

SM2_DEFAULT_EF            = 2.5
SM2_MIN_EF                = 1.3
SM2_INITIAL_INTERVAL_DAYS = 0
SM2_INITIAL_REPETITIONS   = 0

# UI outcome → SM-2 quality mapping (§7.3 of design.md)
OUTCOME_TO_QUALITY: dict[str, int] = {
    ReviewOutcome.PASS:    5,
    ReviewOutcome.PARTIAL: 3,
    ReviewOutcome.FAIL:    1,
}

# ---------------------------------------------------------------------------
# Daily review queue budget defaults (§7.5 of design.md)
# ---------------------------------------------------------------------------

QUEUE_DAILY_LIMIT         = 40
QUEUE_NEW_CARD_SLOTS      = 10
QUEUE_OLD_CARD_SLOTS      = 30
QUEUE_TOP_ERROR_CODES     = 3
QUEUE_MIN_PER_ERROR_CODE  = 3

# ---------------------------------------------------------------------------
# Learner profile generation thresholds (§11 of design.md)
# ---------------------------------------------------------------------------

PROFILE_REVIEW_TRIGGER    = 20   # generate after this many reviews
PROFILE_DAY_TRIGGER       = 7    # or after this many days since last snapshot
PROFILE_LOOKBACK_DAYS     = 90   # only use data from the last N days


# ---------------------------------------------------------------------------
# Lightweight dataclasses — used by application code, not ORM
# ---------------------------------------------------------------------------

@dataclass
class BookRecord:
    id: Optional[int]
    title: str
    author: str
    language: str
    source_format: SourceFormat
    file_hash: str
    imported_at: datetime
    total_chapters: int = 0
    total_sentences: int = 0


@dataclass
class ChapterRecord:
    id: Optional[int]
    book_id: int
    idx: int
    title: str
    sentence_start: int
    sentence_end: int


@dataclass
class ParagraphRecord:
    id: Optional[int]
    chapter_id: int
    idx: int
    sentence_start: int
    sentence_end: int


@dataclass
class SentenceRecord:
    id: Optional[int]
    book_id: int
    chapter_id: int
    paragraph_id: int
    idx: int
    text: str
    text_hash: str
    char_offset_start: int
    char_offset_end: int


@dataclass
class SentenceCardRecord:
    id: Optional[int]
    sentence_id: int
    created_at: datetime
    last_reviewed_at: Optional[datetime]
    review_count: int
    mastery_state: MasteryState
    ef: float
    interval_days: int
    repetitions: int
    due_at: datetime
    user_note: str = ""
    ai_analysis_id: Optional[int] = None
    user_translation: Optional[str] = None
    translation_created_at: Optional[datetime] = None


@dataclass
class WordCardRecord:
    id: Optional[int]
    lemma: str
    surface_form: str
    lexical_type: LexicalType
    first_sentence_id: int
    current_meaning: str
    pos: str
    created_at: datetime
    last_reviewed_at: Optional[datetime]
    review_count: int
    mastery_state: MasteryState
    ef: float
    interval_days: int
    repetitions: int
    due_at: datetime
    occurrence_count: int = 1
    user_note: str = ""
    ai_analysis_id: Optional[int] = None


@dataclass
class ReviewLogRecord:
    id: Optional[int]
    card_type: CardType
    card_id: int
    reviewed_at: datetime
    quality: int                   # 0-5
    outcome: ReviewOutcome
    ef_before: float
    ef_after: float
    interval_before: int
    interval_after: int
    repetitions_before: int
    repetitions_after: int
    latency_ms: int


@dataclass
class AICacheRecord:
    id: Optional[int]
    content_hash: str
    prompt_version: str
    model: str
    response_json: str
    is_valid: bool
    created_at: datetime


@dataclass
class LearnerProfileSnapshot:
    id: Optional[int]
    created_at: datetime
    summary_md: str
    payload_json: str
    cards_at_snapshot: int
    sentences_at_snapshot: int


@dataclass
class PromptVersionRecord:
    id: Optional[int]
    name: str
    version: str
    body_md: str
    created_at: datetime
    is_active: bool
