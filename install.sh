#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo bash install.sh" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR=/opt/laptopguard
APP_DIR="$INSTALL_DIR/app"
BACKUP_DIR="$INSTALL_DIR/app.previous"
MAINT=/run/laptopguard-maintenance
WAS_ENABLED=0
WAS_ACTIVE=0
INSTALL_SUCCESS=0
systemctl is-enabled --quiet laptopguard.service 2>/dev/null && WAS_ENABLED=1 || true
systemctl is-active --quiet laptopguard.service 2>/dev/null && WAS_ACTIVE=1 || true

touch "$MAINT"
cleanup() {
  if [[ $INSTALL_SUCCESS -ne 1 && -d "$BACKUP_DIR" ]]; then
    rm -rf "$APP_DIR"
    mv "$BACKUP_DIR" "$APP_DIR"
  fi
  rm -f "$MAINT"
  if [[ $INSTALL_SUCCESS -ne 1 && $WAS_ACTIVE -eq 1 ]]; then
    systemctl daemon-reload 2>/dev/null || true
    systemctl start laptopguard.service laptopguard-watchdog.timer 2>/dev/null || true
  fi
}
trap cleanup EXIT

PACKAGES=(
  python3 python3-opencv opencv-data python3-numpy python3-cryptography
  python3-gi gir1.2-gtk-3.0 brightnessctl network-manager modemmanager geoclue-2.0
  mokutil gnome-screenshot scrot v4l-utils iproute2 iw
)
if ! /usr/bin/python3 -c 'import tomllib' >/dev/null 2>&1; then
  PACKAGES+=(python3-tomli)
fi

apt-get update
apt-get install -y "${PACKAGES[@]}"

systemctl stop laptopguard-watchdog.timer laptopguard.service 2>/dev/null || true
install -d -m 0755 "$INSTALL_DIR"
rm -rf "$BACKUP_DIR"
if [[ -d "$APP_DIR" ]]; then
  mv "$APP_DIR" "$BACKUP_DIR"
fi
install -d -m 0755 "$APP_DIR"
cp -a "$ROOT_DIR/src" "$ROOT_DIR/README.md" "$ROOT_DIR/docs" "$ROOT_DIR/scripts" "$APP_DIR/"

cat > /usr/local/bin/laptopguard <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=/opt/laptopguard/app/src${PYTHONPATH:+:$PYTHONPATH}
exec /usr/bin/python3 -m laptopguard.cli "$@"
EOF
chmod 0755 /usr/local/bin/laptopguard

install -d -m 0700 /etc/laptopguard /var/lib/laptopguard /var/lib/laptopguard/evidence /var/lib/laptopguard/queue
if [[ ! -f /etc/laptopguard/config.toml ]]; then
  install -m 0600 "$ROOT_DIR/config.example.toml" /etc/laptopguard/config.toml
fi
PYTHONPATH="$APP_DIR/src" /usr/bin/python3 - <<'PYCFG'
from laptopguard.config import migrate_failed_auth_policy, migrate_normal_lifecycle_policy

migrate_failed_auth_policy('/etc/laptopguard/config.toml', threshold=3)
migrate_normal_lifecycle_policy('/etc/laptopguard/config.toml')
PYCFG
rm -f /var/lib/laptopguard/failed-auth-state.json
rm -rf /var/lib/laptopguard/pending-auth
# Clear any automatic tracking state left by v0.1.10 or earlier so upgrades stop repeated location emails immediately.
rm -f /var/lib/laptopguard/tracking-until
# v0.1.15 makes ordinary boot/resume non-alert lifecycle events. Remove only
# legacy queued boot/resume alerts so an upgrade cannot send obsolete mail;
# preserve failed-auth/tamper/manual evidence.
PYTHONPATH="$APP_DIR/src" /usr/bin/python3 - <<'PYQUEUE'
from pathlib import Path
from laptopguard.queue_store import EncryptedQueue

queue = EncryptedQueue(Path('/var/lib/laptopguard/queue'), Path('/var/lib/laptopguard/queue.key'))
queue.remove_events({'boot', 'resume'})
PYQUEUE

install -m 0644 "$ROOT_DIR/systemd/laptopguard.service" /etc/systemd/system/laptopguard.service
install -m 0644 "$ROOT_DIR/systemd/laptopguard-resume.service" /etc/systemd/system/laptopguard-resume.service
install -m 0644 "$ROOT_DIR/systemd/laptopguard-watchdog.service" /etc/systemd/system/laptopguard-watchdog.service
install -m 0644 "$ROOT_DIR/systemd/laptopguard-watchdog.timer" /etc/systemd/system/laptopguard-watchdog.timer
install -m 0755 "$ROOT_DIR/scripts/laptopguard-sleep-hook" /usr/lib/systemd/system-sleep/laptopguard
install -m 0755 "$ROOT_DIR/scripts/watchdog.sh" "$APP_DIR/scripts/watchdog.sh"

# The installer legitimately changes LaptopGuard-managed files that are also
# protected by the tamper monitor. Refresh only those known managed baseline
# entries before the service is restarted. Never bless unrelated OS files.
PYTHONPATH="$APP_DIR/src" /usr/bin/python3 - <<'PYTAMPER'
from pathlib import Path
from laptopguard.tamper import (
    CRITICAL_PATHS,
    TRUSTED_INSTALL_PATHS,
    TamperBaseline,
)

baseline = TamperBaseline(Path('/var/lib/laptopguard/tamper-baseline.json'), CRITICAL_PATHS)
baseline.trust_current(TRUSTED_INSTALL_PATHS)
PYTAMPER

systemctl daemon-reload
if [[ $WAS_ENABLED -eq 1 || $WAS_ACTIVE -eq 1 ]]; then
  systemctl enable --now laptopguard.service laptopguard-watchdog.timer
  echo "LaptopGuard updated and restarted with existing configuration."
else
  echo "LaptopGuard installed. The service is NOT enabled until email is configured."
  echo "Next: sudo laptopguard configure"
fi
rm -rf "$BACKUP_DIR"
INSTALL_SUCCESS=1
echo "Then: sudo laptopguard doctor"
echo "Then: sudo laptopguard test"
