# rh-mastery RPM (RHEL 10)

Produces a **binary RPM** (and SRPM) that installs:

- `/usr/bin/rh-mastery` — launcher (sets `PYTHONPATH` for vendored wheels)
- `/usr/lib/rh-mastery/` — `rh_mastery.py`, wrapper, and `vendor/` (PyPI deps from `requirements.txt` at **build** time)
- `/etc/rh-mastery/` — default `rh_config.json` and `rh_storage.json` (`%config(noreplace)`)
- `/var/lib/rh-mastery/` — state and downloads (seeded from `/etc/rh-mastery` on first install if missing)
- `systemd` units: `rh-mastery-sync.service`, `rh-mastery-sync.timer` (not enabled by default)

## Prerequisites (build host)

- RHEL 10 (or compatible) with **network** during `rpmbuild` ( **`pip install`** into the build root).
- Packages: `git`, `rpm-build`, `python3`, `python3-pip`, `systemd-rpm-macros`

```bash
sudo dnf install -y git rpm-build python3 python3-pip systemd-rpm-macros
```

## Build

From the repository root:

```bash
chmod +x packaging/rpm/build-rpm.sh
./packaging/rpm/build-rpm.sh
```

Artifacts appear under `~/rpmbuild/RPMS/` and `~/rpmbuild/SRPMS/`.

Override the build tree:

```bash
RPMBUILD=/tmp/rpmbuild ./packaging/rpm/build-rpm.sh
```

## Install on RHEL 10

```bash
sudo dnf install -y ./rh-mastery-0.1.0-1.el10.x86_64.rpm
cd /var/lib/rh-mastery
sudo rh-mastery --help
```

Timer (optional):

```bash
sudo systemctl enable --now rh-mastery-sync.timer
```

## Notes

- **Offline builds:** prefetch wheels (e.g. `pip download -r requirements.txt -d SOURCES/wheels`) and adjust the spec to use `--no-index --find-links` — not included by default.
- **tokensaver:** lives in `tokensaver/` in the source tree (independent tool); **not** included in this RPM. Build a container from `tokensaver/Containerfile` or `pip install -e ./tokensaver` separately.
- Python dependencies are **vendored** because `pymupdf4llm` / PyMuPDF are not provided as RHEL 10 application stream packages in the same form as this app expects.
