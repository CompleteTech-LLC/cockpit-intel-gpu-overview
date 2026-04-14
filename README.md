# Cockpit Intel GPU Overview

Small Cockpit extension for showing Intel Arc Pro B60 telemetry in Cockpit.

The project has two parts:

- A root-owned systemd exporter that polls `xpu-smi` and writes read-only JSON to `/run/cockpit-intel-gpu/metrics.json`.
- A Cockpit package that renders the telemetry as a GPU page and inserts a compact GPU row into the Overview page Usage card.

The exporter runs as root because Intel GPU utilization and temperature metrics require MEI device access on this host.

## Install

From the repository root on the target host:

```bash
sudo ./scripts/install.sh
```

Then refresh the Cockpit browser tab.

## Files Installed

- `/usr/local/libexec/cockpit-intel-gpu-exporter`
- `/etc/systemd/system/cockpit-intel-gpu-exporter.service`
- `/usr/local/share/cockpit/intel-gpu/`
- `/usr/share/cockpit/systemd/overview-intel-gpu.js`
- `/usr/share/cockpit/systemd/overview-intel-gpu.css`
- A small script/style reference in `/usr/share/cockpit/systemd/index.html`

## Uninstall

```bash
sudo ./scripts/uninstall.sh
```

