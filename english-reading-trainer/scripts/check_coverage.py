"""Enforce the project's per-module and critical-module coverage policy."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


_MINIMUM_MODULE_COVERAGE = 0.97
_CRITICAL_MODULES = {
    "ai/ai_response_cache.py",
    "ai/json_output_validator.py",
    "review/sm2_scheduler.py",
}


def coverage_failures(coverage_path: Path) -> list[str]:
    """Return policy failures from a Cobertura XML coverage report."""
    root = ET.parse(coverage_path).getroot()
    failures: list[str] = []
    seen: set[str] = set()
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename", "")
        if not filename or filename in seen or filename.endswith("/__init__.py"):
            continue
        seen.add(filename)
        coverage = float(class_node.attrib.get("line-rate", "0"))
        minimum = 1.0 if filename in _CRITICAL_MODULES else _MINIMUM_MODULE_COVERAGE
        if coverage < minimum:
            failures.append(
                f"{filename}: {coverage:.2%} below required {minimum:.0%}"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_xml", type=Path)
    args = parser.parse_args(argv)
    failures = coverage_failures(args.coverage_xml)
    if failures:
        print("Per-module coverage policy failed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Per-module coverage policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
