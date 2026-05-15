# rh-mastery — RHEL UBI 10 with systemd (PID 1 = /sbin/init) for systemctl / timers / cron.
# Build: podman build -f Containerfile -t rh-mastery:latest .
# Run:  see README.md (podman run --systemd=always …)

FROM registry.access.redhat.com/ubi10/ubi-init:latest

USER root

RUN dnf -y install \
        python3 \
        python3-pip \
        cronie \
    && dnf clean all

WORKDIR /opt/rh-mastery
COPY requirements.txt rh_mastery.py rh-mastery ./
RUN pip3 install --no-cache-dir -r requirements.txt \
    && chmod +x rh-mastery \
    && ln -sf /opt/rh-mastery/rh-mastery /usr/local/bin/rh-mastery

# Default config templates stored in /opt/rh-mastery/defaults/
# These are seeded into /var/lib/rh-mastery at first boot by rh-mastery-init.service,
# which handles both named-volume and host bind-mount (-v ./data:/var/lib/rh-mastery).
RUN mkdir -p /opt/rh-mastery/defaults
COPY rh_config.json /opt/rh-mastery/defaults/rh_config.json
COPY rh_storage.json /opt/rh-mastery/defaults/rh_storage.json
RUN python3 <<'PY'
import json
cfg_path = "/opt/rh-mastery/defaults/rh_config.json"
with open(cfg_path) as f:
    cfg = json.load(f)
cfg["settings"]["download_base"] = "/var/lib/rh-mastery/RHDocumentation"
with open(cfg_path, "w") as f:
    json.dump(cfg, f, indent=4)

storage_path = "/opt/rh-mastery/defaults/rh_storage.json"
with open(storage_path) as f:
    storage = json.load(f)
storage["mount_point"] = "/var/lib/rh-mastery"
storage["sync_subdir"] = "RHDocumentation"
with open(storage_path, "w") as f:
    json.dump(storage, f, indent=4)
PY

# Persistent config + downloads (mount a volume or bind-mount a host dir here).
# Pre-populate for named-volume use; bind-mount users are handled by the init service.
RUN mkdir -p /var/lib/rh-mastery \
    && cp /opt/rh-mastery/defaults/rh_config.json /var/lib/rh-mastery/ \
    && cp /opt/rh-mastery/defaults/rh_storage.json /var/lib/rh-mastery/

# Init script: seeds default configs on first boot when the volume/bind-mount is empty
COPY container/container-init.sh /opt/rh-mastery/container-init.sh
RUN chmod +x /opt/rh-mastery/container-init.sh

COPY container/systemd/rh-mastery-sync.service /etc/systemd/system/
COPY container/systemd/rh-mastery-sync.timer /etc/systemd/system/
COPY container/systemd/rh-mastery-init.service /etc/systemd/system/
RUN mkdir -p /usr/share/doc/rh-mastery/cron
COPY container/cron/rh-mastery.example /usr/share/doc/rh-mastery/cron/rh-mastery.example

# Enable crond and the first-boot init service
RUN ln -sf /usr/lib/systemd/system/crond.service \
        /etc/systemd/system/multi-user.target.wants/crond.service \
    && ln -sf /etc/systemd/system/rh-mastery-init.service \
        /etc/systemd/system/sysinit.target.wants/rh-mastery-init.service

VOLUME ["/var/lib/rh-mastery"]

WORKDIR /var/lib/rh-mastery

# ubi-init: systemd as PID 1 (do not override without replacing init)
STOPSIGNAL SIGRTMIN+3
