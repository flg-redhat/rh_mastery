# rh-mastery OKF conversion — implementation specification

**Status:** Planning (handover-ready)  
**Target OKF version:** [0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)  
**Primary CLI surface:** `rh-mastery convert --format okf`  
**Repository:** `/git/infrastructure/containers/rh_mastery`

---

## 1. Executive summary

rh-mastery today mirrors Red Hat documentation PDFs and converts them to Markdown (`convert`). This specification adds an **OKF (Open Knowledge Format) bundle** output mode that structures those Markdown files into agent-consumable knowledge bundles.

**Core workflow (always two steps, single command):**

```
PDF  ──convert──►  Markdown (reference, permanent)  ──structure──►  OKF bundle
```

`convert --format okf` **must always produce or refresh Markdown first**, then derive the OKF bundle from that Markdown. Markdown remains the canonical human-readable extraction artifact; OKF is the structured agent-facing layer.

---

## 2. Goals and non-goals

### Goals

1. Add `--format okf` to the existing `convert` subcommand without breaking current behavior (`--format markdown` remains default).
2. Emit **OKF v0.2-conformant** bundles suitable for agent graph traversal and RAG indexing.
3. Support **two bundle attachment scopes** from one write tree:
   - **Global:** entire mirrored corpus
   - **Per-product/version:** single product at a pinned version
4. Preserve **external docs.redhat.com URLs** in link targets (source fidelity).
5. Use **docling** as the default PDF engine when `--format okf` (better structure for chunking).
6. Keep **Markdown forever** under `settings.markdown_subdir` as the reference extraction layer.

### Non-goals (this phase)

- LLM-based semantic enrichment or cross-guide link inference
- Replacing vector RAG (OKF complements retrieval)
- Attested Computation concepts (`type: Attested Computation`)
- Human `verified` attestation workflows
- Changing `tokensaver/` (remains independent)
- Modifying `sync` behavior beyond optional post-sync automation docs

---

## 3. Stakeholder decisions (resolved)

| # | Question | Decision |
|---|----------|----------|
| 1 | Bundle scope | **Both** global and per-product/version scopes are required. Implemented as one directory tree with two valid attachment roots (see §5). |
| 2 | External links | **Keep original** `https://docs.redhat.com/...` URLs in markdown bodies. Do not rewrite to bundle-relative paths for off-bundle targets. |
| 3 | Chunk size cap | Apply **producer-side caps** where necessary for RAG/embeddings. OKF spec defines **no maximum concept size** (see §6.3). |
| 4 | PDF engine for OKF | **docling** is the default when `--format okf`. |
| 5 | Markdown retention | **Keep forever** under `{slug}/{version}/markdown/` as reference; never delete when emitting OKF. |

---

## 4. CLI design

### 4.1 New argument

Add to the `convert` subparser:

```
--format {markdown,okf}
    Output format (default: markdown).
    markdown — write .md only (current behavior).
    okf      — write .md first, then build OKF bundle from those files.
```

### 4.2 Engine default interaction

| `--format` | Default `--engine` | Override |
|------------|-------------------|----------|
| `markdown` | `pymupdf` | `--engine docling` |
| `okf` | `docling` | `--engine pymupdf` |

Implementation: when `args.format == "okf"` and the user did not explicitly pass `--engine`, set `engine = "docling"`.

Use `argparse` pattern: `default=None` on `--engine`, resolve in `run_convert()`:

```python
engine = args.engine
if engine is None:
    engine = "docling" if fmt == "okf" else "pymupdf"
```

### 4.3 Examples

```bash
# Current behavior unchanged
rh-mastery convert --ansible
rh-mastery convert --ansible --format markdown

# OKF: MD + bundle (docling by default)
rh-mastery convert --ansible --format okf

# OKF with pymupdf extraction
rh-mastery convert --ansible --format okf --engine pymupdf

# Force rebuild MD and OKF
rh-mastery convert --all --format okf --force
```

### 4.4 `--force` semantics

| Artifact | Without `--force` | With `--force` |
|----------|-------------------|----------------|
| `{slug}/{version}/markdown/{stem}.md` | Skip if exists | Overwrite |
| OKF concepts under bundle | Skip guide if manifest hash unchanged | Rebuild all concepts for selected products |
| `index.md` / `log.md` | Regenerate if any child changed | Always regenerate |

