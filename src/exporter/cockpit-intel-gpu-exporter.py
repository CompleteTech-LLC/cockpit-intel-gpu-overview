#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time


DEFAULT_OUTPUT = "/run/cockpit-intel-gpu/metrics.json"
DEFAULT_INTERVAL = 2.0
DEVICE_ID = "0"
METRICS = "0,1,2,3,5,18,22,23,24,25,26"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def parse_number(value):
    value = value.strip()
    if not value or value.upper() == "N/A":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload["updated_at"] = now_iso()
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".metrics.", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_command(args, timeout=15):
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def discover():
    try:
        result = run_command(["xpu-smi", "discovery", "-d", DEVICE_ID])
    except Exception as exc:
        return {"error": str(exc)}

    text = result.stdout
    if "DRM Device" not in text:
        try:
            text += "\n" + run_command(["xpu-smi", "discovery"]).stdout
        except Exception:
            pass

    fields = {}
    for key in ["Device Name", "PCI BDF Address", "DRM Device", "Memory Physical Size"]:
        match = re.search(rf"{re.escape(key)}:\s*([^|]+)", text)
        if match:
            fields[key] = match.group(1).strip()

    memory_total = None
    if "Memory Physical Size" in fields:
        memory_total = parse_number(fields["Memory Physical Size"].replace("MiB", ""))

    return {
        "device_name": fields.get("Device Name", "Intel GPU"),
        "pci_bdf": fields.get("PCI BDF Address"),
        "drm_device": fields.get("DRM Device"),
        "memory_total_mib": memory_total,
    }


def parse_dump(output):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("xpu-smi dump returned no metric rows")

    header_index = None
    for index, line in enumerate(lines):
        if line.startswith("Timestamp,"):
            header_index = index
            break
    if header_index is None or header_index == len(lines) - 1:
        raise ValueError("xpu-smi dump output did not include a CSV header and row")

    reader = csv.DictReader(lines[header_index:])
    row = {key.strip(): value.strip() for key, value in next(reader).items()}

    def first(*names):
        for name in names:
            if name in row:
                return parse_number(row[name])
        return None

    return {
        "timestamp": row.get("Timestamp", "").strip(),
        "device_id": row.get("DeviceId", "").strip(),
        "utilization_percent": first("Average % utilization of all GPU Engines"),
        "power_watts": first("GPU Power (W)"),
        "frequency_mhz": first("GPU Frequency (MHz)"),
        "temperature_c": first("GPU Core Temperature (Celsius Degree)"),
        "memory_util_percent": first("GPU Memory Utilization (%)"),
        "memory_used_mib": first("GPU Memory Used (MiB)"),
        "compute_percent": first("Compute Engine 0 (%)", "Compute Engine (%)"),
        "render_percent": first("Render Engine 0 (%)", "Render Engine (%)"),
        "decoder_percent": first("Decoder Engine 0 (%)", "Decoder Engine (%)"),
        "encoder_percent": first("Encoder Engine 0 (%)", "Encoder Engine (%)"),
        "copy_percent": first("Copy Engine 0 (%)", "Copy Engine (%)"),
    }


def collect(discovery):
    result = run_command([
        "xpu-smi",
        "dump",
        "-d",
        DEVICE_ID,
        "-m",
        METRICS,
        "-i",
        "1",
        "-n",
        "1",
    ])
    metrics = parse_dump(result.stdout)
    metrics.update(discovery)
    metrics["ok"] = True
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    device = discover()

    while True:
        try:
            payload = collect(device)
        except Exception as exc:
            payload = {
                "ok": False,
                "error": str(exc),
                "device_name": device.get("device_name", "Intel GPU"),
            }
            print(f"collection failed: {exc}", file=sys.stderr, flush=True)

        write_json(args.output, payload)
        if args.once:
            return 0 if payload.get("ok") else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
