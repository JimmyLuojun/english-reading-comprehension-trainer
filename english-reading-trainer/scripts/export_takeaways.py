"""Export all user takeaways with sentence context and optional AI suggestion.

Usage:
    .venv/bin/python scripts/export_takeaways.py [--format text|json] [--output FILE]

Output formats:
    text  (default) — readable, paste-ready for AI analysis
    json            — structured, easier to post-process programmatically

The AI suggestion field (takeaway_suggestion) comes from the cached LLM response.
It is omitted when no analysis has been run for that sentence.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "reading_trainer.db"

_QUERY = """
SELECT
    sc.sentence_id,
    s.text            AS sentence,
    sc.user_note,
    sc.created_at,
    sc.last_reviewed_at,
    sc.review_count,
    ac.response_json  AS analysis_json
FROM sentence_cards sc
JOIN sentences s ON s.id = sc.sentence_id
LEFT JOIN ai_cache ac ON ac.id = sc.ai_analysis_id
WHERE sc.user_note != ''
ORDER BY sc.created_at
"""


def _extract_suggestion(response_json: str | None) -> str:
    if not response_json:
        return ""
    try:
        data = json.loads(response_json)
        return data.get("takeaway_suggestion", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


def export_text(rows: list[dict], out) -> None:
    out.write(f"# Takeaway Export — {datetime.now().strftime('%Y-%m-%d')}\n")
    out.write(f"# Total entries: {len(rows)}\n\n")
    for i, row in enumerate(rows, 1):
        suggestion = _extract_suggestion(row["analysis_json"])
        out.write(f"--- [{i}] sentence_id={row['sentence_id']} ---\n")
        out.write(f"原句: {row['sentence']}\n")
        out.write(f"我的takeaway: {row['user_note']}\n")
        if suggestion:
            out.write(f"AI建议: {suggestion}\n")
        reviews = row["review_count"]
        last = row["last_reviewed_at"] or "未复习"
        out.write(f"复习次数: {reviews}  最近复习: {last}\n")
        out.write("\n")


def export_json(rows: list[dict], out) -> None:
    records = []
    for row in rows:
        records.append({
            "sentence_id": row["sentence_id"],
            "sentence": row["sentence"],
            "user_note": row["user_note"],
            "ai_suggestion": _extract_suggestion(row["analysis_json"]),
            "created_at": row["created_at"],
            "last_reviewed_at": row["last_reviewed_at"],
            "review_count": row["review_count"],
        })
    json.dump(records, out, ensure_ascii=False, indent=2)
    out.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", "-o", help="Output file path (default: stdout)")
    parser.add_argument("--db", default=os.environ.get("TRAINER_DB", str(_DEFAULT_DB)))
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(_QUERY).fetchall()]
    con.close()

    if not rows:
        print("No takeaways found (user_note is empty for all cards).", file=sys.stderr)
        return 0

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            if args.format == "json":
                export_json(rows, f)
            else:
                export_text(rows, f)
        print(f"Exported {len(rows)} takeaways → {args.output}", file=sys.stderr)
    else:
        if args.format == "json":
            export_json(rows, sys.stdout)
        else:
            export_text(rows, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