**Order of operations per PDF:**

1. Convert PDF → Markdown (respect `--force` for `.md`)
2. If `--format okf`: structure Markdown → OKF concepts (respect `--force` for OKF)

If `--format okf` and Markdown exists but OKF is missing, **always build OKF** even without `--force`.

### 4.5 Help text and epilog

Update `convert` parser help, root epilog examples, and `README.md` with `--format okf` examples.

---

## 5. Directory layout and bundle scopes

### 5.1 Storage paths (unchanged for PDF + MD)

```
{download_base}/
  {slug}/
    {version}/
      *.pdf
      markdown/
        {stem}.md          # permanent reference extraction
```

`download_base` resolution is unchanged (`rh_storage.json` → `resolve_download_base()`).

### 5.2 OKF bundle tree (single write, dual scope)

**Bundle root:** `{download_base}/okf/`

```
{download_base}/okf/
  index.md                           # global catalog (okf_version: "0.2")
  log.md                             # global update log
  {slug}/
    {version}/
      index.md                       # product-version catalog
      log.md
      {guide_stem}/                  # one directory per source PDF/MD
        index.md                     # section listing for this guide
        guide.md                     # type: Documentation Guide (overview stub)
        {concept_slug}.md            # one OKF concept per chunk
        ...
```

### 5.3 Attachment scopes

| Scope | Agent attaches | Use case |
|-------|----------------|----------|
| **Global** | `{download_base}/okf/` | Cross-product agents, NotebookLM-style corpus |
| **Per-product** | `{download_base}/okf/{slug}/{version}/` | Product-specific assistant (e.g. AAP 2.7 only) |

Both scopes are conformant OKF bundles (each subtree has `index.md`; version subtree is self-contained).

### 5.4 Concept ID (OKF)

Concept ID = path within bundle without `.md` suffix, relative to the attachment root.

Examples (global root):

- `red_hat_ansible_automation_platform/2.7/aap-install-2-7/installing-the-controller`
- `red_hat_quay/3.18/quay-config-3-18/system-requirements`

---

## 6. OKF conformance and chunking policy

### 6.1 OKF v0.2 hard requirements

Every non-reserved `.md` file must have:

- Parseable YAML frontmatter (`---` delimited)
- Non-empty `type` field

Reserved files: `index.md`, `log.md` (structure per spec §8–§9).

Declare bundle version in **global** root only:

```yaml
---
okf_version: "0.2"
---
```

(body: global product listing)

### 6.2 OKF guidance relevant to chunking

The OKF specification **does not define**:

- Maximum file size, token count, or character limit per concept
- Required chunking strategy
- Mandatory heading depth for splits

Relevant **soft guidance** from the spec:

- **One concept = one file**; directory hierarchy is producer-defined.
- Bodies should favor **structural markdown** (headings, lists, tables, code fences).
- **`index.md`** enables progressive disclosure — smaller concepts improve agent browsing.
- Consumers **must not reject** bundles for broken links, missing optional fields, or unknown types.
- Cross-links use markdown links; relationship semantics live in prose, not link type.

**Conclusion:** chunk size caps are an **rh-mastery producer policy** for RAG efficiency, not an OKF conformance rule. Document chosen limits in config and frontmatter metadata.

### 6.3 rh-mastery chunking policy (normative for this project)

#### Primary split: headings

- Default split level: **`##` (h2)** — configurable via `settings.okf_chunk_heading_level` (default `2`).
- Never split inside fenced code blocks.
- Each chunk inherits parent heading context in `description` or a breadcrumb field `rh_section_path` (extension key, preserved by OKF consumers).

#### Overflow split (when primary chunk exceeds cap)

Apply in order:

1. Sub-split on `###` (h3) within the oversized section.
2. Sub-split on blank-line paragraph boundaries.
3. Hard split at character boundary with suffix `-part-2`, `-part-3`, … and cross-links between parts:

   ```markdown
   Continued in [Installing the controller (part 2)](./installing-the-controller-part-2.md).
   ```

#### Default size cap

