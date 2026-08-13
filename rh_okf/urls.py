"""docs.redhat.com URL construction."""

from __future__ import annotations

import re


def guide_resource_url(base_url: str, slug: str, version: str, guide_stem: str) -> str:
    """
    Best-effort canonical guide URL.

    Strips common ``-pdf`` suffix from stem and maps to html path segment.
    """
    base = (base_url or "https://docs.redhat.com/en/documentation").rstrip("/")
    topic = re.sub(r"-pdf$", "", guide_stem, flags=re.IGNORECASE)
    topic = re.sub(r"[-_]+", "_", topic)
    return f"{base}/{slug}/{version}/html/{topic}/"
