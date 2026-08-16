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
| **PDF → OKF** | `convert --format okf` writes Markdown first, then an [OKF v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle under `okf/` for agent/RAG consumption. |
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

## RPM package (RHEL 10)

A specfile and helper script build a **binary RPM** (vendored Python wheels, systemd units, `/etc` + `/var/lib` layout). See **[packaging/rpm/README.md](packaging/rpm/README.md)** and run `./packaging/rpm/build-rpm.sh` on a RHEL 10 build host with network access for `pip` during `rpmbuild`.

---

## tokensaver (bundled, independent)

The **[tokensaver/](tokensaver/)** subdirectory is a separate CLI and Python package for PDF / docx / ODP → Markdown. It does **not** import `rh_mastery` or read `rh_config.json` / `rh_storage.json`. **rh-mastery** keeps its own **`convert`** for mirrored PDFs only.

- Install: `cd tokensaver && pip install -e .`
- Container: `podman build -f tokensaver/Containerfile -t tokensaver:latest .` (state volume: **`/var/lib/tokensaver`**)

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

**Working directory:** `rh_config.json` and optional `rh_storage.json` are loaded from the **current working directory** (not from the wrapper's install path). `cd` to the directory that contains your config files before running `rh-mastery`.

---

## Configuration

Run the script from the directory that contains **`rh_config.json`** (and optionally **`rh_storage.json`**), or adjust paths as needed.

| Key | Purpose |
|-----|---------|
| `settings.base_url` | Documentation base URL (default: `https://docs.redhat.com/en/documentation`). |
| `settings.download_base` | Legacy default root for downloaded PDFs. Used when `rh_storage.json` is missing. |
| `settings.markdown_subdir` | Subfolder under each `{slug}/{version}/` for converted Markdown (default: `markdown`). |
| `settings.okf_bundle_root` | OKF bundle root under `download_base` (default: `okf`). |
| `settings.okf_chunk_heading_level` | Heading level for OKF concept splits (default: `2` = `##`). |
| `settings.okf_max_concept_chars` | Max characters per concept before overflow split (default: `12000`; `0` = disable). |
| `settings.okf_spec_version` | OKF spec version written to global bundle `index.md` (default: `0.2`). |
| `settings.portal_url` | Product index (informational; default points at the Red Hat docs product list). |
| `aliases` | Short name → documentation slug (e.g. `acm` → `red_hat_advanced_cluster_management_for_kubernetes`). |
| `tracked_products` | Slug → last successfully synced version string (updated after each successful sync). |

PDFs are written to:

`{download_base}/{slug}/{version}/`

`download_base` is resolved from `rh_storage.json` first:

- `download_base` (explicit full path), or
- `mount_point` + `sync_subdir` (recommended for separate drive mounts).

Converted Markdown (from `convert`) is written to:

`{download_base}/{slug}/{version}/{markdown_subdir}/{topic}.md`

Each file starts with a short YAML front matter block (`title`, `source` or `source_pdf`, `converted_at`, `engine`, `slug`, `version` depending on converter).

OKF bundles (from `convert --format okf`) are written to:

`{download_base}/okf/{slug}/{version}/{guide_stem}/`

Attach **`{download_base}/okf/`** for the full corpus, or **`{download_base}/okf/{slug}/{version}/`** for one product version. Markdown under `markdown/` is always retained as the reference extraction layer.

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

**Default:** convert the **entire on-disk mirror** under `download_base` — no product flag required. rh-mastery discovers every `{slug}/{version}/` directory that contains PDFs or Markdown.

**Partial convert:** pass **`--product SLUG`**, any alias flag (`--ansible`, `--offline_knowledge_portal`, …), or **`--all`** (only products listed in `tracked_products`).

| Goal | Command |
|------|---------|
| **Convert entire mirror** (default) | `rh-mastery convert --format okf` |
| **Sync updates, then convert all** | `rh-mastery convert --format okf --sync-first` |
| **One product only** | `rh-mastery convert --offline_knowledge_portal --format okf` |
| **Tracked products only** | `rh-mastery convert --all --format okf` |

By default, **`convert` never contacts docs.redhat.com** — it only reads PDFs/Markdown on disk. Pass **`--sync-first`** to refresh downloads before converting.

```bash
rh-mastery convert --format okf              # entire mirror → OKF
rh-mastery convert --ansible --format okf    # partial: Ansible only
rh-mastery convert --all --format okf        # tracked_products subset
rh-mastery convert --format okf --sync-first   # sync all targets, then convert
```

**`--format okf`** runs the full pipeline in one command: **(1) PDF→Markdown** (always written to `markdown/` as reference), then **(2) Markdown→OKF bundle**. You do not need a separate Markdown step. The default PDF engine for OKF is **docling** on non-FIPS hosts; on **RHEL/OpenSSL FIPS** systems rh-mastery automatically uses **pymupdf** with plain-text extraction. Override with `--engine pymupdf`; `--engine docling` fails fast on FIPS. See [`docs/OKF_IMPLEMENTATION_SPEC.md`](docs/OKF_IMPLEMENTATION_SPEC.md) for bundle layout and agent attachment.

**Optional Docling:** [`requirements-docling.txt`](requirements-docling.txt) adds the **Docling** stack (large download, more CPU/RAM). Use it only when you need stronger layout/table handling than the default pipeline.

For Markdown from **arbitrary** paths (any folder or files outside the mirror layout), use the bundled **tokensaver** tool in [`tokensaver/`](tokensaver/README.md): `pip install -e ./tokensaver`, then `tokensaver convert -d … -o …` or `-f … -o …`. It is **independent** of `rh-mastery` (no shared config). On servers/containers, use **`/var/lib/tokensaver`** as the data directory (see `tokensaver/README.md` and `tokensaver/Containerfile`).

---

## Container image (UBI 10 + systemd)

The **`Containerfile`** builds an image from **[Red Hat Universal Base Image 10 Init](https://catalog.redhat.com/en/software/containers/ubi10/ubi-init/66f2b3428a972331bb915d51)** (`registry.access.redhat.com/ubi10/ubi-init`). That variant runs **`/sbin/init`** (systemd) as PID 1 so you can use **`systemctl`**, **timers**, and **`crond`** inside the container.

The image installs this repository under **`/opt/rh-mastery`**, sets storage to **`/var/lib/rh-mastery/RHDocumentation`** via **`rh_storage.json`**, and keeps **`rh_config.json`** + **`rh_storage.json`** under **`/var/lib/rh-mastery`** (use a **volume** there to persist config and mirrors).

### Build

```bash
cd /path/to/rh_mastery
podman build -f Containerfile -t rh-mastery:latest .
```

(`docker build -f Containerfile -t rh-mastery:latest .` works similarly; use a run invocation that supports systemd if you need `systemctl` inside the container.)

### Run (Podman + systemd)

**Named volume** (default; Podman manages storage inside the VM):

```bash
podman run -d --name rh-mastery \
  --systemd=always \
  -v rh-mastery-data:/var/lib/rh-mastery \
  rh-mastery:latest
```

**Bind-mount a host directory** (recommended on macOS with Podman machine — files are directly accessible on the host):

```bash
mkdir -p ./data
podman run -d --name rh-mastery \
  --systemd=always \
  -v ./data:/var/lib/rh-mastery:Z \
  rh-mastery:latest
```

On first boot `rh-mastery-init.service` detects an empty volume and seeds `rh_config.json` and `rh_storage.json` from the built-in defaults. Subsequent starts leave existing files untouched. Downloaded PDFs and converted Markdown will appear under `./data/RHDocumentation/`.

> **macOS / Podman machine note:** Podman automatically shares paths under `/Users` with the VM via virtfs, so any subdirectory of your home folder works as a bind-mount source without extra configuration.

- **`--systemd=always`** lets systemd run as init and **`systemctl`** work as expected inside the container.
- Mount **`/var/lib/rh-mastery`** so `rh_config.json`, `rh_storage.json`, and downloaded PDFs survive container recreation.

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
| `/var/lib/rh-mastery/` | `rh_config.json`, `rh_storage.json`, mirrored PDFs (volume recommended) |
| `/etc/systemd/system/rh-mastery-sync.{service,timer}` | Optional scheduled sync |
| `/usr/share/doc/rh-mastery/cron/` | Cron example |

---

## Project layout

| File | Role |
|------|------|
| `rh_mastery.py` | CLI, `help()`, version discovery, PDF mirror |
| `rh-mastery` | Executable bash wrapper (forwards all args to `rh_mastery.py`) |
| `rh_config.json` | Product settings, aliases, tracked versions |
| `rh_storage.json` | Storage path config (`mount_point`, `sync_subdir`, or explicit `download_base`) |
| `requirements.txt` | Python dependencies (includes `pymupdf4llm` for `convert`) |
| `requirements-docling.txt` | Optional stack for `convert --engine docling` |
| `Containerfile` | UBI 10 `ubi-init` image with systemd + app install |
| `container/systemd/` | `rh-mastery-sync.service` / `.timer` for optional scheduling |
| `container/cron/` | Example crontab fragment |
| `.containerignore` / `.dockerignore` | Exclude VCS, venvs, caches, and local mirror dirs from the image build context (Podman and Docker) |
| `packaging/rpm/` | RHEL 10 RPM spec, systemd snippets for the package, `build-rpm.sh` |
| `tokensaver/` | Standalone PDF/docx/odp → Markdown tool (`/var/lib/tokensaver` in container docs) |

---

## Disclaimer

For **personal or organizational** mirroring of publicly available documentation. Follow Red Hat’s [terms of use](https://redhat.com/en/about/terms-use) and site policies. Not affiliated with Red Hat.

---

## License

Add a `LICENSE` file in your GitHub repository if you publish this project; this README does not specify a license by itself.
