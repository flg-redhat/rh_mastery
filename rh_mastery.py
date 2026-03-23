import os
import sys
import json
import argparse
import requests
import re
import shutil
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from packaging import version as py_version

def get_aliases():
    try:
        with open('rh_config.json', 'r') as f:
            return json.load(f).get('aliases', {})
    except:
        return {"ocp": "openshift_container_platform", "ansible": "ansible_automation_platform"}

class RHDocsMaster:
    def __init__(self, config_path='rh_config.json'):
        self.config_path = config_path
        self.config = self.load_config()
        self.base_path = self.config['settings']['download_base']
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


def _build_argparser(parser_cls=argparse.ArgumentParser):
    """Build the CLI parser. *parser_cls* is :class:`RHArgumentParser` for the real entrypoint."""
    aliases = get_aliases()
    parser = parser_cls(
        prog="rh_mastery.py",
        description="Mirror Red Hat product documentation (PDFs) from docs.redhat.com.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s sync --ansible\n"
            "  %(prog)s sync --acm -v 2.16   # or --force-version 2.16\n"
            "  %(prog)s sync --product red_hat_quay\n"
            "  %(prog)s sync --all\n"
            "  %(prog)s help\n"
            "  %(prog)s -h\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")
    sync_p = subparsers.add_parser("sync", help="Download docs for one or more products")
    sync_p.add_argument("--all", action="store_true", help="Sync all tracked products")
    sync_p.add_argument(
        "--product",
        metavar="SLUG",
        help="Sync by documentation slug (e.g. red_hat_advanced_cluster_management_for_kubernetes)",
    )
    for alias in sorted(aliases.keys()):
        sync_p.add_argument(f"--{alias}", action="store_true", help=argparse.SUPPRESS)
    sync_p.add_argument(
        "-v",
        "--force-version",
        metavar="VER",
        dest="force_version",
        help="Pin documentation version (single-product sync only; overrides auto-detect)",
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
    print("RH Mirror Manager — all commands and options\n", file=stream)
    parser.print_help(file=stream)
    aliases = get_aliases()
    print("\n--- Product aliases (--<name> → docs.redhat.com slug) ---\n", file=stream)
    width = max(len(a) for a in aliases) if aliases else 0
    for alias in sorted(aliases.keys()):
        print(f"  --{alias:<{width}}  {aliases[alias]}", file=stream)
    print(f"\n  ({len(aliases)} product flags on ``sync``.)", file=stream)


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
        aliases = get_aliases()
        master = RHDocsMaster()
        slugs_to_sync = []
        if getattr(args, "all", False):
            slugs_to_sync = list(master.config.get("tracked_products", {}).keys())
        elif getattr(args, "product", None):
            slugs_to_sync = [args.product]
        else:
            selected_slug = next((aliases[a] for a in aliases if getattr(args, a, False)), None)
            if selected_slug:
                slugs_to_sync = [selected_slug]
        if not slugs_to_sync:
            print("❌ Product flag required (e.g. --ocp, --ansible, --acm, --all, or --product SLUG).")
            return
        force_ver = args.force_version if len(slugs_to_sync) == 1 else None
        for slug in slugs_to_sync:
            master.sync_product(slug, force_version=force_ver)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
