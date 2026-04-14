#!/usr/bin/env bash
set -euo pipefail

COCKPIT_SYSTEMD_INDEX="/usr/share/cockpit/systemd/index.html"
BACKUP="/usr/share/cockpit/systemd/index.html.cockpit-intel-gpu.bak"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/uninstall.sh" >&2
  exit 1
fi

systemctl disable --now cockpit-intel-gpu-exporter.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/cockpit-intel-gpu-exporter.service
rm -f /usr/local/libexec/cockpit-intel-gpu-exporter
rm -rf /usr/local/share/cockpit/intel-gpu
rm -f /usr/share/cockpit/systemd/overview-intel-gpu.js
rm -f /usr/share/cockpit/systemd/overview-intel-gpu.css

if [[ -f "$BACKUP" ]]; then
  cp -a "$BACKUP" "$COCKPIT_SYSTEMD_INDEX"
else
  python3 - "$COCKPIT_SYSTEMD_INDEX" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace('  <link rel="stylesheet" href="overview-intel-gpu.css" />\n', '')
text = text.replace('  <script type="text/javascript" src="overview-intel-gpu.js"></script>\n', '')
path.write_text(text, encoding="utf-8")
PY
fi

systemctl daemon-reload
systemctl try-restart cockpit.socket >/dev/null 2>&1 || true

echo "Uninstalled cockpit-intel-gpu-overview"

