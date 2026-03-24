import os
import sys
import json
import argparse
import requests
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from packaging import version as py_version

DEFAULT_STORAGE_CONFIG = "rh_storage.json"

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


def report_empty_slug_selection(args):
    """User-facing error when ``resolve_product_slugs`` returns no slugs."""
    if getattr(args, "all", False):
        print("❌ tracked_products is empty; run sync for at least one product first.")
    else:
        print("❌ Product flag required (e.g. --ocp, --ansible, --acm, --all, or --product SLUG).")


def markdown_subdir_from_config(config):
    return (config.get("settings") or {}).get("markdown_subdir", "markdown")


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


def _pdf_display_title(pdf_path):
    try:
        import fitz

        doc = fitz.open(pdf_path)
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
    """Default engine: PyMuPDF4LLM when it works, else PyMuPDF per-page ``get_text('markdown')``."""
    try:
        import pymupdf4llm

        md = pymupdf4llm.to_markdown(pdf_path)
        if md and str(md).strip():
            return str(md)
    except Exception:
        pass
    import fitz

    doc = fitz.open(pdf_path)
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text("markdown") or "")
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


def run_convert(master, args):
    """CLI handler for ``convert``."""
    engine = getattr(args, "engine", "pymupdf") or "pymupdf"
    if engine not in ("pymupdf", "docling"):
        print(f"❌ Unknown engine: {engine!r} (use pymupdf or docling).")
        return
    if engine == "docling":
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            print(
                "❌ Docling is not installed. Install with: pip install -r requirements-docling.txt"
            )
            return
        docling_converter = DocumentConverter()
    else:
        docling_converter = None

    slugs, force_version = resolve_product_slugs(args, master)
    if not slugs:
        report_empty_slug_selection(args)
        return

    tracked = master.config.get("tracked_products", {})
    mdir = markdown_subdir_from_config(master.config)
    base = master.base_path
    force = getattr(args, "force", False)

    for slug in slugs:
        ver = force_version if force_version else tracked.get(slug)
        if not ver:
            print(
                f"❌ No version for {slug!r} in tracked_products; run sync first or pass -v for a single product."
            )
            continue
        pdf_paths = enumerate_pdfs(base, slug, ver)
        if not pdf_paths:
            print(f"⚠️ No PDFs under {os.path.join(base, slug, ver)} — skip.")
            continue
        print(f"📄 Converting {len(pdf_paths)} PDF(s) for {slug} @ {ver} (engine={engine})...")
        for pdf_path in pdf_paths:
            stem = os.path.splitext(os.path.basename(pdf_path))[0]
            out_dir = os.path.join(base, slug, ver, mdir)
            out_md = os.path.join(out_dir, f"{stem}.md")
            if os.path.exists(out_md) and not force:
                print(f"   ⏭️  skip (exists): {stem}.md")
                continue
            try:
                convert_pdf_file(
                    pdf_path,
                    out_md,
                    engine=engine,
                    slug=slug,
                    version=ver,
                    docling_converter=docling_converter,
                )
                print(f"   ✅ {stem}.md")
            except Exception as e:
                print(f"   ❌ {stem}: {e}")


