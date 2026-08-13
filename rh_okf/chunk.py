"""Markdown chunking for OKF concept files."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rh_okf.links import slugify


@dataclass(frozen=True)
class ConceptChunk:
    title: str | None
    body: str
    section_path: str | None
    filename: str
    chunk_part: int | None = None
    chunk_parts: int | None = None


def split_markdown_body(
    body: str,
    *,
    heading_level: int = 2,
    max_concept_chars: int = 12000,
) -> list[ConceptChunk]:
    """Split markdown body into OKF-sized concept chunks."""
    sections = _split_by_heading(body, heading_level)
    chunks: list[ConceptChunk] = []
    used_filenames: set[str] = set()

    for title, section_body in sections:
        display_title = title or "Overview"
        section_path = display_title if title else None
        parts = _apply_size_cap(section_body, max_concept_chars, heading_level + 1)
        base_slug = slugify(display_title)
        part_count = len(parts)

        for idx, part_body in enumerate(parts, start=1):
            part_title = display_title
            if part_count > 1:
                part_title = f"{display_title} (part {idx})"
            fname = base_slug if part_count == 1 else f"{base_slug}-part-{idx}"
            fname = _unique_filename(fname, used_filenames)
            used_filenames.add(fname)

            chunk_part = idx if part_count > 1 else None
            chunk_parts = part_count if part_count > 1 else None
            enriched_body = _add_part_crosslinks(
                part_body,
                base_slug=base_slug,
                part=idx,
                part_count=part_count,
                title=display_title,
            )
            chunks.append(
                ConceptChunk(
                    title=part_title if title else None,
                    body=enriched_body,
                    section_path=section_path,
                    filename=fname,
                    chunk_part=chunk_part,
                    chunk_parts=chunk_parts,
                )
            )
    return chunks


def _split_by_heading(body: str, level: int) -> list[tuple[str | None, str]]:
    prefix = "#" * level + " "
    deeper = "#" * (level + 1)
    chunks: list[tuple[str | None, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    preamble: list[str] = []
    in_fence = False

    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        is_target_heading = (
            not in_fence
            and line.startswith(prefix)
            and not line.startswith(deeper)
        )
        if is_target_heading:
            if current_title is not None:
                chunks.append((current_title, "".join(current_lines)))
            elif preamble or current_lines:
                chunks.append((None, "".join(preamble) + "".join(current_lines)))
            current_title = line[len(prefix) :].strip()
            current_lines = [line]
            preamble = []
            continue
        if current_title is None:
            preamble.append(line)
        else:
            current_lines.append(line)

    if current_title is not None:
        chunks.append((current_title, "".join(current_lines)))
    elif preamble:
        chunks.append((None, "".join(preamble)))
    elif body.strip():
        chunks.append((None, body))
    return chunks


def _apply_size_cap(text: str, max_chars: int, sub_heading_level: int) -> list[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    sub = _split_by_heading(text, sub_heading_level)
    if len(sub) > 1:
        parts: list[str] = []
        for _title, sub_body in sub:
            parts.extend(_apply_size_cap(sub_body, max_chars, sub_heading_level + 1))
        if all(len(p) <= max_chars for p in parts):
            return parts

    para_parts = _split_by_paragraphs(text)
    if len(para_parts) > 1:
        merged: list[str] = []
        buf = ""
        for p in para_parts:
            candidate = f"{buf}\n\n{p}".strip() if buf else p
            if len(candidate) <= max_chars:
                buf = candidate
            else:
                if buf:
                    merged.append(buf)
                if len(p) > max_chars:
                    merged.extend(_hard_split(p, max_chars))
                    buf = ""
                else:
                    buf = p
        if buf:
            merged.append(buf)
        if len(merged) > 1:
            return merged

    return _hard_split(text, max_chars)


def _split_by_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text.strip())
    return [p for p in parts if p.strip()]


def _hard_split(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        out.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        out.append(remaining)
    return out or [text]


def _add_part_crosslinks(
    body: str,
    *,
    base_slug: str,
    part: int,
    part_count: int,
    title: str,
) -> str:
    if part_count <= 1:
        return body
    links: list[str] = []
    if part > 1:
        prev = f"{base_slug}-part-{part - 1}.md"
        links.append(f"Continued from [{title} (part {part - 1})](./{prev}).")
    if part < part_count:
        nxt = f"{base_slug}-part-{part + 1}.md"
        links.append(f"Continued in [{title} (part {part + 1})](./{nxt}).")
    if not links:
        return body
    return body.rstrip() + "\n\n" + "\n\n".join(links) + "\n"


def _unique_filename(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    n = 2
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"