| Setting | Default | Purpose |
|---------|---------|---------|
| `settings.okf_max_concept_chars` | `12000` | ~3k tokens; safe for common embedding models |
| `settings.okf_max_concept_chars` | `0` | Disable cap (heading-only chunking) |

Record split reason in extension frontmatter when overflow splitting occurs:

```yaml
rh_chunk_policy: overflow-split
rh_chunk_part: 2
rh_chunk_parts: 3
```

#### Per-guide wrapper concept

Each `{guide_stem}/guide.md`:

```yaml
type: Documentation Guide
title: <from MD frontmatter title>
description: <first non-empty paragraph or auto-summary, max 240 chars>
resource: <docs.redhat.com URL>
```

Body: guide abstract (content before first h2) or minimal placeholder linking to `index.md`.

---

## 7. Concept type taxonomy

OKF does not register types centrally. rh-mastery uses:

| `type` | Detection heuristic |
|--------|---------------------|
| `Documentation Guide` | `guide.md` wrapper only |
| `Procedure` | Heading matches `(?i)^(install\|configure\|deploy\|upgrade\|migrate\|backup\|restore\|uninstall\|remove\|enable\|disable\|set up\|creating)` OR body contains ordered list with ≥3 items |
| `Reference` | Body is >40% table lines OR heading matches `(?i)(reference\|parameters\|options\|syntax\|api\|commands\|configuration)` |
| `Release Note` | Heading matches `(?i)(release notes\|what's new\|changelog)` |
| `Concept` | Default fallback |

Consumers must tolerate unknown types (OKF §11).

---

## 8. Frontmatter schema (per concept)

### 8.1 Required

```yaml
type: <taxonomy value>
```

### 8.2 Recommended (OKF v0.2)

```yaml
title: <section title>
description: <one sentence, max 240 chars>
resource: <canonical docs.redhat.com URL for this guide>
tags: [<slug>, <version>, <guide_stem>, ...]
```

### 8.3 Provenance and trust (OKF v0.2)

```yaml
generated:
  by: process:rh-mastery
  at: <ISO 8601 UTC, same as MD converted_at>
status: stable
sources:
  - id: source-md
    resource: <bundle-relative path to markdown reference>
    title: <MD title>
    last_modified: <YYYY-MM-DD from converted_at>
  - id: source-pdf
    resource: <bundle-relative path to PDF OR absolute path if outside okf tree>
    title: <PDF filename>
  - id: source-web
    resource: <https://docs.redhat.com/en/documentation/{slug}/{version}/html/...>
    title: Red Hat documentation (online)
```

Use **bundle-relative** paths for `sources[].resource` when pointing at mirrored artifacts inside `{download_base}`:

```yaml
resource: ../../../red_hat_ansible_automation_platform/2.7/markdown/aap-install-2-7-pdf.md
```

### 8.4 rh-mastery extension keys (preserve on round-trip)

```yaml
slug: <product slug>
version: <doc version>
guide_stem: <pdf/md stem>
engine: <pymupdf|docling>
rh_section_path: <breadcrumb, e.g. "Chapter 3 > Installing the controller">
rh_source_md: <relative path from concept to source .md>
```

### 8.5 Legacy MD frontmatter (unchanged)

Markdown files keep existing fields:

```yaml
title, source_pdf, converted_at, engine, slug, version
```

OKF generation reads but does not mutate source MD (unless `--force` re-converts from PDF).

---

## 9. URL and link policy

### 9.1 `resource` field

Construct canonical guide URL from config:

```
{settings.base_url}/{slug}/{version}/html/{topic_path}/
```

**Topic path derivation** (best effort):

1. Parse from PDF filename / MD stem (e.g. `aap-install-2-7-pdf` → `installing` patterns in Red Hat URL scheme).
2. Fallback: `{base_url}/{slug}/{version}/pdf/{stem}` → redirect-following optional (future); if unavailable, use portal product page + tag metadata.

Store constructed URL even if approximate; prefer stability over perfection in v1.

### 9.2 In-body links

- **Do not rewrite** `https://docs.redhat.com/...` or other external URLs.
- **Do rewrite** only intra-guide anchor links (`#section`) to sibling concept files when the target section was split into another concept file.
- **Bundle-relative** links (`/slug/version/guide/concept.md`) for intra-bundle navigation between concepts in the **same** guide.

