"""OKF bundle orchestration: Markdown → concept files + indexes."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from rh_okf.chunk import ConceptChunk, split_markdown_body
from rh_okf.frontmatter import first_sentence, wrap_concept
from rh_okf.index import render_global_index, render_guide_index, render_product_index
from rh_okf.log import append_log_entries
from rh_okf.types import infer_concept_type
from rh_okf.urls import guide_resource_url

MANIFEST_NAME = ".rh-okf-manifest.json"


def parse_md_file(path: str) -> tuple[dict[str, Any], str]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    meta: dict[str, Any] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        val = val.strip()
        try:
            meta[key.strip()] = json.loads(val)
        except json.JSONDecodeError:
            meta[key.strip()] = val.strip('"')
    return meta, parts[2].lstrip("\n")


def settings_hash(chunk_heading_level: int, max_concept_chars: int, okf_spec_version: str) -> str:
    payload = json.dumps(
        {
            "chunk_heading_level": chunk_heading_level,
            "max_concept_chars": max_concept_chars,
            "okf_spec_version": okf_spec_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _rel_path(from_dir: str, to_path: str) -> str:
    return os.path.relpath(os.path.abspath(to_path), start=os.path.abspath(from_dir)).replace(
        os.sep, "/"
    )


def _read_manifest(guide_dir: str) -> dict[str, Any] | None:
    path = os.path.join(guide_dir, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_manifest(guide_dir: str, data: dict[str, Any]) -> None:
    path = os.path.join(guide_dir, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _should_skip_okf(
    guide_dir: str,
    md_path: str,
    *,
    chunk_heading_level: int,
    max_concept_chars: int,
    okf_spec_version: str,
    force: bool,
) -> bool:
    if force:
        return False
    manifest = _read_manifest(guide_dir)
    if not manifest:
        return False
    expected = settings_hash(chunk_heading_level, max_concept_chars, okf_spec_version)
    if manifest.get("settings_hash") != expected:
        return False
    if manifest.get("source_md_sha256") != file_sha256(md_path):
        return False
    return os.path.isdir(guide_dir) and bool(manifest.get("concept_count"))


def _clear_guide_concepts(guide_dir: str) -> None:
    if not os.path.isdir(guide_dir):
        return
    for name in os.listdir(guide_dir):
        if name == MANIFEST_NAME:
            continue
        if name.endswith(".md"):
            os.remove(os.path.join(guide_dir, name))


def _build_sources(
    *,
    guide_dir: str,
    md_path: str,
    pdf_path: str | None,
    md_meta: dict[str, Any],
    resource_url: str,
) -> list[dict[str, Any]]:
    converted_at = str(md_meta.get("converted_at", ""))
    last_modified = converted_at[:10] if len(converted_at) >= 10 else ""
    title = str(md_meta.get("title", os.path.basename(md_path)))
    sources: list[dict[str, Any]] = [
        {
            "id": "source-md",
            "resource": _rel_path(guide_dir, md_path),
            "title": title,
        },
    ]
    if last_modified:
        sources[0]["last_modified"] = last_modified
    if pdf_path and os.path.exists(pdf_path):
        sources.append(
            {
                "id": "source-pdf",
                "resource": _rel_path(guide_dir, pdf_path),
                "title": os.path.basename(pdf_path),
            }
        )
    sources.append(
        {
            "id": "source-web",
            "resource": resource_url,
            "title": "Red Hat documentation (online)",
        }
    )
    return sources


def _concept_fields(
    *,
    concept_type: str,
    title: str,
    description: str,
    resource_url: str,
    tags: list[str],
    generated_at: str,
    sources: list[dict[str, Any]],
    slug: str,
    version: str,
    guide_stem: str,
    engine: str,
    section_path: str | None,
    md_path: str,
    guide_dir: str,
    chunk: ConceptChunk | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "type": concept_type,
        "title": title,
        "description": description,
        "resource": resource_url,
        "tags": tags,
        "generated": {"by": "process:rh-mastery", "at": generated_at},
        "status": "stable",
        "sources": sources,
        "slug": slug,
        "version": version,
        "guide_stem": guide_stem,
        "engine": engine,
        "rh_source_md": _rel_path(guide_dir, md_path),
    }
    if section_path:
        fields["rh_section_path"] = section_path
    if chunk and chunk.chunk_part is not None:
        fields["rh_chunk_policy"] = "overflow-split"
        fields["rh_chunk_part"] = chunk.chunk_part
        fields["rh_chunk_parts"] = chunk.chunk_parts
    return fields


def build_guide_bundle(
    md_path: str,
    *,
    bundle_root: str,
    slug: str,
    version: str,
    guide_stem: str,
    base_url: str,
    pdf_path: str | None = None,
    chunk_heading_level: int = 2,
    max_concept_chars: int = 12000,
    okf_spec_version: str = "0.2",
    force: bool = False,
) -> dict[str, Any]:
    """
    Build OKF concepts for one guide Markdown file.

    Returns metadata dict with keys: guide_stem, title, description, concept_count, paths.
    """
    md_meta, body = parse_md_file(md_path)
    guide_dir = os.path.join(bundle_root, slug, version, guide_stem)
    os.makedirs(guide_dir, exist_ok=True)

    if _should_skip_okf(
        guide_dir,
        md_path,
        chunk_heading_level=chunk_heading_level,
        max_concept_chars=max_concept_chars,
        okf_spec_version=okf_spec_version,
        force=force,
    ):
        manifest = _read_manifest(guide_dir) or {}
        return {
            "guide_stem": guide_stem,
            "title": str(md_meta.get("title", guide_stem)),
            "description": first_sentence(body),
            "concept_count": manifest.get("concept_count", 0),
            "paths": [],
            "skipped": True,
        }

    _clear_guide_concepts(guide_dir)

    title = str(md_meta.get("title", guide_stem))
    engine = str(md_meta.get("engine", "pymupdf"))
    generated_at = str(
        md_meta.get("converted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    resource_url = guide_resource_url(base_url, slug, version, guide_stem)
    tags = [slug, version, guide_stem]
    sources = _build_sources(
        guide_dir=guide_dir,
        md_path=md_path,
        pdf_path=pdf_path,
        md_meta=md_meta,
        resource_url=resource_url,
    )

    chunks = split_markdown_body(
        body,
        heading_level=chunk_heading_level,
        max_concept_chars=max_concept_chars,
    )

    written: list[str] = []
    index_entries: list[dict[str, Any]] = []

    preamble = ""
    if chunks and chunks[0].title is None:
        preamble = chunks[0].body

    guide_desc = first_sentence(preamble or body)
    guide_body = preamble.strip() or (
        f"This guide covers **{title}**. See [index.md](./index.md) for all sections."
    )
    guide_fields = _concept_fields(
        concept_type="Documentation Guide",
        title=title,
        description=guide_desc or title,
        resource_url=resource_url,
        tags=tags,
        generated_at=generated_at,
        sources=sources,
        slug=slug,
        version=version,
        guide_stem=guide_stem,
        engine=engine,
        section_path=None,
        md_path=md_path,
        guide_dir=guide_dir,
    )
    guide_path = os.path.join(guide_dir, "guide.md")
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(wrap_concept(guide_fields, guide_body))
    written.append(guide_path)

    concept_chunks = [c for c in chunks if c.title is not None]
    if (
        not concept_chunks
        and len(chunks) == 1
        and chunks[0].title is None
    ):
        concept_chunks = []
    elif not concept_chunks and chunks:
        concept_chunks = chunks

    for chunk in concept_chunks:
        section_title = chunk.title or title
        concept_type = infer_concept_type(section_title, chunk.body)
        desc = first_sentence(chunk.body) or section_title
        fields = _concept_fields(
            concept_type=concept_type,
            title=section_title,
            description=desc,
            resource_url=resource_url,
            tags=tags + [concept_type.lower().replace(" ", "-")],
            generated_at=generated_at,
            sources=sources,
            slug=slug,
            version=version,
            guide_stem=guide_stem,
            engine=engine,
            section_path=chunk.section_path,
            md_path=md_path,
            guide_dir=guide_dir,
            chunk=chunk,
        )
        out_path = os.path.join(guide_dir, f"{chunk.filename}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(wrap_concept(fields, chunk.body.strip()))
        written.append(out_path)
        index_entries.append(
            {
                "title": section_title,
                "description": desc,
                "filename": chunk.filename,
                "type": concept_type,
            }
        )

    index_path = os.path.join(guide_dir, "index.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(render_guide_index(index_entries))

    manifest = {
        "source_md_sha256": file_sha256(md_path),
        "concept_count": len(index_entries),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "settings_hash": settings_hash(chunk_heading_level, max_concept_chars, okf_spec_version),
        "okf_spec_version": okf_spec_version,
    }
    _write_manifest(guide_dir, manifest)

    return {
        "guide_stem": guide_stem,
        "title": title,
        "description": guide_desc or title,
        "concept_count": len(index_entries),
        "paths": written,
        "skipped": False,
        "engine": engine,
    }


def build_product_index(
    bundle_root: str,
    slug: str,
    version: str,
    guides: list[dict[str, Any]],
) -> str:
    product_dir = os.path.join(bundle_root, slug, version)
    os.makedirs(product_dir, exist_ok=True)
    index_path = os.path.join(product_dir, "index.md")
    content = render_product_index(slug, version, guides)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    return index_path


def build_global_index(
    bundle_root: str,
    products: list[dict[str, Any]],
    *,
    okf_spec_version: str = "0.2",
) -> str:
    os.makedirs(bundle_root, exist_ok=True)
    index_path = os.path.join(bundle_root, "index.md")
    content = render_global_index(products, okf_version=okf_spec_version)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    return index_path


def write_product_log(
    bundle_root: str,
    slug: str,
    version: str,
    guides: list[dict[str, Any]],
    *,
    force: bool = False,
) -> None:
    log_path = os.path.join(bundle_root, slug, version, "log.md")
    entries = []
    for g in guides:
        if g.get("skipped"):
            continue
        stem = g["guide_stem"]
        n = g.get("concept_count", 0)
        eng = g.get("engine", "unknown")
        entries.append(
            f"**Update**: Rebuilt OKF concepts for [{g.get('title', stem)}]({stem}/guide.md) "
            f"({n} concepts, engine={eng})."
        )
    if entries:
        append_log_entries(log_path, entries, force_rewrite_today=force)


def write_global_log(
    bundle_root: str,
    products: list[dict[str, Any]],
    *,
    force: bool = False,
) -> None:
    log_path = os.path.join(bundle_root, "log.md")
    entries = []
    for p in products:
        slug = p["slug"]
        version = p["version"]
        guide_count = len(p.get("guides", []))
        entries.append(
            f"**Update**: OKF bundle for {slug}/{version} ({guide_count} guide(s))."
        )
    if entries:
        append_log_entries(log_path, entries, force_rewrite_today=force)
