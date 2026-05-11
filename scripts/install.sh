#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COCKPIT_SYSTEMD_INDEX="/usr/share/cockpit/systemd/index.html"
COCKPIT_METRICS_INDEX="/usr/share/cockpit/metrics/index.html"
BACKUP="/usr/share/cockpit/systemd/index.html.cockpit-intel-gpu.bak"
METRICS_BACKUP="/usr/share/cockpit/metrics/index.html.cockpit-intel-gpu.bak"
COCKPIT_SENSORS_URL="https://github.com/ocristopfer/cockpit-sensors/releases/latest/download/cockpit-sensors.tar.xz"
COCKPIT_SENSORS_DIR="/usr/share/cockpit/sensors"
COCKPIT_SENSORS_MARKER="/usr/share/cockpit/sensors/.cockpit-intel-gpu-managed"

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/install.sh" >&2
  exit 1
fi

install_host_sensor_tools() {
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates lm-sensors wget xz-utils
  elif ! command -v sensors >/dev/null 2>&1; then
    echo "lm-sensors is not installed and this installer only knows apt-get hosts." >&2
    exit 1
  fi

  sensors-detect --auto >/dev/null 2>&1 || true

  for module in k10temp drivetemp nct6775; do
    modprobe -q "$module" >/dev/null 2>&1 || true
  done
}

install_cockpit_sensors() {
  if [[ -e "$COCKPIT_SENSORS_DIR" ]]; then
    echo "Cockpit Sensors already exists at $COCKPIT_SENSORS_DIR; leaving it unchanged."
    return
  fi

  (
  local work
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT

  wget -q -O "$work/cockpit-sensors.tar.xz" "$COCKPIT_SENSORS_URL"
  tar -xf "$work/cockpit-sensors.tar.xz" -C "$work" cockpit-sensors/dist

  install -d -m0755 /usr/share/cockpit
  mv "$work/cockpit-sensors/dist" "$COCKPIT_SENSORS_DIR"
  touch "$COCKPIT_SENSORS_MARKER"
  chmod -R a+rX "$COCKPIT_SENSORS_DIR"
  )
}

if ! command -v xpu-smi >/dev/null 2>&1; then
  echo "Warning: xpu-smi is not installed; the Intel GPU Cockpit page will not collect B60 telemetry." >&2
fi

install_host_sensor_tools
install_cockpit_sensors

install -Dm0755 "$ROOT/src/exporter/cockpit-intel-gpu-exporter.py" /usr/local/libexec/cockpit-intel-gpu-exporter
install -Dm0644 "$ROOT/systemd/cockpit-intel-gpu-exporter.service" /etc/systemd/system/cockpit-intel-gpu-exporter.service

install -d -m0755 /usr/local/share/cockpit/intel-gpu
install -m0644 "$ROOT/src/cockpit/manifest.json" /usr/local/share/cockpit/intel-gpu/manifest.json
install -m0644 "$ROOT/src/cockpit/index.html" /usr/local/share/cockpit/intel-gpu/index.html
install -m0644 "$ROOT/src/cockpit/gpu.css" /usr/local/share/cockpit/intel-gpu/gpu.css
install -m0644 "$ROOT/src/cockpit/gpu.js" /usr/local/share/cockpit/intel-gpu/gpu.js

install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.js" /usr/share/cockpit/systemd/overview-intel-gpu.js
install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.css" /usr/share/cockpit/systemd/overview-intel-gpu.css
install -m0644 "$ROOT/src/cockpit/metrics-intel-gpu.js" /usr/share/cockpit/metrics/metrics-intel-gpu.js
install -m0644 "$ROOT/src/cockpit/metrics-intel-gpu.css" /usr/share/cockpit/metrics/metrics-intel-gpu.css

if [[ ! -f "$BACKUP" ]]; then
  cp -a "$COCKPIT_SYSTEMD_INDEX" "$BACKUP"
fi

if [[ ! -f "$METRICS_BACKUP" ]]; then
  cp -a "$COCKPIT_METRICS_INDEX" "$METRICS_BACKUP"
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

python3 - "$COCKPIT_METRICS_INDEX" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
css = '    <link rel="stylesheet" href="metrics-intel-gpu.css" />'
js = '    <script type="text/javascript" src="metrics-intel-gpu.js"></script>'

if css not in text:
    text = text.replace('    <link rel="stylesheet" href="index.css" />', '    <link rel="stylesheet" href="index.css" />\n' + css)
if js not in text:
    text = text.replace('    <script type="text/javascript" src="index.js"></script>', '    <script type="text/javascript" src="index.js"></script>\n' + js)

path.write_text(text, encoding="utf-8")
PY

systemctl daemon-reload
systemctl enable cockpit-intel-gpu-exporter.service >/dev/null
systemctl restart cockpit-intel-gpu-exporter.service
systemctl try-restart cockpit.socket >/dev/null 2>&1 || true

echo "Installed cockpit-intel-gpu-overview"
