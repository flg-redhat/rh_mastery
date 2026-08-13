import os
import sys
import json
import argparse
import requests
import re
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from packaging import version as py_version

DEFAULT_STORAGE_CONFIG = "rh_storage.json"
DEFAULT_AUTH_CONFIG = "rh_auth.json"
SSO_TOKEN_URL = (
    "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"
)
SSO_CLIENT_ID = "rhsm-api"
CURL_CFFI_IMPERSONATE = "chrome131"
DOCS_REQUEST_TIMEOUT = 60
DOCS_REQUEST_RETRIES = 2
SYNC_PAUSE_SECONDS = 1.0

DOCS_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def _expand_path(path):
    return os.path.expanduser(path) if path else path


def load_auth_config(path=DEFAULT_AUTH_CONFIG):
    """
    Optional auth for docs.redhat.com (Bearer token and/or browser cookies).
    Secrets via ``RH_OFFLINE_TOKEN``, ``RH_OFFLINE_TOKEN_FILE``, ``RH_COOKIE_FILE``,
    or ``rh_auth.json`` (see ``rh_auth.example.json``).
    """
    cfg = {}
    config_path = os.environ.get("RH_AUTH_CONFIG", path)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"⚠️ Could not read {config_path}: {e}")

    if os.environ.get("RH_OFFLINE_TOKEN"):
        cfg["offline_token"] = os.environ["RH_OFFLINE_TOKEN"]
    if os.environ.get("RH_OFFLINE_TOKEN_FILE"):
        cfg["offline_token_file"] = os.environ["RH_OFFLINE_TOKEN_FILE"]
    if os.environ.get("RH_COOKIE_FILE"):
        cfg["cookie_file"] = os.environ["RH_COOKIE_FILE"]
    return cfg


def _read_secret_file(path):
    path = _expand_path(path)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read().strip()


def get_red_hat_access_token(offline_token):
    res = requests.post(
        SSO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": SSO_CLIENT_ID,
            "refresh_token": offline_token,
        },
        timeout=30,
    )
    res.raise_for_status()
    return res.json()["access_token"]


def _load_cookie_file(session, cookie_file):
    import http.cookiejar

    path = _expand_path(cookie_file)
    if not path or not os.path.exists(path):
        print(f"⚠️ Cookie file not found: {cookie_file}")
        return
    jar = http.cookiejar.MozillaCookieJar(path)
    jar.load(ignore_discard=True, ignore_expires=True)
    for cookie in jar:
        session.cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path,
        )


def create_docs_session(auth_cfg=None):
    """
    HTTP session for docs.redhat.com.

    Uses ``curl_cffi`` with Chrome TLS impersonation when installed (required to
    pass Akamai bot checks). Optionally attaches Red Hat SSO bearer token and/or
    cookies from a logged-in browser export.
    """
    if auth_cfg is None:
        auth_cfg = load_auth_config()

    backend = "requests"
    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate=CURL_CFFI_IMPERSONATE)
        backend = f"curl_cffi/{CURL_CFFI_IMPERSONATE}"
    except ImportError:
        session = requests.Session()
        print(
            "⚠️ curl_cffi is not installed; docs.redhat.com may return HTTP 403. "
            "Install with: pip install curl_cffi"
        )

    session.headers.update(DOCS_BROWSER_HEADERS)

    auth_bits = []
    offline_token = auth_cfg.get("offline_token") or _read_secret_file(
        auth_cfg.get("offline_token_file")
    )
    if offline_token:
        try:
            access_token = get_red_hat_access_token(offline_token)
            session.headers["Authorization"] = f"Bearer {access_token}"
            auth_bits.append("Red Hat bearer token")
        except Exception as e:
            print(f"⚠️ Red Hat token refresh failed: {e}")

    cookie_file = auth_cfg.get("cookie_file")
    if cookie_file:
        _load_cookie_file(session, cookie_file)
        auth_bits.append(f"cookies ({cookie_file})")

    try:
        session.get("https://docs.redhat.com/", timeout=20, allow_redirects=True)
    except Exception:
        pass

    if auth_bits:
        print(f"🔐 HTTP backend: {backend} ({', '.join(auth_bits)})")
    elif backend != "requests":
        print(f"🔐 HTTP backend: {backend}")
    return session, backend


def get_aliases():
    try:
        with open('rh_config.json', 'r') as f:
            return json.load(f).get('aliases', {})
    except Exception:
        return {"ocp": "openshift_container_platform", "ansible": "ansible_automation_platform"}


def resolve_product_slugs(args, master):
    """
    Shared product selection for ``sync`` and ``convert`` (``--all``, ``--product``, alias flags).

    Returns ``(slugs, force_version)``. ``force_version`` is set only when exactly one slug
    is selected and ``args.force_version`` is provided.
    """
    aliases = get_aliases()
    tracked = master.config.get("tracked_products", {})
    slugs = []
    if getattr(args, "all", False):
        slugs = list(tracked.keys())
    elif getattr(args, "product", None):
        slugs = [args.product]
    else:
        selected = next((aliases[a] for a in aliases if getattr(args, a, False)), None)
        if selected:
            slugs = [selected]
    fv = getattr(args, "force_version", None)
    force_version = fv if len(slugs) == 1 else None
    return slugs, force_version


def has_partial_convert_selection(args):
    """True when the user narrowed ``convert`` to specific product(s) via flags."""
    if getattr(args, "product", None):
        return True
    return any(getattr(args, alias, False) for alias in get_aliases())


def report_empty_slug_selection(args):
    """User-facing error when ``resolve_product_slugs`` returns no slugs (sync)."""
    if getattr(args, "all", False):
        print("❌ tracked_products is empty; run sync for at least one product first.")
    else:
        print("❌ Product flag required (e.g. --ocp, --ansible, --acm, --all, or --product SLUG).")


def report_empty_convert_targets():
    print("❌ No mirrored products found under download_base (no PDF/Markdown directories).")


