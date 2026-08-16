#!/bin/bash
# First-boot initialisation: copy default config files into the data volume if they
# are missing.  This makes bind-mount usage work out of the box — when an empty host
# directory is mounted at /var/lib/rh-mastery the container still gets valid defaults.
# Named-volume users are unaffected: existing files are never overwritten.
set -euo pipefail

DATA=/var/lib/rh-mastery
DEFAULTS=/opt/rh-mastery/defaults

mkdir -p "$DATA"

for f in rh_config.json rh_storage.json; do
    if [[ ! -f "$DATA/$f" ]]; then
        echo "rh-mastery-init: seeding $f from defaults"
        cp "$DEFAULTS/$f" "$DATA/$f"
    fi
done
