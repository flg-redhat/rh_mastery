# rh-mastery

Mirror **Red Hat product documentation** from [docs.redhat.com](https://docs.redhat.com) as PDFs for offline reading. The tool discovers the current documentation version for each product, downloads PDFs into a local directory tree, and stores the last-synced version in `rh_config.json`. The **`convert`** command turns those PDFs into Markdown (for humans and agents), using the same product selection as **`sync`**.

You can run it as **`python3 rh_mastery.py …`** or use the **`rh-mastery`** bash wrapper (same arguments, no `python` prefix).

---

## What it does

| Capability | Details |
|------------|---------|
| **Version discovery** | Probes docs.redhat.com (redirects, page titles, link scraping, fallback patterns) to resolve the documentation version for a product *slug*. |
| **PDF mirroring** | Fetches PDFs from explicit `/pdf/` links or, for many products, from topic URLs like `…/{version}/pdf/{topic}/`. |
| **Product catalog** | `rh_config.json` maps short CLI names to Red Hat documentation slugs (aligned with the [product index](https://docs.redhat.com/en/products)). |
| **Flexible sync** | One product by alias, by slug, or all tracked products in one run. |
| **PDF → Markdown** | `convert` writes readable `.md` next to mirrored PDFs (default: `markdown/` under each version dir), with YAML front matter for provenance. |
| **Help** | `help()` / `-h` / `--help` / `help` / `list-options` — full command list and alias table (see [CLI help](#cli-help)). |

---

## Requirements

- Python **3.8+**
- Install dependencies:

```bash
pip install -r requirements.txt
```

(`requests`, `beautifulsoup4`, `packaging`, `pymupdf4llm` for `convert`)

---

## `rh-mastery` wrapper (recommended)

The **`rh-mastery`** executable in this repo is a thin bash wrapper around **`rh_mastery.py`**. It resolves `python3` (or `python`), finds **`rh_mastery.py`** next to the wrapper’s real path (**symlinks are followed**, so e.g. **`/usr/local/bin/rh-mastery`** → **`/opt/rh-mastery/`** in the container works), passes **`"$@"`** through unchanged, and sets **`RH_MASTERY_PROG=rh-mastery`** so `-h` / `--help` show **`rh-mastery`** as the program name (direct `python3 rh_mastery.py …` still shows **`rh_mastery.py`**).

| You run | Same as |
|---------|---------|
| `rh-mastery help` | `python3 rh_mastery.py help` |
| `rh-mastery sync --ocp` | `python3 rh_mastery.py sync --ocp` |
| `rh-mastery -h` | `python3 rh_mastery.py -h` |
| `rh-mastery list-options` | `python3 rh_mastery.py list-options` |

**Setup**

```bash
cd /path/to/rh_mastery
chmod +x rh-mastery    # once, if your checkout is not already executable
./rh-mastery --help
```

**On your `PATH`** (optional):

```bash
export PATH="/path/to/rh_mastery:$PATH"
rh-mastery sync --ansible
# or
ln -s /path/to/rh_mastery/rh-mastery ~/bin/rh-mastery
```

**Working directory:** `rh_config.json` is loaded from the **current working directory** (not from the wrapper’s install path). `cd` to the directory that contains your config before running `rh-mastery`, or keep config next to your project and run from there.

---

## Configuration

Run the script from the directory that contains **`rh_config.json`**, or adjust paths as needed.

| Key | Purpose |
|-----|---------|
| `settings.base_url` | Documentation base URL (default: `https://docs.redhat.com/en/documentation`). |
| `settings.download_base` | Root folder for downloaded PDFs (e.g. `./Notebookml/RHDocumentation`). |
| `settings.markdown_subdir` | Subfolder under each `{slug}/{version}/` for converted Markdown (default: `markdown`). |
| `settings.portal_url` | Product index (informational; default points at the Red Hat docs product list). |
| `aliases` | Short name → documentation slug (e.g. `acm` → `red_hat_advanced_cluster_management_for_kubernetes`). |
| `tracked_products` | Slug → last successfully synced version string (updated after each successful sync). |

PDFs are written to:

`{download_base}/{slug}/{version}/`

Converted Markdown (from `convert`) is written to:

`{download_base}/{slug}/{version}/{markdown_subdir}/{topic}.md`

Each file starts with a short YAML front matter block (`title`, `source_pdf`, `converted_at`, `engine`, `slug`, `version`).

---

## CLI help

These all print **every command**, argparse usage, and the **full product alias → slug** table:

| Invocation | Notes |
|------------|--------|
| `rh-mastery -h` or `python3 rh_mastery.py -h` | Short option |
| `rh-mastery --help` or `python3 rh_mastery.py --help` | Long option |
| `rh-mastery help` or `python3 rh_mastery.py help` | `help` subcommand |
| `rh-mastery list-options` or `python3 rh_mastery.py list-options` | Same output (legacy name) |

From Python:

```python
from rh_mastery import help as tool_help  # avoid shadowing builtin help()

tool_help()
# tool_help(open("cli-help.txt", "w"))
```

The module defines **`help(stream=None)`** as the canonical printer (see `rh_mastery.py`). Import it with an alias if you use Python’s built-in `help()` in the same session.

Subcommand-specific usage:

```bash
rh-mastery sync -h
# or: python3 rh_mastery.py sync -h
```

---

## Usage examples

Below, **`rh-mastery`** and **`python3 rh_mastery.py`** are interchangeable.

```bash
# Full help + all product flags
rh-mastery --help

# Sync one product (by alias from rh_config.json)
rh-mastery sync --ansible
rh-mastery sync --ocp
rh-mastery sync --acm

# Sync by documentation slug (no alias required)
rh-mastery sync --product red_hat_quay

# Pin a version (single product only; skips auto-detect)
rh-mastery sync --acm -v 2.16
rh-mastery sync --acm --force-version 2.16

# Sync every product in tracked_products (can take a long time)
rh-mastery sync --all
```

### PDF → Markdown (`convert`)

Product selection matches **`sync`**: `--all`, `--product SLUG`, or an alias flag (`--ansible`, `--ocp`, …). The version comes from **`tracked_products`** in `rh_config.json` unless you pass **`-v` / `--force-version`** with **exactly one** product (same rules as sync). Run **`sync`** first so PDFs and tracked versions exist.

```bash
# Default engine: PyMuPDF4LLM (falls back to PyMuPDF per-page markdown if needed)
rh-mastery convert --ansible
rh-mastery convert --all
rh-mastery convert --product red_hat_quay --force   # overwrite existing .md

# Optional: Docling (heavier; better on some complex layouts). Install deps first:
# pip install -r requirements-docling.txt
rh-mastery convert --acm --engine docling
```

**Optional Docling:** [`requirements-docling.txt`](requirements-docling.txt) adds the **Docling** stack (large download, more CPU/RAM). Use it only when you need stronger layout/table handling than the default pipeline.

---

## Container image (UBI 10 + systemd)

The **`Containerfile`** builds an image from **[Red Hat Universal Base Image 10 Init](https://catalog.redhat.com/en/software/containers/ubi10/ubi-init/66f2b3428a972331bb915d51)** (`registry.access.redhat.com/ubi10/ubi-init`). That variant runs **`/sbin/init`** (systemd) as PID 1 so you can use **`systemctl`**, **timers**, and **`crond`** inside the container.

The image installs this repository under **`/opt/rh-mastery`**, sets **`download_base`** to **`/var/lib/rh-mastery/RHDocumentation`**, and keeps **`rh_config.json`** under **`/var/lib/rh-mastery`** (use a **volume** there to persist config and mirrors).

### Build

```bash
cd /path/to/rh_mastery
podman build -f Containerfile -t rh-mastery:latest .
```

(`docker build -f Containerfile -t rh-mastery:latest .` works similarly; use a run invocation that supports systemd if you need `systemctl` inside the container.)

### Run (Podman + systemd)

```bash
podman run -d --name rh-mastery \
  --systemd=always \
  -v rh-mastery-data:/var/lib/rh-mastery \
  rh-mastery:latest
```

- **`--systemd=always`** lets systemd run as init and **`systemctl`** work as expected inside the container.
- Mount **`/var/lib/rh-mastery`** so `rh_config.json` and downloaded PDFs survive container recreation.

### One-off commands

```bash
podman exec -it rh-mastery bash
rh-mastery --help
rh-mastery sync --ansible
rh-mastery convert --ansible
```

### Schedule with systemd (timer)

Units are installed but **not** enabled by default (avoid surprise full-catalog syncs). To run **`rh-mastery sync --all`** weekly:

```bash
podman exec -it rh-mastery systemctl enable --now rh-mastery-sync.timer
podman exec -it rh-mastery systemctl list-timers
```

Run the service once manually:

```bash
podman exec -it rh-mastery systemctl start rh-mastery-sync.service
podman exec -it rh-mastery journalctl -u rh-mastery-sync.service -n 50 --no-pager
```

Override the command (e.g. sync a single product) with a **drop-in**:

```bash
podman exec -it rh-mastery bash -c 'mkdir -p /etc/systemd/system/rh-mastery-sync.service.d && printf "[Service]\nExecStart=\nExecStart=/opt/rh-mastery/rh-mastery sync --ocp\n" > /etc/systemd/system/rh-mastery-sync.service.d/override.conf'
podman exec -it rh-mastery systemctl daemon-reload
```

### Schedule with cron

**`crond`** is enabled at image build time. Copy the example and adjust the schedule:

```bash
podman exec -it rh-mastery cp /usr/share/doc/rh-mastery/cron/rh-mastery.example /etc/cron.d/rh-mastery
podman exec -it rh-mastery chmod 0644 /etc/cron.d/rh-mastery
# Edit the file if needed, then:
podman exec -it rh-mastery systemctl status crond
```

### Layout in the image

| Path | Purpose |
|------|---------|
| `/opt/rh-mastery/` | Application (`rh_mastery.py`, `rh-mastery`, deps) |
| `/var/lib/rh-mastery/` | `rh_config.json`, mirrored PDFs (volume recommended) |
| `/etc/systemd/system/rh-mastery-sync.{service,timer}` | Optional scheduled sync |
| `/usr/share/doc/rh-mastery/cron/` | Cron example |

---

## Project layout

| File | Role |
|------|------|
| `rh_mastery.py` | CLI, `help()`, version discovery, PDF mirror |
| `rh-mastery` | Executable bash wrapper (forwards all args to `rh_mastery.py`) |
| `rh_config.json` | Settings, aliases, tracked versions |
| `requirements.txt` | Python dependencies (includes `pymupdf4llm` for `convert`) |
| `requirements-docling.txt` | Optional stack for `convert --engine docling` |
| `Containerfile` | UBI 10 `ubi-init` image with systemd + app install |
| `container/systemd/` | `rh-mastery-sync.service` / `.timer` for optional scheduling |
| `container/cron/` | Example crontab fragment |
| `.containerignore` / `.dockerignore` | Exclude VCS, venvs, caches, and local mirror dirs from the image build context (Podman and Docker) |

---

## Disclaimer

For **personal or organizational** mirroring of publicly available documentation. Follow Red Hat’s [terms of use](https://redhat.com/en/about/terms-use) and site policies. Not affiliated with Red Hat.

---

## License

Add a `LICENSE` file in your GitHub repository if you publish this project; this README does not specify a license by itself.
