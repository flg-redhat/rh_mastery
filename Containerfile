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

# Persistent config + downloads (mount a volume here at runtime)
RUN mkdir -p /var/lib/rh-mastery
COPY rh_config.json /var/lib/rh-mastery/rh_config.json
RUN python3 <<'PY'
import json
path = "/var/lib/rh-mastery/rh_config.json"
with open(path) as f:
    cfg = json.load(f)
cfg["settings"]["download_base"] = "/var/lib/rh-mastery/RHDocumentation"
with open(path, "w") as f:
    json.dump(cfg, f, indent=4)
PY

COPY container/systemd/rh-mastery-sync.service /etc/systemd/system/
COPY container/systemd/rh-mastery-sync.timer /etc/systemd/system/
RUN mkdir -p /usr/share/doc/rh-mastery/cron
COPY container/cron/rh-mastery.example /usr/share/doc/rh-mastery/cron/rh-mastery.example

# Enable crond so cron-based scheduling works; timer is installed but not enabled (opt-in).
RUN ln -sf /usr/lib/systemd/system/crond.service \
        /etc/systemd/system/multi-user.target.wants/crond.service

VOLUME ["/var/lib/rh-mastery"]

WORKDIR /var/lib/rh-mastery

# ubi-init: systemd as PID 1 (do not override without replacing init)
STOPSIGNAL SIGRTMIN+3
