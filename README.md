# RH Mirror Manager

Mirror **Red Hat product documentation** from [docs.redhat.com](https://docs.redhat.com) as PDFs for offline reading. The tool discovers the current documentation version for each product, downloads PDFs into a local directory tree, and stores the last-synced version in `rh_config.json`.

---

## What it does

| Capability | Details |
|------------|---------|
| **Version discovery** | Probes docs.redhat.com (redirects, page titles, link scraping, fallback patterns) to resolve the documentation version for a product *slug*. |
| **PDF mirroring** | Fetches PDFs from explicit `/pdf/` links or, for many products, from topic URLs like `…/{version}/pdf/{topic}/`. |
| **Product catalog** | `rh_config.json` maps short CLI names to Red Hat documentation slugs (aligned with the [product index](https://docs.redhat.com/en/products)). |
| **Flexible sync** | One product by alias, by slug, or all tracked products in one run. |
| **Help** | `help()` / `-h` / `--help` / `help` / `list-options` — full command list and alias table (see [CLI help](#cli-help)). |

---

## Requirements

- Python **3.8+**
- Install dependencies:

```bash
pip install -r requirements.txt
```

(`requests`, `beautifulsoup4`, `packaging`)

---

## Configuration

Run the script from the directory that contains **`rh_config.json`**, or adjust paths as needed.

| Key | Purpose |
|-----|---------|
| `settings.base_url` | Documentation base URL (default: `https://docs.redhat.com/en/documentation`). |
| `settings.download_base` | Root folder for downloaded PDFs (e.g. `./Notebookml/RHDocumentation`). |
| `settings.portal_url` | Product index (informational; default points at the Red Hat docs product list). |
| `aliases` | Short name → documentation slug (e.g. `acm` → `red_hat_advanced_cluster_management_for_kubernetes`). |
| `tracked_products` | Slug → last successfully synced version string (updated after each successful sync). |

PDFs are written to:

`{download_base}/{slug}/{version}/`

---

## CLI help

These all print **every command**, argparse usage, and the **full product alias → slug** table:

| Invocation | Notes |
|------------|--------|
| `python rh_mastery.py -h` | Short option |
| `python rh_mastery.py --help` | Long option |
| `python rh_mastery.py help` | `help` subcommand |
| `python rh_mastery.py list-options` | Same output (legacy name) |

From Python:

```python
from rh_mastery import help as tool_help  # avoid shadowing builtin help()

tool_help()
# tool_help(open("cli-help.txt", "w"))
```

The module defines **`help(stream=None)`** as the canonical printer (see `rh_mastery.py`). Import it with an alias if you use Python’s built-in `help()` in the same session.

Subcommand-specific usage:

```bash
python rh_mastery.py sync -h
```

---

## Usage examples

```bash
# Full help + all product flags
python rh_mastery.py --help

# Sync one product (by alias from rh_config.json)
python rh_mastery.py sync --ansible
python rh_mastery.py sync --ocp
python rh_mastery.py sync --acm

# Sync by documentation slug (no alias required)
python rh_mastery.py sync --product red_hat_quay

# Pin a version (single product only; skips auto-detect)
python rh_mastery.py sync --acm -v 2.16
python rh_mastery.py sync --acm --force-version 2.16

# Sync every product in tracked_products (can take a long time)
python rh_mastery.py sync --all
```

---

## Project layout

| File | Role |
|------|------|
| `rh_mastery.py` | CLI, `help()`, version discovery, PDF mirror |
| `rh_config.json` | Settings, aliases, tracked versions |
| `requirements.txt` | Python dependencies |

---

## Disclaimer

For **personal or organizational** mirroring of publicly available documentation. Follow Red Hat’s [terms of use](https://redhat.com/en/about/terms-use) and site policies. Not affiliated with Red Hat.

---

## License

Add a `LICENSE` file in your GitHub repository if you publish this project; this README does not specify a license by itself.
