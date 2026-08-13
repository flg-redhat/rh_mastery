"""OKF log.md writers."""

from __future__ import annotations

import os
from datetime import date
from typing import Sequence


def append_log_entries(
    log_path: str,
    entries: Sequence[str],
    *,
    force_rewrite_today: bool = False,
) -> None:
    """Append dated log entries; create file if missing."""
    today = date.today().isoformat()
    section_header = f"## {today}"
    existing = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            existing = f.read()

    if not existing.strip():
        body = "# Directory Update Log\n\n" + section_header + "\n"
        for e in entries:
            body += f"* {e}\n"
        body += "\n"
    elif section_header in existing and force_rewrite_today:
        body = _replace_today_section(existing, section_header, entries)
    elif section_header in existing:
        body = _append_to_today_section(existing, section_header, entries)
    else:
        body = existing.rstrip() + "\n\n" + section_header + "\n"
        for e in entries:
            body += f"* {e}\n"
        body += "\n"

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(body)


def _append_to_today_section(text: str, header: str, entries: Sequence[str]) -> str:
    lines = text.splitlines()
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.strip() == header and not inserted:
            for e in entries:
                out.append(f"* {e}")
            inserted = True
    if not inserted:
        out.append("")
        out.append(header)
        for e in entries:
            out.append(f"* {e}")
    return "\n".join(out) + "\n"


def _replace_today_section(text: str, header: str, entries: Sequence[str]) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_today = False
    for line in lines:
        if line.strip() == header:
            in_today = True
            out.append(line)
            for e in entries:
                out.append(f"* {e}")
            continue
        if in_today and line.startswith("## ") and line.strip() != header:
            in_today = False
        if not in_today:
            out.append(line)
    return "\n".join(out) + "\n"
