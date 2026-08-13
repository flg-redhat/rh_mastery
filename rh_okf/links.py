"""Filename slugify and intra-guide link helpers."""

from __future__ import annotations

import hashlib
import re


def slugify(text: str, *, max_len: int = 80) -> str:
    """Lowercase ASCII slug; truncate with hash suffix when needed."""
    s = (text or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        s = "section"
    if len(s) <= max_len:
        return s
    digest = hashlib.sha256(s.encode()).hexdigest()[:8]
    trimmed = s[: max_len - len(digest) - 1].rstrip("-")
    return f"{trimmed}-{digest}"


def heading_anchor(title: str) -> str:
    """GitHub-style heading anchor (best effort)."""
    s = (title or "").lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s.strip("-")
