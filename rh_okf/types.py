"""OKF concept type heuristics."""

from __future__ import annotations

import re

_PROCEDURE_HEADING = re.compile(
    r"(?i)^(install|configure|deploy|upgrade|migrate|backup|restore|"
    r"uninstall|remove|enable|disable|set up|creating)\b"
)
_REFERENCE_HEADING = re.compile(
    r"(?i)(reference|parameters|options|syntax|api|commands|configuration)"
)
_RELEASE_HEADING = re.compile(r"(?i)(release notes|what's new|changelog)")


def infer_concept_type(title: str | None, body: str) -> str:
    """Return OKF type string for a section chunk."""
    t = (title or "").strip()
    if _RELEASE_HEADING.search(t):
        return "Release Note"
    if _PROCEDURE_HEADING.search(t):
        return "Procedure"
    if _REFERENCE_HEADING.search(t):
        return "Reference"
    if _table_ratio(body) > 0.4:
        return "Reference"
    if _ordered_list_items(body) >= 3 and _PROCEDURE_HEADING.search(body[:500]):
        return "Procedure"
    if _ordered_list_items(body) >= 3:
        return "Procedure"
    return "Concept"


def _table_ratio(body: str) -> float:
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if not lines:
        return 0.0
    table_lines = sum(1 for ln in lines if ln.strip().startswith("|"))
    return table_lines / len(lines)


def _ordered_list_items(body: str) -> int:
    return len(re.findall(r"(?m)^\s*\d+\.\s+", body or ""))
