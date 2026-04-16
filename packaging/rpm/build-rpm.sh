#!/usr/bin/env bash
# Build rh-mastery RPM for RHEL 10 (or compatible).
# Prereqs: git, rpm-build, python3-pip, tar, gzip
# Network: required during rpmbuild %%install (pip install into buildroot).
set -euo pipefail

TOP="$(cd "$(dirname "$0")/../.." && pwd)"
SPECFILE="${TOP}/packaging/rpm/rh-mastery.spec"
VERSION="${VERSION:-$(awk '/^Version:/ {print $2; exit}' "${SPECFILE}")}"
if ! git -C "${TOP}" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Not a git repository: ${TOP}" >&2
  exit 1
fi

if [[ ! -f "${SPECFILE}" ]]; then
  echo "Spec not found: ${SPECFILE}" >&2
  exit 1
fi

RPMBUILD="${RPMBUILD:-${HOME}/rpmbuild}"
mkdir -p "${RPMBUILD}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

TARBALL="${RPMBUILD}/SOURCES/rh-mastery-${VERSION}.tar.gz"
echo "==> Creating ${TARBALL}"
git -C "${TOP}" archive --format=tar.gz --prefix="rh-mastery-${VERSION}/" -o "${TARBALL}" HEAD

cp -f "${SPECFILE}" "${RPMBUILD}/SPECS/rh-mastery.spec"

echo "==> rpmbuild -ba (this runs pip install; needs network)"
rpmbuild --define "_topdir ${RPMBUILD}" -ba "${RPMBUILD}/SPECS/rh-mastery.spec"

echo "==> Done. RPMS under ${RPMBUILD}/RPMS/"