def list_mirrored_products(base_path, markdown_subdir, okf_bundle_root="okf"):
    """
    Discover ``(slug, version)`` pairs present on disk under ``download_base``.

    A directory qualifies when it contains at least one PDF or Markdown file.
    """
    out = []
    if not os.path.isdir(base_path):
        return out
    skip_top = {okf_bundle_root}
    for slug in sorted(os.listdir(base_path)):
        if slug in skip_top:
            continue
        slug_dir = os.path.join(base_path, slug)
        if not os.path.isdir(slug_dir):
            continue
        for ver in sorted(os.listdir(slug_dir)):
            ver_dir = os.path.join(slug_dir, ver)
            if not os.path.isdir(ver_dir):
                continue
            if enumerate_pdfs(base_path, slug, ver):
                out.append((slug, ver))
                continue
            mdir = os.path.join(ver_dir, markdown_subdir)
            if os.path.isdir(mdir) and any(
                name.endswith(".md") for name in os.listdir(mdir)
            ):
                out.append((slug, ver))
    return out


def resolve_convert_targets(args, master, base, mdir, okf_bundle_root):
    """
    Resolve ``(slug, version)`` pairs to convert.

    Default (no product flags): every ``slug/version`` directory on disk under
    ``download_base`` that contains PDFs or Markdown.

    * ``--product`` / alias flags — partial convert for selected product(s).
    * ``--all`` — every entry in ``tracked_products`` (config-driven subset).
    * ``--all-mirrored`` — same as default (explicit); entire on-disk mirror.
    """
    tracked = master.config.get("tracked_products", {})

    if getattr(args, "all_mirrored", False) or (
        not getattr(args, "all", False) and not has_partial_convert_selection(args)
    ):
        return list_mirrored_products(base, mdir, okf_bundle_root)

    if getattr(args, "all", False):
        if not tracked:
            print("❌ tracked_products is empty; use default convert for on-disk mirror.")
            return []
        return [(slug, ver) for slug, ver in sorted(tracked.items()) if ver]

    slugs, force_version = resolve_product_slugs(args, master)
    if not slugs:
        return []

    targets = []
    for slug in slugs:
        ver = force_version if force_version else tracked.get(slug)
        if not ver:
            ver = _newest_version_on_disk(base, slug)
        if not ver:
            print(
                f"❌ No version for {slug!r}; run sync, pass -v, or omit flags to use on-disk versions."
            )
            continue
        targets.append((slug, ver))
    return targets


def _newest_version_on_disk(base_path, slug):
    """Return the lexicographically last version directory for *slug*, if any."""
    slug_dir = os.path.join(base_path, slug)
    if not os.path.isdir(slug_dir):
        return None
    versions = [
        name
        for name in os.listdir(slug_dir)
        if os.path.isdir(os.path.join(slug_dir, name))
    ]
    return sorted(versions)[-1] if versions else None


def markdown_subdir_from_config(config):
    return (config.get("settings") or {}).get("markdown_subdir", "markdown")


def okf_settings_from_config(config):
    """OKF bundle settings from ``rh_config.json`` ``settings``."""
    s = config.get("settings") or {}
    return {
        "okf_bundle_root": s.get("okf_bundle_root", "okf"),
        "okf_chunk_heading_level": int(s.get("okf_chunk_heading_level", 2)),
        "okf_max_concept_chars": int(s.get("okf_max_concept_chars", 12000)),
        "okf_spec_version": s.get("okf_spec_version", "0.2"),
        "base_url": s.get("base_url", "https://docs.redhat.com/en/documentation"),
    }


def _ensure_rh_okf_path():
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)


def fips_mode_enabled():
    """True when the kernel has crypto FIPS mode enabled (Linux)."""
    try:
        with open("/proc/sys/crypto/fips_enabled", encoding="utf-8") as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def resolve_convert_engine(fmt, engine_arg):
    """
    Pick the PDF conversion engine, with FIPS-safe defaults.

    Docling's ``DocumentConverter`` aborts on hosts with OpenSSL FIPS mode enabled
    (common on RHEL FIPS). Fall back to pymupdf unless the user explicitly chose docling.
    """
    if engine_arg is not None:
        engine = engine_arg
    elif fmt == "okf":
        engine = "docling"
    else:
        engine = "pymupdf"

    if engine == "docling" and fips_mode_enabled():
        if engine_arg == "docling":
            print(
                "❌ Docling cannot run on this host: OpenSSL FIPS mode is enabled and "
                "DocumentConverter fails FIPS self-tests. Use --engine pymupdf instead."
            )
            return None
        print(
            "⚠️ OpenSSL FIPS mode is enabled; docling is unavailable here. "
            "Using pymupdf for PDF→Markdown."
        )
        return "pymupdf"
    return engine


