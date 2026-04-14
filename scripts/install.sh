#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COCKPIT_SYSTEMD_INDEX="/usr/share/cockpit/systemd/index.html"
BACKUP="/usr/share/cockpit/systemd/index.html.cockpit-intel-gpu.bak"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install.sh" >&2
  exit 1
fi

install -Dm0755 "$ROOT/src/exporter/cockpit-intel-gpu-exporter.py" /usr/local/libexec/cockpit-intel-gpu-exporter
install -Dm0644 "$ROOT/systemd/cockpit-intel-gpu-exporter.service" /etc/systemd/system/cockpit-intel-gpu-exporter.service

install -d -m0755 /usr/local/share/cockpit/intel-gpu
install -m0644 "$ROOT/src/cockpit/manifest.json" /usr/local/share/cockpit/intel-gpu/manifest.json
install -m0644 "$ROOT/src/cockpit/index.html" /usr/local/share/cockpit/intel-gpu/index.html
install -m0644 "$ROOT/src/cockpit/gpu.css" /usr/local/share/cockpit/intel-gpu/gpu.css
install -m0644 "$ROOT/src/cockpit/gpu.js" /usr/local/share/cockpit/intel-gpu/gpu.js

install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.js" /usr/share/cockpit/systemd/overview-intel-gpu.js
install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.css" /usr/share/cockpit/systemd/overview-intel-gpu.css

if [[ ! -f "$BACKUP" ]]; then
  cp -a "$COCKPIT_SYSTEMD_INDEX" "$BACKUP"
fi

python3 - "$COCKPIT_SYSTEMD_INDEX" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
css = '  <link rel="stylesheet" href="overview-intel-gpu.css" />'
js = '  <script type="text/javascript" src="overview-intel-gpu.js"></script>'

if css not in text:
    text = text.replace('  <link rel="stylesheet" href="overview.css" />', '  <link rel="stylesheet" href="overview.css" />\n' + css)
if js not in text:
    text = text.replace('  <script type="text/javascript" src="po.js"></script>', '  <script type="text/javascript" src="po.js"></script>\n' + js)

path.write_text(text, encoding="utf-8")
PY

systemctl daemon-reload
systemctl enable cockpit-intel-gpu-exporter.service >/dev/null
systemctl restart cockpit-intel-gpu-exporter.service
systemctl try-restart cockpit.socket >/dev/null 2>&1 || true

echo "Installed cockpit-intel-gpu-overview"