---

## 10. `index.md` and `log.md` generation

### 10.1 `index.md` (auto-generated, no `type` frontmatter except global root)

Hierarchy:

1. `{download_base}/okf/index.md` — lists `{slug}/{version}/` entries with descriptions from product metadata.
2. `{download_base}/okf/{slug}/{version}/index.md` — lists guide directories.
3. `{download_base}/okf/{slug}/{version}/{guide_stem}/index.md` — lists concept files with `description` from frontmatter.

Entry format (OKF §8):

```markdown
# Red Hat Ansible Automation Platform 2.7

* [Installation Guide](aap-install-2-7/guide.md) — Install and configure AAP 2.7
* [Upgrading](aap-install-2-7/upgrading.md) — Procedure
```

### 10.2 `log.md` (append/update on rebuild)

Format per OKF §9. Write one entry per convert run affecting that scope:

```markdown
# Directory Update Log

## 2026-08-13
* **Update**: Rebuilt OKF concepts for [Installation Guide](aap-install-2-7/guide.md) (47 concepts, engine=docling).
* **Creation**: Initial OKF bundle for red_hat_ansible_automation_platform/2.7.
```

---

## 11. Configuration (`rh_config.json`)

Add under `settings`:

```json
{
  "settings": {
    "markdown_subdir": "markdown",
    "okf_bundle_root": "okf",
    "okf_chunk_heading_level": 2,
    "okf_max_concept_chars": 12000,
    "okf_spec_version": "0.2"
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `okf_bundle_root` | `"okf"` | Subdirectory of `download_base` for bundle root |
| `okf_chunk_heading_level` | `2` | Heading level for primary splits (2=`##`, 3=`###`) |
| `okf_max_concept_chars` | `12000` | Overflow split threshold; `0` disables |
| `okf_spec_version` | `"0.2"` | Written to global `index.md` as `okf_version` |

---

## 12. Code architecture

### 12.1 New package: `rh_okf/`

Keep OKF logic out of the monolithic `rh_mastery.py` where practical.

```
rh_okf/
  __init__.py
  bundle.py       # orchestration: md path → concept files + indexes
  chunk.py        # heading/overflow splitting
  frontmatter.py  # OKF v0.2 field builders
  index.py        # index.md generators (3 levels)
  links.py        # anchor rewrite, slugify filenames
  log.py          # log.md writers
  types.py        # concept type heuristics
  urls.py         # docs.redhat.com resource URL builder
```

### 12.2 Changes to `rh_mastery.py`

| Function / area | Change |
|-----------------|--------|
| `run_convert()` | Accept `format`; branch after MD phase into `run_okf_from_markdown()` |
| `_build_argparser()` | Add `--format`; adjust `--engine` default resolution |
| `convert_pdf_file()` | No change (MD output unchanged) |
| New `run_okf_from_markdown(master, args, slug, ver, md_paths)` | Drive OKF build per product version |

### 12.3 Public API (for tests)

```python
# rh_okf/bundle.py
def build_guide_bundle(
    md_path: str,
    *,
    bundle_root: str,
    slug: str,
    version: str,
    guide_stem: str,
    base_url: str,
    chunk_heading_level: int = 2,
    max_concept_chars: int = 12000,
    force: bool = False,
) -> list[str]:  # paths written
    ...

def build_product_index(bundle_root, slug, version, guides) -> str: ...
def build_global_index(bundle_root, products) -> str: ...
```

### 12.4 Slugify rules for concept filenames

- Lowercase, ASCII
- Replace non-alphanumeric with `-`
- Collapse repeated `-`
- Max length 80 chars (truncate with hash suffix if needed)
- Example: `## Installing Red Hat Ansible Automation Platform` → `installing-red-hat-ansible-automation-platform.md`

---

## 13. Processing algorithm

### 13.1 Per-product-version loop (extends existing `run_convert`)