class RHDocsMaster:
    def __init__(self, config_path='rh_config.json', storage_config_path=DEFAULT_STORAGE_CONFIG):
        self.config_path = config_path
        self.storage_config_path = storage_config_path
        self.config = self.load_config()
        self.storage_config = load_storage_config(self.storage_config_path)
        self.base_path = resolve_download_base(self.config, self.storage_config)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0'})

    def load_config(self):
        with open(self.config_path, 'r') as f:
            return json.load(f)

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=4)

    def get_latest_remote_version(self, slug):
        """Probes the portal for versioning through redirects and title scraping."""
        url = f"{self.config['settings']['base_url']}/{slug}"
        print(f"🔍 Probing version for: {slug}")
        
        try:
            # Red Hat often redirects the landing page to the latest version path
            res = self.session.get(url, timeout=15, allow_redirects=True)
            
            # Strategy 1: Check URL Redirects (The most reliable for OCP/AAP)
            # If URL becomes .../ansible_automation_platform/2.6, we found it.
            url_match = re.search(fr"/{slug}/([\d\.]+)", res.url)
            if url_match:
                return url_match.group(1)

            # Strategy 2: Scrape the H1 Title (from your previous screenshot)
            soup = BeautifulSoup(res.text, 'html.parser')
            h1 = soup.find('h1')
            if h1:
                title_match = re.search(r'\b\d+\.\d+(?:\.\d+)?\b', h1.get_text())
                if title_match:
                    return title_match.group(0)

            # Strategy 2.5: Scrape version from links (e.g. /slug/2.6/ or /slug/2.6)
            link_versions = set()
            for a in soup.find_all('a', href=True):
                m = re.search(fr"/{re.escape(slug)}/([\d\.]+)(?:/|$)", a['href'])
                if m and re.match(r'^\d+\.\d+', m.group(1)):
                    link_versions.add(m.group(1))
            # Also scan raw HTML for slug/version patterns (version selector, etc.)
            link_versions.update(re.findall(fr"/{re.escape(slug)}/(\d+\.\d+(?:\.\d+)?)(?:/|$)", res.text))
            if link_versions:
                return max(link_versions, key=py_version.parse)

            # Strategy 3: Brute Force Probe (Common RH Version Patterns)
            # If discovery fails, we check if /slug/4.16, /slug/2.6, etc., exist
            print("🧪 Attempting pattern discovery...")
            test_patterns = ["4.17", "4.16", "2.6", "2.5", "9.4", "9.3"]
            for p in test_patterns:
                test_url = f"{url}/{p}"
                if self.session.head(test_url, allow_redirects=True).status_code == 200:
                    return p

            return None
        except Exception as e:
            print(f"⚠️ Error: {e}")
            return None

    def _discover_pdf_urls(self, slug, ver, page_url, soup, res_text):
        """Collect PDF URLs: first from explicit /pdf/ links, then from topic paths."""
        # Strategy 1: Explicit PDF links (e.g. legacy or some products)
        pdfs = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/pdf' in href or (href.endswith('.pdf') and slug in href):
                full = urljoin("https://docs.redhat.com", href)
                pdfs.append((full.split('/')[-1] or f"doc_{len(pdfs)}.pdf", full))
        if pdfs:
            return pdfs
        # Strategy 2: Topic-based PDFs — Red Hat serves PDF at /pdf/{topic}/ for many products (e.g. AAP)
        # Extract topic segments from html/ and html-single/ links on the version landing page
        pattern = rf'/{re.escape(slug)}/{re.escape(ver)}/html(?:[-_]single)?/([a-z0-9_]+)'
        segments = set(re.findall(pattern, res_text))
        base = f"{self.config['settings']['base_url']}/{slug}/{ver}/pdf"
        for seg in sorted(segments):
            pdf_url = f"{base}/{seg}/"
            try:
                head = self.session.head(pdf_url, allow_redirects=True, timeout=10)
                if head.status_code == 200 and (head.headers.get('Content-Type') or '').startswith('application/pdf'):
                    pdfs.append((f"{seg}.pdf", pdf_url))
            except Exception:
                pass
        return pdfs

    def mirror(self, slug, ver):
        save_dir = os.path.join(self.base_path, slug, ver)
        os.makedirs(save_dir, exist_ok=True)
        url = f"{self.config['settings']['base_url']}/{slug}/{ver}"
        
        print(f"🛰️ Accessing documentation library at {url}...")
        res = self.session.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')
        pdf_list = self._discover_pdf_urls(slug, ver, url, soup, res.text)
        
        if not pdf_list:
            print(f"❌ Could not find PDF links in the {ver} library.")
            return

        print(f"📦 Mirroring {len(pdf_list)} files...")
        for name, pdf_url in pdf_list:
            fpath = os.path.join(save_dir, name)
            if not os.path.exists(fpath):
                print(f"   📥 {name}")
                with self.session.get(pdf_url, stream=True) as r:
                    with open(fpath, 'wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)

    def sync_product(self, slug, force_version=None):
        latest = force_version if force_version else self.get_latest_remote_version(slug)
        if not latest:
            print(f"❌ FATAL: Red Hat portal is not responding with version data for {slug}.")
            return

        print(f"✅ Target Version: {latest}")
        self.mirror(slug, latest)
        self.config['tracked_products'][slug] = latest
        self.save_config()


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
        help="Convert mirrored PDFs to Markdown under settings.markdown_subdir (default: markdown/)",
    )
    _add_product_selection_to_parser(convert_p)
    convert_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .md files",
    )
    convert_p.add_argument(
        "--engine",
        choices=("pymupdf", "docling"),
        default="pymupdf",
        help="Conversion backend (default: pymupdf). docling needs: pip install -r requirements-docling.txt",
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
        for slug in slugs_to_sync:
            master.sync_product(slug, force_version=force_ver)
    elif args.command == "convert":
        master = RHDocsMaster()
        run_convert(master, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