def load_storage_config(path=DEFAULT_STORAGE_CONFIG):
    """
    Optional storage config for where synced files are written.
    Falls back silently to legacy ``settings.download_base`` when missing.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not read {path}: {e}. Falling back to settings.download_base.")
        return {}


def resolve_download_base(config, storage_cfg):
    """
    Resolve final base path for mirrored files.
    Priority:
      1) ``rh_storage.json``: ``download_base`` (explicit full path)
      2) ``rh_storage.json``: ``mount_point`` + ``sync_subdir``
      3) legacy ``rh_config.json``: ``settings.download_base``
    """
    settings = config.get("settings") or {}
    legacy = settings.get("download_base", "./Notebookml/RHDocumentation")
    if not storage_cfg:
        return legacy

    explicit = storage_cfg.get("download_base")
    if explicit:
        return os.path.normpath(explicit)

    mount_point = storage_cfg.get("mount_point")
    sync_subdir = storage_cfg.get("sync_subdir", "RHDocumentation")
    if mount_point:
        if os.path.isabs(sync_subdir):
            return os.path.normpath(sync_subdir)
        if sync_subdir:
            return os.path.normpath(os.path.join(mount_point, sync_subdir))
        return os.path.normpath(mount_point)
    return legacy


def enumerate_pdfs(base_path, slug, version):
    """PDF files directly under ``{base_path}/{slug}/{version}/`` (not subfolders)."""
    d = os.path.join(base_path, slug, version)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not name.lower().endswith(".pdf"):
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p):
            out.append(p)
    return out


def is_valid_pdf(path):
    """True when *path* looks like a readable PDF (magic bytes, minimum size)."""
    try:
        if os.path.getsize(path) < 128:
            return False
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def pdf_problem(path):
    """Human-readable reason a mirrored file is not a valid PDF, or ``None`` if valid."""
    if is_valid_pdf(path):
        return None
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError as exc:
        return str(exc)
    if b"AccessDenied" in head or head.startswith(b"<?xml"):
        return "download failed (error page saved as .pdf — re-sync required)"
    if head.startswith((b"<!DOCTYPE", b"<html", b"<HTML")):
        return "download failed (HTML error page saved as .pdf — re-sync required)"
    if len(head) < 128:
        return "file too small to be a PDF — re-sync required"
    return "not a valid PDF — re-sync required"


def _pdf_display_title(pdf_path):
    try:
        import pymupdf

        doc = pymupdf.open(pdf_path)
        try:
            meta = doc.metadata or {}
            t = (meta.get("title") or "").strip()
            if t:
                return t
        finally:
            doc.close()
    except Exception:
        pass
    return os.path.splitext(os.path.basename(pdf_path))[0]


def _pdf_to_markdown_pymupdf(pdf_path):
    """
    PDF → markdown/text via pymupdf4llm when FIPS-safe, else pymupdf plain text per page.

    pymupdf4llm and docling both abort under OpenSSL FIPS mode on RHEL; on FIPS hosts we
    extract plain text only (OKF chunking still works, but with fewer ``##`` headings).
    """
    if not fips_mode_enabled():
        try:
            import pymupdf4llm

            md = pymupdf4llm.to_markdown(pdf_path)
            if md and str(md).strip():
                return str(md)
        except Exception:
            pass

    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        return "\n\n".join(parts)
    finally:
        doc.close()


def _pdf_to_markdown_docling(pdf_path, converter):
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown() or ""


def _yaml_front_matter(fields):
    """Minimal YAML front matter; string values JSON-encoded for safe quoting."""
    lines = ["---"]
    for k, v in fields.items():
        if v is None:
            continue
        lines.append(f"{k}: {json.dumps(str(v))}")
    lines.append("---")
    return "\n".join(lines)


def convert_pdf_file(
    pdf_path,
    out_md_path,
    *,
    engine,
    slug,
    version,
    docling_converter=None,
):
    """Convert one PDF to markdown with provenance header; writes ``out_md_path``."""
    title = _pdf_display_title(pdf_path)
    rel_pdf = os.path.relpath(os.path.abspath(pdf_path), start=os.getcwd())
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if engine == "docling":
        body = _pdf_to_markdown_docling(pdf_path, docling_converter)
    else:
        body = _pdf_to_markdown_pymupdf(pdf_path)
    fm = _yaml_front_matter(
        {
            "title": title,
            "source_pdf": rel_pdf,
            "converted_at": ts,
            "engine": engine,
            "slug": slug,
            "version": version,
        }
    )
    text = f"{fm}\n\n{body.strip()}\n"
    os.makedirs(os.path.dirname(out_md_path), exist_ok=True)
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(text)


def _ensure_markdown_from_pdf(
    pdf_path,
    out_md_path,
    *,
    engine,
    slug,
    version,
    docling_converter,
    force,
    stem,
    fmt,
):
    """
    Step 1 of the OKF pipeline: ensure reference Markdown exists.

    Returns ``True`` when ``out_md_path`` is ready, ``False`` when the PDF cannot be converted.
    """
    if os.path.exists(out_md_path) and not force:
        return True

    problem = pdf_problem(pdf_path)
    if problem:
        print(f"   ❌ {stem}: {problem}")
        return False

    step = "Step 1/2 — PDF→Markdown" if fmt == "okf" else "PDF→Markdown"
    print(f"   📝 {step}: {stem}.md")
    try:
        convert_pdf_file(
            pdf_path,
            out_md_path,
            engine=engine,
            slug=slug,
            version=version,
            docling_converter=docling_converter,
        )
        print(f"   ✅ {stem}.md")
        return True
    except Exception as e:
        print(f"   ❌ {stem}: {e}")
        return False


def _build_okf_for_guide(
    okf_mod,
    *,
    out_md_path,
    bundle_root,
    slug,
    version,
    guide_stem,
    okf_cfg,
    pdf_path,
    force,
):
    """Step 2 of the OKF pipeline. Returns guide info dict or ``None`` on failure."""
    if not os.path.exists(out_md_path):
        print(f"   ⚠️  skip OKF (no Markdown yet): {guide_stem}")
        return None
    try:
        info = okf_mod.build_guide_bundle(
            out_md_path,
            bundle_root=bundle_root,
            slug=slug,
            version=version,
            guide_stem=guide_stem,
            base_url=okf_cfg["base_url"],
            pdf_path=pdf_path,
            chunk_heading_level=okf_cfg["okf_chunk_heading_level"],
            max_concept_chars=okf_cfg["okf_max_concept_chars"],
            okf_spec_version=okf_cfg["okf_spec_version"],
            force=force,
        )
        if info.get("skipped"):
            print(f"   ⏭️  skip OKF (unchanged): {guide_stem}")
        else:
            n = info.get("concept_count", 0)
            print(f"   ✅ Step 2/2 — OKF {guide_stem} ({n} concepts)")
        return info
    except Exception as e:
        print(f"   ❌ OKF {guide_stem}: {e}")
        return None


def _convert_product_guides(
    master,
    *,
    slug,
    ver,
    pdf_paths,
    fmt,
    engine,
    docling_converter,
    mdir,
    base,
    bundle_root,
    okf_cfg,
    okf_mod,
    force,
):
    """Convert all guides for one product version. Returns (guide_infos, repair_stems)."""
    guide_infos = []
    repair_stems = []

    for pdf_path in pdf_paths:
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        out_md = os.path.join(base, slug, ver, mdir, f"{stem}.md")
        pdf_ok = is_valid_pdf(pdf_path)

        if not pdf_ok:
            if os.path.exists(out_md):
                print(
                    f"   ⚠️  {stem}: invalid PDF on disk; using existing Markdown "
                    f"({pdf_problem(pdf_path)})"
                )
            else:
                print(f"   ❌ {stem}: {pdf_problem(pdf_path)} (no Markdown — skipped)")
                repair_stems.append(stem)
                continue
        elif os.path.exists(out_md) and not force:
            print(f"   ⏭️  skip MD (exists): {stem}.md")
        elif not _ensure_markdown_from_pdf(
            pdf_path,
            out_md,
            engine=engine,
            slug=slug,
            version=ver,
            docling_converter=docling_converter,
            force=force,
            stem=stem,
            fmt=fmt,
        ):
            repair_stems.append(stem)
            continue

        if fmt != "okf":
            continue

        info = _build_okf_for_guide(
            okf_mod,
            out_md_path=out_md,
            bundle_root=bundle_root,
            slug=slug,
            version=ver,
            guide_stem=stem,
            okf_cfg=okf_cfg,
            pdf_path=pdf_path if pdf_ok else None,
            force=force,
        )
        if info is not None:
            guide_infos.append(info)

    return guide_infos, repair_stems


def run_convert(master, args):
    """CLI handler for ``convert`` (mirrored PDFs only; uses rh_config / rh_storage paths)."""
    fmt = getattr(args, "format", "markdown") or "markdown"
    if fmt not in ("markdown", "okf"):
        print(f"❌ Unknown format: {fmt!r} (use markdown or okf).")
        return 1

    engine_arg = getattr(args, "engine", None)
    engine = resolve_convert_engine(fmt, engine_arg)
    if engine is None:
        return 1
    if engine not in ("pymupdf", "docling"):
        print(f"❌ Unknown engine: {engine!r} (use pymupdf or docling).")
        return 1
    if engine == "docling":
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            print(
                "❌ Docling is not installed. Install with: pip install -r requirements-docling.txt"
            )
            return 1
        docling_converter = DocumentConverter()
    else:
        docling_converter = None

    mdir = markdown_subdir_from_config(master.config)
    okf_cfg = okf_settings_from_config(master.config)
    base = master.base_path
    bundle_root = os.path.join(base, okf_cfg["okf_bundle_root"])
    force = getattr(args, "force", False)
    sync_first = getattr(args, "sync_first", False)

    targets = resolve_convert_targets(args, master, base, mdir, okf_cfg["okf_bundle_root"])
    if not targets:
        report_empty_convert_targets()
        return 1

    if has_partial_convert_selection(args) or getattr(args, "all", False):
        scope = f"partial selection ({len(targets)} product/version target(s))"
    else:
        scope = f"entire on-disk mirror ({len(targets)} product/version target(s))"

    if sync_first:
        print(f"🔄 --sync-first: syncing {len(targets)} product/version target(s) before convert...")
        sync_ok = 0
        sync_fail = 0
        for i, (slug, ver) in enumerate(targets):
            try:
                if master.sync_product(slug, force_version=ver):
                    sync_ok += 1
                else:
                    sync_fail += 1
            except Exception as exc:
                sync_fail += 1
                print(f"⚠️  Sync failed for {slug} @ {ver}: {exc}")
            if i + 1 < len(targets):
                time.sleep(SYNC_PAUSE_SECONDS)
        print(f"🔄 Sync pass complete: {sync_ok} ok, {sync_fail} skipped/failed.")
    else:
        print(
            f"📂 Mirror-only convert ({scope}): using PDFs/Markdown on disk "
            f"(pass --sync-first to refresh from docs.redhat.com first)."
        )

    okf_mod = None
    if fmt == "okf":
        _ensure_rh_okf_path()
        from rh_okf import bundle as okf_mod
        print(
            "📚 OKF pipeline: Step 1 PDF→Markdown (reference), then Step 2 Markdown→OKF bundle."
        )

    global_products = []
    total_concepts = 0
    total_guides = 0
    total_skipped_repair = 0

    for slug, ver in targets:
        pdf_paths = enumerate_pdfs(base, slug, ver)
        if not pdf_paths:
            if sync_first:
                master.sync_product(slug, force_version=ver)
                pdf_paths = enumerate_pdfs(base, slug, ver)
            if not pdf_paths:
                print(
                    f"⚠️ No PDFs under {os.path.join(base, slug, ver)} — skip. "
                    f"Use --sync-first to download."
                )
                continue
        label = "Converting" if fmt == "markdown" else "Converting + OKF"
        print(f"📄 {label} {len(pdf_paths)} PDF(s) for {slug} @ {ver} (engine={engine}, format={fmt})...")

        guide_infos, repair_stems = _convert_product_guides(
            master,
            slug=slug,
            ver=ver,
            pdf_paths=pdf_paths,
            fmt=fmt,
            engine=engine,
            docling_converter=docling_converter,
            mdir=mdir,
            base=base,
            bundle_root=bundle_root,
            okf_cfg=okf_cfg,
            okf_mod=okf_mod,
            force=force,
        )

        if repair_stems and sync_first:
            print(
                f"\n🔄 {len(repair_stems)} guide(s) still need valid PDFs — re-syncing "
                f"{slug} @ {ver} and retrying..."
            )
            master.sync_product(slug, force_version=ver)
            retry_pdfs = [
                p
                for p in enumerate_pdfs(base, slug, ver)
                if os.path.splitext(os.path.basename(p))[0] in repair_stems
            ]
            retry_infos, still_failed = _convert_product_guides(
                master,
                slug=slug,
                ver=ver,
                pdf_paths=retry_pdfs,
                fmt=fmt,
                engine=engine,
                docling_converter=docling_converter,
                mdir=mdir,
                base=base,
                bundle_root=bundle_root,
                okf_cfg=okf_cfg,
                okf_mod=okf_mod,
                force=True,
            )
            existing = {g["guide_stem"] for g in guide_infos}
            for info in retry_infos:
                if info["guide_stem"] not in existing:
                    guide_infos.append(info)
                else:
                    for i, g in enumerate(guide_infos):
                        if g["guide_stem"] == info["guide_stem"]:
                            guide_infos[i] = info
                            break
            repair_stems = still_failed

        if repair_stems:
            total_skipped_repair += len(repair_stems)
            hint = (
                f"{_cli_prog()} convert --sync-first --product {slug} -v {ver}"
                if not sync_first
                else f"{_cli_prog()} sync --product {slug} -v {ver}"
            )
            print(
                f"⚠️  {len(repair_stems)} guide(s) skipped ({', '.join(repair_stems)}). "
                f"To re-download: {hint}"
            )

        for info in guide_infos:
            total_guides += 1
            if not info.get("skipped"):
                total_concepts += info.get("concept_count", 0)

        if fmt == "okf" and guide_infos:
            okf_mod.build_product_index(bundle_root, slug, ver, guide_infos)
            okf_mod.write_product_log(bundle_root, slug, ver, guide_infos, force=force)
            global_products.append({"slug": slug, "version": ver, "guides": guide_infos})

    if fmt == "okf" and global_products:
        okf_mod.build_global_index(
            bundle_root,
            global_products,
            okf_spec_version=okf_cfg["okf_spec_version"],
        )
        okf_mod.write_global_log(bundle_root, global_products, force=force)

    if fmt == "okf":
        print(
            f"\n📚 OKF bundle: {bundle_root} "
            f"({len(global_products)} product(s), {total_guides} guide(s), "
            f"{total_concepts} new concept(s))"
        )
    if total_skipped_repair and not sync_first:
        print(
            f"\n💡 Tip: {total_skipped_repair} guide(s) had no usable PDF/Markdown. "
            f"Run with --sync-first to refresh the mirror, then convert again."
        )
    return 0


class RHDocsMaster:
    def __init__(
        self,
        config_path='rh_config.json',
        storage_config_path=DEFAULT_STORAGE_CONFIG,
        auth_config_path=DEFAULT_AUTH_CONFIG,
    ):
        self.config_path = config_path
        self.storage_config_path = storage_config_path
        self.auth_config_path = auth_config_path
        self.config = self.load_config()
        self.storage_config = load_storage_config(self.storage_config_path)
        self.base_path = resolve_download_base(self.config, self.storage_config)
        auth_cfg = load_auth_config(self.auth_config_path)
        self.session, self.http_backend = create_docs_session(auth_cfg)

    def load_config(self):
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def _fetch_docs_page(self, url, referer=None):
        """GET a docs page, following meta-refresh hops used by the remodeled site."""
        headers = {"Referer": referer} if referer else None
        last_error = None
        for attempt in range(DOCS_REQUEST_RETRIES + 1):
            try:
                res = self.session.get(
                    url,
                    timeout=DOCS_REQUEST_TIMEOUT,
                    allow_redirects=True,
                    headers=headers,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt < DOCS_REQUEST_RETRIES:
                    wait = 2**attempt
                    print(f"   ⚠️  Request timed out, retrying in {wait}s ({url})...")
                    time.sleep(wait)
                    continue
                print(f"❌ Network error fetching {url}: {exc}")
                return None
        else:
            return None

        for _ in range(3):
            if res.status_code != 200 or "Access Denied" in res.text:
                break
            refresh = re.search(
                r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\']+)',
                res.text,
                flags=re.I,
            )
            if not refresh:
                refresh = re.search(
                    r'content=["\'][^"\']*url=([^"\']+)["\'][^>]+http-equiv=["\']refresh',
                    res.text,
                    flags=re.I,
                )
            if not refresh:
                break
            next_url = urljoin(res.url, refresh.group(1).strip())
            if next_url == res.url:
                break
            try:
                res = self.session.get(
                    next_url,
                    timeout=DOCS_REQUEST_TIMEOUT,
                    allow_redirects=True,
                    headers=headers,
                )
            except Exception as exc:
                print(f"❌ Network error following redirect to {next_url}: {exc}")
                return None
        return res

    def _docs_page_ok(self, res):
        return (
            res is not None
            and res.status_code == 200
            and "Access Denied" not in res.text
            and len(res.text) > 500
        )

    def _collect_html_topics(self, slug, ver, soup, res_text):
        """
        HTML guide topic segments from remodeled docs pages.

        Red Hat docs now emit both absolute paths
        ``/documentation/{slug}/{ver}/html/{topic}`` and site-relative
        ``/html/{topic}`` links in the SPA shell.
        """
        segments = set()
        patterns = [
            rf"/(?:en/)?documentation/{re.escape(slug)}/{re.escape(ver)}/html(?:[-_]single)?/([a-z0-9_]+)",
            r"/html/(?:[-_]single)?/([a-z0-9_]+)",
        ]
        for pat in patterns:
            segments.update(re.findall(pat, res_text, flags=re.I))
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            m = re.search(
                rf"/(?:en/)?documentation/{re.escape(slug)}/{re.escape(ver)}/html/(?:[-_]single)?/([a-z0-9_]+)",
                href,
                flags=re.I,
            )
            if m:
                segments.add(m.group(1))
                continue
            m = re.search(r"/html/(?:[-_]single)?/([a-z0-9_]+)", href, flags=re.I)
            if m:
                segments.add(m.group(1))
        return segments

    def _is_documentation_hub(self, slug, ver, res_text):
        """True when the landing page links out to other products but has no own guides."""
        own_guides = re.findall(
            rf"/documentation/{re.escape(slug)}/{re.escape(ver)}/html/",
            res_text,
            flags=re.I,
        )
        rel_guides = re.findall(r'["\']/html/[a-z0-9_]+["\']', res_text, flags=re.I)
        if own_guides or rel_guides:
            return False
        other_products = set(
            re.findall(
                r"/documentation/(red_hat_[a-z0-9_]+)/",
                res_text,
                flags=re.I,
            )
        )
        other_products.discard(slug)
        return len(other_products) >= 3

    def _docs_page_url(self, path):
        """Normalize site-relative documentation paths to configured ``base_url``."""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        m = re.search(r"/(?:en/)?documentation/(.+)", path)
        if m:
            return f"{self.config['settings']['base_url']}/{m.group(1)}"
        return urljoin(f"{self.config['settings']['base_url']}/", path.lstrip("/"))

    def _looks_like_version(self, value):
        return bool(
            re.match(
                r"^(\d+\.\d+(?:\.\d+)?|\d+\.|\d{4}(?:\.\d+)?|\d+)$",
                value,
            )
        )

    def _version_sort_key(self, value):
        normalized = value.rstrip(".")
        try:
            return (0, py_version.parse(normalized))
        except Exception:
            pass
        if re.match(r"^\d{4}$", normalized):
            return (1, int(normalized))
        if re.match(r"^\d+$", normalized):
            return (2, int(normalized))
        return (3, normalized)

    def _pick_latest_version(self, versions):
        valid = [v for v in versions if self._looks_like_version(v)]
        if not valid:
            return None
        return max(valid, key=self._version_sort_key)

    def _extract_versions_from_text(self, slug, text):
        if not text:
            return set()
        versions = set()
        pattern = rf"/(?:en/)?documentation/{re.escape(slug)}/([^/\"'?#\s]+)"
        for segment in re.findall(pattern, text):
            segment = segment.rstrip("/")
            if not self._looks_like_version(segment):
                continue
            versions.add(segment)
        return versions

    def _version_from_response(self, slug, res):
        url_match = re.search(
            rf"/{re.escape(slug)}/([^/\"'?#]+)",
            res.url,
        )
        if url_match and self._looks_like_version(url_match.group(1)):
            return url_match.group(1)

        for refresh_target in re.findall(
            r'content=["\'][^"\']*url=([^"\']+)["\']',
            res.text,
            flags=re.I,
        ):
            refresh_match = re.search(
                rf"/{re.escape(slug)}/([^/\"'?#]+)",
                refresh_target,
            )
            if refresh_match and self._looks_like_version(refresh_match.group(1)):
                return refresh_match.group(1)

        found = self._extract_versions_from_text(slug, res.text)
        if found:
            return self._pick_latest_version(found)

        soup = BeautifulSoup(res.text, "html.parser")
        h1 = soup.find("h1")
        if h1:
            title_text = h1.get_text()
            title_versions = set()
            title_versions.update(re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", title_text))
            title_versions.update(re.findall(r"\b\d{4}\b", title_text))
            picked = self._pick_latest_version(title_versions)
            if picked:
                return picked

        link_versions = set()
        for a in soup.find_all("a", href=True):
            link_versions.update(self._extract_versions_from_text(slug, a["href"]))
        if link_versions:
            return self._pick_latest_version(link_versions)
        return None

    def _probe_version_candidates(self, slug, tracked=None):
        """Build version candidates from the last synced release upward."""
        candidates = []
        seen = set()

        def add(value):
            if not value or value in seen:
                return
            seen.add(value)
            candidates.append(value)

        if tracked:
            add(tracked)
            base = tracked.rstrip(".")
            if base != tracked:
                add(base)

            if tracked.endswith(".") and re.match(r"^[\d.]+$", tracked):
                prefix = tracked[:-1]
                if re.match(r"^\d+$", prefix):
                    for minor in range(0, 20):
                        add(f"{prefix}.{minor}")
                    add(str(int(prefix) + 1))
                elif re.match(r"^\d{4}$", prefix):
                    for bump in range(0, 4):
                        add(str(int(prefix) + bump))
                return candidates

            patch = re.match(r"^(\d+)\.(\d+)\.(\d+)$", base)
            if patch:
                major, minor, patch_num = map(int, patch.groups())
                for bump in range(1, 4):
                    add(f"{major}.{minor}.{patch_num + bump}")
                for bump in range(1, 3):
                    add(f"{major}.{minor + bump}.0")
                add(f"{major + 1}.0")
                return candidates

            minor = re.match(r"^(\d+)\.(\d+)$", base)
            if minor:
                major, minor_num = int(minor.group(1)), int(minor.group(2))
                for bump in range(1, 6):
                    add(f"{major}.{minor_num + bump}")
                add(f"{major + 1}.0")
                add(f"{major + 1}.1")
                return candidates

            year = re.match(r"^(\d{4})$", base)
            if year:
                start = int(year.group(1))
                for bump in range(1, 4):
                    add(str(start + bump))
                return candidates

            whole = re.match(r"^(\d+)$", base)
            if whole:
                start = int(whole.group(1))
                for bump in range(1, 4):
                    add(str(start + bump))
                return candidates

        return candidates

    def _probe_existing_versions(self, slug, candidates):
        """Return the highest version that resolves to a live docs library page."""
        url = f"{self.config['settings']['base_url']}/{slug}"
        latest = None
        for ver in candidates:
            probe = self._fetch_docs_page(f"{url}/{ver}", referer=url)
            if not self._docs_page_ok(probe):
                continue
            found = self._version_from_response(slug, probe) or ver
            if latest is None or self._version_sort_key(found) > self._version_sort_key(latest):
                latest = found
        return latest

    def get_latest_remote_version(self, slug):
        """Discover the newest docs.redhat.com release for *slug*."""
        url = f"{self.config['settings']['base_url']}/{slug}"
        tracked = self.config.get("tracked_products", {}).get(slug)
        print(f"🔍 Probing version for: {slug}")

        try:
            discovered = []

            res = self._fetch_docs_page(url, referer="https://docs.redhat.com/")
            landing_version = None
            if res is not None:
                landing_version = self._version_from_response(slug, res)
                if not landing_version and (
                    res.status_code != 200 or "Access Denied" in res.text
                ):
                    print(
                        f"⚠️ Portal returned HTTP {res.status_code} for {slug} landing page."
                    )
            else:
                print(f"⚠️ Could not load landing page for {slug}.")

            if landing_version:
                discovered.append(landing_version)

            probed = self._probe_existing_versions(
                slug,
                self._probe_version_candidates(slug, tracked),
            )
            if probed:
                discovered.append(probed)

            latest = self._pick_latest_version(discovered)
            if latest:
                if tracked and self._version_sort_key(latest) > self._version_sort_key(tracked):
                    print(f"📈 Newer release detected ({tracked} → {latest})")
                return latest

            if not discovered:
                print("🧪 No version discovered from landing page or tracked release probes.")
            return None
        except Exception as e:
            print(f"⚠️ Error: {e}")
            return None

    def _discover_pdf_urls(self, slug, ver, page_url, soup, res_text):
        """Collect downloadable PDF URLs from docs pages (direct links or /pdf/* index pages)."""
        def is_pdf_response(resp):
            ctype = (resp.headers.get("Content-Type") or "").lower()
            cdisp = (resp.headers.get("Content-Disposition") or "").lower()
            final = resp.url.lower().split("?", 1)[0]
            return (
                ctype.startswith("application/pdf")
                or final.endswith(".pdf")
                or ".pdf" in cdisp
            )

        def resolve_download_url(candidate_url):
            """
            Return a direct PDF URL for *candidate_url*.
            docs.redhat now often serves /pdf/<topic>/ as HTML index pages containing the
            real *.pdf URL inside page scripts/state.
            """
            if candidate_url.lower().split("?", 1)[0].endswith(".pdf"):
                try:
                    head = self.session.head(
                        candidate_url, allow_redirects=True, timeout=DOCS_REQUEST_TIMEOUT
                    )
                    if head.status_code == 200 and is_pdf_response(head):
                        return head.url
                except Exception:
                    pass

            try:
                head = self.session.head(
                    candidate_url, allow_redirects=True, timeout=DOCS_REQUEST_TIMEOUT
                )
                final = head.url
                if head.status_code == 200 and is_pdf_response(head):
                    return final
            except Exception:
                pass

            try:
                res = self.session.get(
                    candidate_url, allow_redirects=True, timeout=DOCS_REQUEST_TIMEOUT
                )
                if res.status_code != 200:
                    return None
                if is_pdf_response(res):
                    return res.url
                # JSON/script blobs often escape slashes as \/.
                text = res.text.replace("\\/", "/")
                # Prefer absolute links, then site-relative links.
                patterns = [
                    r'https?://[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
                    r'/(?:en/)?documentation/[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
                    r'pdfs/[^"\'>\s]+\.pdf(?:\?[^"\'>\s]*)?',
                ]
                seen = set()
                for pat in patterns:
                    for m in re.findall(pat, text, flags=re.IGNORECASE):
                        full = urljoin(res.url, m)
                        if "docs.redhat.com" not in full and not m.startswith("pdfs/"):
                            continue
                        if f"/documentation/{slug}/{ver}/" not in full:
                            continue
                        if full in seen:
                            continue
                        seen.add(full)
                        try:
                            h2 = self.session.head(
                                full, allow_redirects=True, timeout=DOCS_REQUEST_TIMEOUT
                            )
                            if h2.status_code == 200 and is_pdf_response(h2):
                                return h2.url
                        except Exception:
                            continue
            except Exception:
                return None
            return None

        def add_pdf(name, url, pdfs, seen_urls):
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            if not name.lower().endswith(".pdf"):
                name = f"{name}.pdf"
            pdfs.append((name, url))

        pdfs = []
        seen_urls = set()

        # Strategy 1: Remodeled docs hub pages (download_pdf-* with pdfs/*.pdf assets)
        download_pages = set(
            re.findall(
                rf"/(?:en/)?documentation/{re.escape(slug)}/{re.escape(ver)}/download_pdf-[a-z0-9_]+",
                res_text,
            )
        )
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "download_pdf-" in href and slug in href:
                download_pages.add(href.split("?", 1)[0])
        for page_path in sorted(download_pages):
            page_url_full = self._docs_page_url(page_path)
            page_res = self._fetch_docs_page(page_url_full, referer=page_url)
            if not self._docs_page_ok(page_res):
                continue
            for href in re.findall(r'href="(pdfs/[^"]+\.pdf)"', page_res.text, flags=re.I):
                full = urljoin(page_res.url.rstrip("/") + "/", href)
                add_pdf(os.path.basename(href), full, pdfs, seen_urls)
        if pdfs:
            return pdfs

        # Strategy 2: Explicit PDF links (legacy or direct .pdf assets)
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'download_pdf-' in href:
                continue
            if '/pdf' in href or href.endswith('.pdf'):
                full = urljoin(page_url, href)
                if slug not in full and not href.startswith("pdfs/"):
                    continue
                resolved = resolve_download_url(full)
                if resolved:
                    name = os.path.basename(resolved.split("?", 1)[0]) or f"doc_{len(pdfs)}.pdf"
                    add_pdf(name, resolved, pdfs, seen_urls)
        if pdfs:
            return pdfs

        # Strategy 3: Topic-based PDFs — /pdf/{topic}/ index pages (current docs.redhat.com layout)
        segments = self._collect_html_topics(slug, ver, soup, res_text)
        base = f"{self.config['settings']['base_url']}/{slug}/{ver}/pdf"
        for seg in sorted(segments):
            candidate = f"{base}/{seg}/"
            resolved = resolve_download_url(candidate)
            if resolved:
                name = os.path.basename(resolved.split("?", 1)[0]) or f"{seg}.pdf"
                add_pdf(name, resolved, pdfs, seen_urls)
        return pdfs

    def mirror(self, slug, ver):
        save_dir = os.path.join(self.base_path, slug, ver)
        os.makedirs(save_dir, exist_ok=True)
        url = f"{self.config['settings']['base_url']}/{slug}/{ver}"

        print(f"🛰️ Accessing documentation library at {url}...")
        try:
            res = self._fetch_docs_page(url, referer="https://docs.redhat.com/")
        except Exception as exc:
            print(f"❌ Could not load documentation library: {exc}")
            return False
        if not self._docs_page_ok(res):
            status = res.status_code if res is not None else "network error"
            print(f"❌ Could not load documentation library (HTTP {status}).")
            return False
        soup = BeautifulSoup(res.text, "html.parser")
        pdf_list = self._discover_pdf_urls(slug, ver, res.url, soup, res.text)

        if not pdf_list:
            if self._is_documentation_hub(slug, ver, res.text):
                print(
                    f"ℹ️  {slug} @ {ver} is a documentation hub (links to other products; "
                    f"no PDFs for this slug)."
                )
            else:
                print(f"❌ Could not find PDF links in the {ver} library.")
            return False

        print(f"📦 Mirroring {len(pdf_list)} files...")
        for name, pdf_url in pdf_list:
            fpath = os.path.join(save_dir, name)
            if os.path.exists(fpath) and is_valid_pdf(fpath):
                continue
            if os.path.exists(fpath):
                print(f"   🔄 Re-downloading invalid file: {name} ({pdf_problem(fpath)})")
            else:
                print(f"   📥 {name}")
            try:
                r = self.session.get(
                    pdf_url,
                    stream=True,
                    timeout=DOCS_REQUEST_TIMEOUT,
                    headers={"Referer": url},
                )
                try:
                    with open(fpath, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                finally:
                    r.close()
            except Exception as exc:
                print(f"   ❌ {name}: download failed ({exc})")
                continue
            if not is_valid_pdf(fpath):
                print(
                    f"   ⚠️  {name}: still not a valid PDF after download "
                    f"({pdf_problem(fpath)})"
                )
        return True

    def sync_product(self, slug, force_version=None):
        try:
            latest = force_version if force_version else self.get_latest_remote_version(slug)
        except Exception as exc:
            print(f"❌ Version discovery failed for {slug}: {exc}")
            return False
        if not latest:
            print(f"❌ Could not resolve documentation version for {slug}.")
            return False

        print(f"✅ Target Version: {latest}")
        ok = self.mirror(slug, latest)
        if ok:
            self.config["tracked_products"][slug] = latest
            self.save_config()
        return ok


class RHArgumentParser(argparse.ArgumentParser):
    """Root parser so ``-h`` / ``--help`` print full help including the product alias table."""

    def print_help(self, file=None):
        help(stream=file or sys.stdout)


def _cli_prog():
    """Invocation name for argparse (wrapper sets RH_MASTERY_PROG=rh-mastery)."""
    if os.environ.get("RH_MASTERY_PROG"):
        return os.environ["RH_MASTERY_PROG"]
    return os.path.basename(sys.argv[0]) if sys.argv else "rh-mastery"


def _add_product_selection_to_parser(parser):
    """``--all``, ``--product``, per-alias flags, ``-v`` / ``--force-version`` (same as sync/convert)."""
    aliases = get_aliases()
    parser.add_argument(
        "--all",
        action="store_true",
        help="All products listed in tracked_products (same selection rules as sync)",
    )
    parser.add_argument(
        "--product",
        metavar="SLUG",
        help="Documentation slug (e.g. red_hat_advanced_cluster_management_for_kubernetes)",
    )
    for alias in sorted(aliases.keys()):
        parser.add_argument(f"--{alias}", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "-v",
        "--force-version",
        metavar="VER",
        dest="force_version",
        help="Pin version when exactly one product is selected (overrides tracked_products for that run)",
    )


def _build_argparser(parser_cls=argparse.ArgumentParser):
    """Build the CLI parser. *parser_cls* is :class:`RHArgumentParser` for the real entrypoint."""
    prog = _cli_prog()
    parser = parser_cls(
        prog=prog,
        description="Mirror Red Hat product documentation (PDFs) from docs.redhat.com; optional PDF→Markdown conversion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s sync --ansible\n"
            "  %(prog)s sync --acm -v 2.16   # or --force-version 2.16\n"
            "  %(prog)s sync --product red_hat_quay\n"
            "  %(prog)s sync --all\n"
            "  %(prog)s convert --ansible\n"
            "  %(prog)s convert --all --force\n"
            "  %(prog)s convert --format okf\n"
            "  %(prog)s convert --ansible --format okf\n"
            "  %(prog)s convert --all --format okf --sync-first\n"
            "  %(prog)s convert --product red_hat_quay --engine docling\n"
            "  %(prog)s help\n"
            "  %(prog)s -h\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    sync_p = subparsers.add_parser("sync", help="Download docs for one or more products")
    _add_product_selection_to_parser(sync_p)
    convert_p = subparsers.add_parser(
        "convert",
        help="Convert mirrored PDFs to Markdown and optionally OKF bundles "
        "(default: entire on-disk mirror; use product flags for partial convert)",
    )
    _add_product_selection_to_parser(convert_p)
    convert_p.add_argument(
        "--all-mirrored",
        action="store_true",
        help="Convert entire on-disk mirror (same as default when no product flags are given)",
    )
    convert_p.add_argument(
        "--sync-first",
        action="store_true",
        help="Sync selected product(s) from docs.redhat.com before converting "
        "(full update + convert pipeline)",
    )
    convert_p.add_argument(
        "--format",
        choices=("markdown", "okf"),
        default="markdown",
        help="Output format: markdown (.md only) or okf (write .md then OKF bundle; "
        "default engine: docling, or pymupdf on FIPS-enabled hosts)",
    )
    convert_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .md and OKF concept files",
    )
    convert_p.add_argument(
        "--engine",
        choices=("pymupdf", "docling"),
        default=None,
        help="PDF→Markdown backend (default: pymupdf, or docling when --format okf on non-FIPS hosts). "
        "docling needs: pip install -r requirements-docling.txt",
    )
    subparsers.add_parser(
        "list-options",
        help="Same as help: full options + product alias table",
    )
    subparsers.add_parser(
        "help",
        help="Print all commands and options (same as -h / --help)",
    )
    return parser


def build_argparser():
    """Build the root CLI parser (``-h`` / ``--help`` use :func:`help`)."""
    return _build_argparser(RHArgumentParser)


def help(stream=None):
    """
    Print every command and option, including argparse help and the product alias table.

    Used by ``-h`` / ``--help``, the ``help`` subcommand, and ``list-options``.
    Uses a plain :class:`argparse.ArgumentParser` here so this does not recurse into
    :class:`RHArgumentParser`.
    """
    if stream is None:
        stream = sys.stdout
    parser = _build_argparser(argparse.ArgumentParser)
    print(f"{_cli_prog()} — all commands and options\n", file=stream)
    parser.print_help(file=stream)
    aliases = get_aliases()
    print("\n--- Product aliases (--<name> → docs.redhat.com slug) ---\n", file=stream)
    width = max(len(a) for a in aliases) if aliases else 0
    for alias in sorted(aliases.keys()):
        print(f"  --{alias:<{width}}  {aliases[alias]}", file=stream)
    print(f"\n  ({len(aliases)} product flags on ``sync`` and ``convert``.)", file=stream)


def print_cli_options(stream=None):
    """
    Print the full CLI help (including every product flag) and a readable
    alias → documentation slug table from ``rh_config.json``.

    Same output as :func:`help`.
    """
    help(stream=stream)


def main():
    parser = build_argparser()
    args = parser.parse_args()
    if args.command in ("list-options", "help"):
        help()
        return
    if args.command == "sync":
        master = RHDocsMaster()
        slugs_to_sync, force_ver = resolve_product_slugs(args, master)
        if not slugs_to_sync:
            report_empty_slug_selection(args)
            return
        for i, slug in enumerate(slugs_to_sync):
            master.sync_product(slug, force_version=force_ver)
            if len(slugs_to_sync) > 1 and i + 1 < len(slugs_to_sync):
                time.sleep(1)
    elif args.command == "convert":
        master = RHDocsMaster()
        run_convert(master, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