```
for slug in selected_slugs:
    ver = resolve_version(slug)
    for pdf_path in enumerate_pdfs(base, slug, ver):
        md_path = {base}/{slug}/{ver}/markdown/{stem}.md

        # Phase 1 — Markdown (always for --format okf; only output for --format markdown)
        if not md_path.exists() or force:
            convert_pdf_file(pdf_path, md_path, engine=engine, ...)

        # Phase 2 — OKF (only if format == okf)
        if format == okf:
            build_guide_bundle(
                md_path,
                bundle_root={base}/okf,
                slug=slug, version=ver, guide_stem=stem,
                ...
            )

    if format == okf:
        build_product_index(...)
        append_product_log(...)

if format == okf:
    build_global_index(...)
    append_global_log(...)
```

### 13.2 Incremental skip (OKF)

Compute stable hash from:

- MD file content hash
- `okf_chunk_heading_level`, `okf_max_concept_chars`
- OKF spec version string

Store in `{guide_dir}/.rh-okf-manifest.json`:

```json
{
  "source_md_sha256": "...",
  "concept_count": 47,
  "generated_at": "2026-08-13T10:00:00Z",
  "settings_hash": "..."
}
```

Skip guide rebuild if manifest matches and not `--force`.

### 13.3 Error handling

- PDF convert failure: log error, skip OKF for that guide (do not partial-write OKF without MD).
- OKF failure after successful MD: log error, retain MD, do not update manifest.
- Docling import missing when `engine=docling`: print install hint (`requirements-docling.txt`), exit non-zero.

---

## 14. Automation

### 14.1 Recommended operator sequence

```bash
rh-mastery sync --all
rh-mastery convert --all --format okf
```

### 14.2 systemd (documentation only in this phase)

Add example unit or extend `packaging/rpm/systemd/`:

```ini
# rh-mastery-convert-okf.service (example)
ExecStart=/usr/bin/rh-mastery convert --all --format okf
```

Run after sync timer or as chained `ExecStartPost` in a wrapper script.

---

## 15. Testing plan

### 15.1 Unit tests (`tests/test_rh_okf/`)

| Test | Assert |
|------|--------|
| `chunk_h2_basic` | Split on `##`, preserve code fences |
| `chunk_overflow` | Large section splits into parts with cross-links |
| `chunk_no_split_in_code` | Fenced blocks stay intact |
| `frontmatter_v02` | Required `type`, `generated`, `sources` present |
| `type_heuristic_procedure` | Install heading → `Procedure` |
| `slugify` | Stable filenames |
| `index_generation` | Valid markdown list syntax |
| `manifest_skip` | Unchanged MD skips rebuild |
| `force_rebuild` | `--force` ignores manifest |

Use fixture MD files (no PDF required) under `tests/fixtures/md/`.

### 15.2 Integration test

1. Small sample PDF or pre-generated MD in fixtures.
2. Run `convert --format okf` against temp directory.
3. Validate:
   - MD exists under `markdown/`
   - Concepts exist under `okf/{slug}/{version}/{guide}/`
   - Every concept has `type` in frontmatter
   - Global and product `index.md` exist
   - Global root `okf_version: "0.2"`

### 15.3 Conformance spot-check

Manually or via script: verify bundle against OKF §11 rules (frontmatter + `type` on all non-reserved files).

---

## 16. Documentation deliverables

| File | Updates |
|------|---------|
| `README.md` | `--format okf`, bundle layout, agent attachment examples |
| `packaging/rpm/rh-mastery.spec` | Include `rh_okf/` package |
| `Containerfile` | Ensure `requirements-docling.txt` available for OKF default engine |
| `docs/OKF_IMPLEMENTATION_SPEC.md` | This document |

---

## 17. Acceptance criteria

1. `rh-mastery convert --ansible` behavior unchanged (markdown only, pymupdf default).
2. `rh-mastery convert --ansible --format okf`:
   - Creates/updates `markdown/*.md`
   - Creates OKF tree under `okf/`
   - Defaults to docling for PDF extraction
3. Agent can attach `{download_base}/okf/` (global) or `{download_base}/okf/{slug}/{version}/` (scoped).
4. Every OKF concept file has valid YAML frontmatter with non-empty `type`.
5. External docs.redhat.com links in MD body are unchanged in OKF concepts.
6. Oversized sections are split per `okf_max_concept_chars` with cross-links.
7. `--force` rebuilds both MD and OKF for selected products.
8. Existing product selection flags (`--all`, `--product`, aliases) work unchanged.

