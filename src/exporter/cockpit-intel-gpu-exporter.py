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
DEFAULT_HISTORY_MINUTES = 2880
DEFAULT_INTERVAL = 2.0
DEVICE_ID = "0"
METRICS = "MEMORY,UTILIZATION,TEMPERATURE,POWER,CLOCK"
METRICS_FALLBACK = (
    METRICS,
    "all",
)
DRM_DEVICE = "/sys/class/drm/card0/device"


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


def read_float(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return float(handle.read().strip())
    except (OSError, ValueError):
        return None


def sample_sysfs_gpu():
    device = os.path.realpath(DRM_DEVICE)
    now = time.monotonic()
    samples = []
    for gt in ("gt0", "gt1"):
        idle = read_float(os.path.join(device, "tile0", gt, "gtidle", "idle_residency_ms"))
        if idle is not None:
            samples.append(idle)
    return {"time": now, "idle_ms": samples}


def sysfs_gpu_util_percent(before, after):
    if not before or not after:
        return None
    elapsed_ms = (after["time"] - before["time"]) * 1000
    if elapsed_ms <= 0:
        return None

    busy = []
    for old_idle, new_idle in zip(before["idle_ms"], after["idle_ms"]):
        idle_delta = max(0, new_idle - old_idle)
        busy.append(100 - min(100, (idle_delta / elapsed_ms) * 100))
    if not busy:
        return None
    return max(0, min(100, max(busy)))


def sysfs_temperature_c():
    device = os.path.realpath(DRM_DEVICE)
    for name in ("temp2_input", "temp3_input"):
        value = read_float(os.path.join(device, "hwmon", "hwmon5", name))
        if value is not None:
            return value / 1000
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


def history_path(output):
    return os.path.join(os.path.dirname(output), "history.json")


def load_history(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    samples = data.get("samples") if isinstance(data, dict) else None
    return samples if isinstance(samples, list) else []


def update_history(path, payload, limit):
    if not payload.get("ok"):
        return

    minute = int(time.time() // 60) * 60
    sample = {
        "time_ms": minute * 1000,
        "timestamp": dt.datetime.fromtimestamp(minute, dt.timezone.utc).isoformat(timespec="seconds"),
        "utilization_percent": payload.get("utilization_percent"),
        "memory_util_percent": payload.get("memory_util_percent"),
        "memory_used_mib": payload.get("memory_used_mib"),
        "memory_total_mib": payload.get("memory_total_mib"),
    }

    samples = [item for item in load_history(path) if isinstance(item, dict) and item.get("time_ms") != sample["time_ms"]]
    samples.append(sample)
    cutoff = sample["time_ms"] - (limit - 1) * 60 * 1000
    samples = [item for item in samples if item.get("time_ms", 0) >= cutoff]
    samples.sort(key=lambda item: item.get("time_ms", 0))
    write_json(path, {"samples": samples})


def run_command(args, timeout=15):
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def extract_json_payload(text):
    if not text:
        return ""
    start = text.find("{")
    if start == -1:
        return ""
    end = text.rfind("}")
    if end == -1 or end < start:
        return ""
    return text[start : end + 1]


def _collect_discovery_indices_from_text(text):
    ids = []
    seen = set()
    for value in re.findall(r"(?i)\b(?:Device(?:\s+ID|\s+Id)|Device(?:\s+Index))\s*:\s*(\d+)", text):
        index = int(value)
        if index not in seen:
            ids.append(index)
            seen.add(index)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "Timestamp" in stripped or "Device" in stripped:
            continue
        match = re.match(r"^(\d+)\s*[| \t]", stripped)
        if match:
            index = int(match.group(1))
            if index not in seen:
                ids.append(index)
                seen.add(index)

    return ids


def _collect_discovery_indices_from_json(payload):
    if not isinstance(payload, (dict, list)):
        return []

    candidate_keys = (
        "device_id",
        "deviceid",
        "card_id",
        "cardid",
        "id",
        "index",
        "deviceindex",
    )
    ids = []
    seen = set()

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and any(k == key.lower().replace("_", "").replace("-", "") for k in candidate_keys):
                    try:
                        index = int(str(value).strip())
                    except (TypeError, ValueError):
                        continue
                    if index >= 0 and index not in seen:
                        ids.append(index)
                        seen.add(index)
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
    return ids


def discover_indices():
    try:
        result = run_command(["xpu-smi", "discovery"])
    except Exception:
        return [0]

    text = result.stdout
    ids = _collect_discovery_indices_from_text(text)
    if not ids and text:
        try:
            payload = json.loads(extract_json_payload(text))
        except Exception:
            payload = None
        if payload is not None:
            ids = _collect_discovery_indices_from_json(payload)
    return ids if ids else [0]


def discover():
    discovery_output = ""
    try:
        result = run_command(["xpu-smi", "discovery", "-d", DEVICE_ID, "-j"])
        discovery_output = result.stdout
        discovery_json = extract_json_payload(discovery_output)
        data = json.loads(discovery_json) if discovery_json else None
    except Exception as exc:
        data = None
        error = str(exc)
    else:
        error = None

    device_indices = _collect_discovery_indices_from_text(discovery_output)
    if not device_indices and data:
        device_indices = _collect_discovery_indices_from_json(data)

    if data:
        memory_total = None
        memory_total_bytes = parse_number(str(data.get("memory_physical_size_byte", "")))
        if memory_total_bytes is not None:
            memory_total = memory_total_bytes / 1024 / 1024

        return {
            "device_name": data.get("device_name", "Intel GPU"),
            "pci_bdf": data.get("pci_bdf_address"),
            "drm_device": data.get("drm_device"),
            "device_indices": device_indices or [0],
            "memory_total_mib": memory_total,
        }

    try:
        result = run_command(["xpu-smi", "discovery"])
    except Exception:
        return {
            "device_name": "Intel GPU",
            "pci_bdf": None,
            "drm_device": None,
            "device_indices": [0],
            "memory_total_mib": None,
            "error": error,
        }

    text = result.stdout

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
            "device_indices": device_indices or [0],
            "memory_total_mib": memory_total,
        }


def sample_dump():
    indices = discover_indices()
    errors = []

    for index in indices:
        for metrics in METRICS_FALLBACK:
            try:
                result = run_command([
                    "xpu-smi",
                    "dump",
                    "--json",
                    "--device",
                    str(index),
                    "--metrics",
                    metrics,
                    "--number",
                    "1",
                ])
                return parse_dump(result.stdout)
            except Exception as exc:
                message = str(exc)
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                    message = f"{message}; stderr: {exc.stderr.strip()}"
                errors.append(f"i={index},m={metrics}: {message}")

    raise RuntimeError("; ".join(errors) or "xpu-smi dump failed")


def parse_dump(output):
    data = None
    try:
        payload = extract_json_payload(output)
        if payload:
            data = json.loads(payload)
    except Exception:
        data = None

    if isinstance(data, dict):
        metrics = data.get("metrics")
        if isinstance(metrics, dict):
            timestamp = str(data.get("timestamp", "")).strip()
            device_id = str(data.get("device", data.get("DeviceId", ""))).strip()

            def pick(*names):
                for name in names:
                    if name in metrics:
                        return parse_number(metrics[name])
                return None

            return {
                "timestamp": timestamp,
                "device_id": device_id,
                "utilization_percent": pick("utilization.gpu"),
                "power_watts": pick("power.draw"),
                "frequency_mhz": pick("clocks.current.graphics", "clocks.max.graphics"),
                "temperature_c": pick("temperature.gpu"),
                "memory_util_percent": pick("utilization.memory"),
                "memory_used_mib": pick("memory.used"),
                "compute_percent": pick("utilization.compute"),
                "render_percent": pick("utilization.render"),
                "decoder_percent": pick("utilization.media"),
                "encoder_percent": pick("utilization.media"),
                "copy_percent": pick("utilization.copy"),
            }

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
    sysfs_before = sample_sysfs_gpu()
    sysfs_after = sample_sysfs_gpu()
    metrics = sample_dump()
    if metrics.get("utilization_percent") is None:
        metrics["utilization_percent"] = sysfs_gpu_util_percent(sysfs_before, sysfs_after)
    if metrics.get("temperature_c") is None:
        metrics["temperature_c"] = sysfs_temperature_c()
    metrics.update(discovery)
    metrics["ok"] = True
    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--history-output")
    parser.add_argument("--history-minutes", type=int, default=DEFAULT_HISTORY_MINUTES)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    history_output = args.history_output or history_path(args.output)

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
        update_history(history_output, payload, args.history_minutes)
        if args.once:
            return 0 if payload.get("ok") else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
