"""OKF index.md generators."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence


def render_guide_index(concepts: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Sections", ""]
    for c in concepts:
        title = c.get("title") or c.get("filename", "Section")
        desc = c.get("description") or c.get("type", "")
        fname = c.get("filename", "section")
        lines.append(f"* [{title}]({fname}.md) — {desc}")
    lines.append("")
    return "\n".join(lines)


def render_product_index(
    slug: str,
    version: str,
    guides: Sequence[Mapping[str, Any]],
) -> str:
    heading = f"# {slug.replace('_', ' ').title()} {version}"
    lines = [heading, ""]
    for g in guides:
        stem = g["guide_stem"]
        title = g.get("title") or stem
        desc = g.get("description") or f"Documentation guide ({g.get('concept_count', 0)} concepts)"
        lines.append(f"* [{title}]({stem}/guide.md) — {desc}")
    lines.append("")
    return "\n".join(lines)


def render_global_index(
    products: Sequence[Mapping[str, Any]],
    *,
    okf_version: str = "0.2",
) -> str:
    fm = f"---\nokf_version: {json.dumps(okf_version)}\n---\n\n"
    lines = ["# Red Hat Documentation OKF Bundle", ""]
    for p in products:
        slug = p["slug"]
        version = p["version"]
        label = f"{slug.replace('_', ' ').title()} {version}"
        lines.append(f"* [{label}]({slug}/{version}/index.md)")
    lines.append("")
    return fm + "\n".join(lines)