---

## 18. Implementation phases

### Phase 1 — MVP (target first PR)

- [ ] `--format` CLI flag and engine default logic
- [ ] `rh_okf/chunk.py`, `frontmatter.py`, `bundle.py`
- [ ] Per-guide concept generation + guide `index.md`
- [ ] Product and global `index.md`
- [ ] Config keys with defaults
- [ ] README section

### Phase 2 — Robustness

- [ ] Manifest-based incremental skip
- [ ] `log.md` generation
- [ ] Overflow splitting with part cross-links
- [ ] Unit + integration tests
- [ ] RPM/container docling dependency notes

### Phase 3 — Polish (optional)

- [ ] Improved `resource` URL derivation from Red Hat URL patterns
- [ ] systemd example units
- [ ] CLI progress summary (`N guides, M concepts written`)

---

## 19. Reference: current code touchpoints

| File | Role today |
|------|------------|
| `rh_mastery.py:319` | `convert_pdf_file()` — MD writer |
| `rh_mastery.py:352` | `run_convert()` — extend for format + OKF phase |
| `rh_mastery.py:910` | `convert` subparser — add `--format` |
| `rh_config.json` | Add OKF settings |
| `tokensaver/tokensaver/front_matter.py` | Reference for YAML quoting style (do not import across boundary) |

---

## 20. Agent consumption notes (for downstream projects)

When attaching an OKF bundle to an agent:

1. **Start at `index.md`** for progressive disclosure (OKF §8).
2. **Filter by `type`** for procedure vs reference questions.
3. **Follow bundle-relative links** for intra-guide navigation.
4. **Treat `sources`** as citation chain back to PDF, MD, and docs.redhat.com.
5. **Index concepts for RAG** at concept-file granularity (not whole PDFs).
6. **Respect `status` and `stale_after`** when present (optional in v1 output).
7. **Global vs scoped attachment:** use subtree `okf/{slug}/{version}/` to reduce context size.

---

## Appendix A — Example concept file

```markdown
---
type: Procedure
title: Installing the automation controller
description: Install the Red Hat Ansible Automation Platform controller on RHEL 9.
resource: "https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.7/html/installing_on_rhel/index"
tags: ["red_hat_ansible_automation_platform", "2.7", "aap-install-2-7", "install"]
generated:
  by: process:rh-mastery
  at: "2026-08-13T09:41:00Z"
status: stable
sources:
  - id: source-md
    resource: ../../../red_hat_ansible_automation_platform/2.7/markdown/aap-install-2-7-pdf.md
    title: "Installing on RHEL"
    last_modified: "2026-08-13"
  - id: source-pdf
    resource: ../../../red_hat_ansible_automation_platform/2.7/aap-install-2-7-pdf.pdf
    title: aap-install-2-7-pdf.pdf
  - id: source-web
    resource: "https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.7/html/installing_on_rhel/index"
    title: Red Hat documentation (online)
slug: red_hat_ansible_automation_platform
version: "2.7"
guide_stem: aap-install-2-7-pdf
engine: docling
rh_section_path: "Chapter 2 > Installing the automation controller"
rh_source_md: ../../../red_hat_ansible_automation_platform/2.7/markdown/aap-install-2-7-pdf.md
---

## Installing the automation controller

1. Log in to the target host as root.
2. Enable the required repositories.
3. Run the installer script.

For prerequisites, see [System requirements](./system-requirements.md).

Further reading: [Red Hat Ansible Automation Platform 2.7 installation guide](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.7/html/installing_on_rhel/index).
```

---

## Appendix B — OKF chunk size FAQ

**Q: What does OKF say about maximum concept size?**  
**A:** Nothing normative. OKF defines one concept per file and encourages structure and indexes for agent navigation. Size limits are a **consumer/producer optimization**, not conformance criteria.

**Q: What should rh-mastery use?**  
**A:** Default `okf_max_concept_chars: 12000` with overflow splitting (§6.3). Operators may set `0` to disable caps and rely on heading splits only.

**Q: Will oversized concepts fail OKF validation?**  
**A:** No. OKF §11 only requires parseable frontmatter and non-empty `type`.
