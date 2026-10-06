<p align="center"><img src="assets/banner.jpg" alt="An isometric graphics card on a server rack sending glowing telemetry traces up into floating gauge, temperature and line-chart dashboards." width="100%"></p>

# Cockpit Intel GPU Overview

Cockpit extension that shows Intel Arc Pro B60 GPU telemetry collected from `xpu-smi`, for Linux hosts that already run Cockpit. It was written for one host (an Arc Pro B60 on an apt-based Linux system); other hardware and distributions are not covered here.

The project has three parts:

- A root-owned systemd exporter that polls `xpu-smi` and writes read-only JSON to `/run/cockpit-intel-gpu/metrics.json` plus minute history to `/run/cockpit-intel-gpu/history.json`.
- A Cockpit package that renders the telemetry as a GPU page, inserts separate GPU and GPU memory rows into the Overview page Usage card, adds a standalone Overview GPU card, and adds a GPU card to the Metrics page.
- The upstream Cockpit Sensors package backed by `lm-sensors` for host temperature, fan, voltage, and power-style values exposed through the kernel hwmon stack.

The exporter runs as root because Intel GPU utilization and temperature metrics require MEI device access on this host.

## Install

From the repository root on the target host:

```bash
sudo ./scripts/install.sh
```

Then refresh the Cockpit browser tab.

The installer needs root, installs `lm-sensors` through `apt-get` (it exits on hosts without `apt-get` unless `sensors` is already present), downloads the Cockpit Sensors package from its GitHub releases unless `/usr/share/cockpit/sensors` already exists, and edits Cockpit's Overview and Metrics `index.html` files, saving `.cockpit-intel-gpu.bak` backups beside them.

This host currently uses `xpu-smi` from the Intel graphics package feed. Intel's full `xpumanager` package conflicts with `xpu-smi`, so do not install both on the same system. Keep `xpu-smi` for the Cockpit page unless you explicitly want to switch to the full XPU Manager daemon for REST/Prometheus workflows.

## Files Installed

- `/usr/local/libexec/cockpit-intel-gpu-exporter`
- `/etc/systemd/system/cockpit-intel-gpu-exporter.service`
- `/usr/local/share/cockpit/intel-gpu/`
- `/usr/share/cockpit/sensors/`
- `/usr/share/cockpit/systemd/overview-intel-gpu.js`
- `/usr/share/cockpit/systemd/overview-intel-gpu.css`
- `/usr/share/cockpit/metrics/metrics-intel-gpu.js`
- `/usr/share/cockpit/metrics/metrics-intel-gpu.css`
- Small script/style references in `/usr/share/cockpit/systemd/index.html` and `/usr/share/cockpit/metrics/index.html`

## Uninstall

```bash
sudo ./scripts/uninstall.sh
```

## License

MIT. See [LICENSE](LICENSE).
