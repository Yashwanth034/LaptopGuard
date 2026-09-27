#!/usr/bin/env bash
set -euo pipefail
[[ -e /run/laptopguard-maintenance ]] && exit 0
if ! systemctl is-active --quiet laptopguard.service; then
  /usr/local/bin/laptopguard event tamper || true
  systemctl start laptopguard.service || true
fi
