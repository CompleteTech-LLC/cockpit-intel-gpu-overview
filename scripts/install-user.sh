#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COCKPIT_USER_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/cockpit"
LOCAL_BIN="$HOME/.local/libexec"
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
METRICS_PATH="${XDG_CACHE_HOME:-$HOME/.cache}/cockpit-intel-gpu/metrics.json"

if [[ ${EUID} -eq 0 ]]; then
  echo "Run without sudo: ./scripts/install-user.sh" >&2
  exit 1
fi

copy_cockpit_package() {
  local package="$1"
  local source="/usr/share/cockpit/$package"
  local target="$COCKPIT_USER_DIR/$package"
  if [[ ! -d "$source" ]]; then
    echo "Missing Cockpit package: $source" >&2
    exit 1
  fi
  rm -rf "$target"
  mkdir -p "$COCKPIT_USER_DIR"
  cp -a "$source" "$target"
}

patch_html() {
  local path="$1"
  local base_css="$2"
  local css="$3"
  local base_js="$4"
  local js="$5"

  python3 - "$path" "$base_css" "$css" "$base_js" "$js" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
base_css, css, base_js, js = sys.argv[2:]
text = path.read_text(encoding="utf-8")
css_tag = f'  <link rel="stylesheet" href="{css}" />'
js_tag = f'  <script type="text/javascript" src="{js}"></script>'

if css_tag not in text:
    text = text.replace(base_css, base_css + "\n" + css_tag)
if js_tag not in text:
    text = text.replace(base_js, base_js + "\n" + js_tag)

path.write_text(text, encoding="utf-8")
PY
}

copy_cockpit_package systemd
copy_cockpit_package metrics

install -d -m0755 "$COCKPIT_USER_DIR/intel-gpu"
install -m0644 "$ROOT/src/cockpit/manifest.json" "$COCKPIT_USER_DIR/intel-gpu/manifest.json"
install -m0644 "$ROOT/src/cockpit/index.html" "$COCKPIT_USER_DIR/intel-gpu/index.html"
install -m0644 "$ROOT/src/cockpit/gpu.css" "$COCKPIT_USER_DIR/intel-gpu/gpu.css"
install -m0644 "$ROOT/src/cockpit/gpu.js" "$COCKPIT_USER_DIR/intel-gpu/gpu.js"

python3 - "$COCKPIT_USER_DIR/intel-gpu/manifest.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data.pop("conditions", None)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.js" "$COCKPIT_USER_DIR/systemd/overview-intel-gpu.js"
install -m0644 "$ROOT/src/cockpit/overview-intel-gpu.css" "$COCKPIT_USER_DIR/systemd/overview-intel-gpu.css"
install -m0644 "$ROOT/src/cockpit/metrics-intel-gpu.js" "$COCKPIT_USER_DIR/metrics/metrics-intel-gpu.js"
install -m0644 "$ROOT/src/cockpit/metrics-intel-gpu.css" "$COCKPIT_USER_DIR/metrics/metrics-intel-gpu.css"

patch_html "$COCKPIT_USER_DIR/systemd/index.html" \
  '  <link rel="stylesheet" href="overview.css" />' \
  overview-intel-gpu.css \
  '  <script type="text/javascript" src="po.js"></script>' \
  overview-intel-gpu.js

patch_html "$COCKPIT_USER_DIR/metrics/index.html" \
  '    <link rel="stylesheet" href="index.css" />' \
  metrics-intel-gpu.css \
  '    <script type="text/javascript" src="index.js"></script>' \
  metrics-intel-gpu.js

install -d -m0755 "$LOCAL_BIN" "$USER_SYSTEMD" "$(dirname "$METRICS_PATH")"
install -m0755 "$ROOT/src/exporter/cockpit-intel-gpu-exporter.py" "$LOCAL_BIN/cockpit-intel-gpu-exporter"

cat > "$USER_SYSTEMD/cockpit-intel-gpu-exporter.service" <<EOF
[Unit]
Description=Cockpit Intel GPU telemetry exporter

[Service]
ExecStart=%h/.local/libexec/cockpit-intel-gpu-exporter --output %h/.cache/cockpit-intel-gpu/metrics.json
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now cockpit-intel-gpu-exporter.service >/dev/null

echo "Installed user Cockpit Intel GPU overview"
