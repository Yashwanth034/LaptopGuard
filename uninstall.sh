#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo bash uninstall.sh [--purge]" >&2
  exit 1
fi

touch /run/laptopguard-maintenance
trap 'rm -f /run/laptopguard-maintenance' EXIT
systemctl disable --now laptopguard-watchdog.timer laptopguard.service 2>/dev/null || true
systemctl stop laptopguard-resume.service laptopguard-watchdog.service 2>/dev/null || true
rm -f /etc/systemd/system/laptopguard.service \
      /etc/systemd/system/laptopguard-resume.service \
      /etc/systemd/system/laptopguard-watchdog.service \
      /etc/systemd/system/laptopguard-watchdog.timer \
      /usr/lib/systemd/system-sleep/laptopguard \
      /usr/local/bin/laptopguard
rm -rf /opt/laptopguard
systemctl daemon-reload

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf /etc/laptopguard /var/lib/laptopguard
  echo "LaptopGuard removed, including configuration and queued evidence."
else
  echo "LaptopGuard removed. /etc/laptopguard and /var/lib/laptopguard were preserved."
  echo "Use --purge only if you also want those deleted."
fi
