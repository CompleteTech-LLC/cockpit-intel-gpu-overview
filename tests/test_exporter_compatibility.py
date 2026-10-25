"""Offline command compatibility regressions; no collectors or devices are used.

Fixtures are synthetic, not hardware captures. Discovery follows Intel's
33afa129d539aaf2643a10b3883ef210b0842dce ial/cmn/cmd_discovery.cpp.
The legacy command contract follows a22960fe0c3479cb4237233c0863e5c4b6464b95
cli/src/comlet_dump.cpp and the exporter on main cc15287e227edeab53153e77d20ff84aad433391.
Run with: python3 -B -m unittest discover -s tests -v
"""

import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "src/exporter/cockpit-intel-gpu-exporter.py"
SPEC = importlib.util.spec_from_file_location("intel_gpu_exporter_compatibility", SOURCE)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)

GROUPS = "MEMORY,UTILIZATION,TEMPERATURE,POWER,CLOCK"
LEGACY_METRICS = "0,1,2,3,5,18,22,23,24,25,26"
V2_TABLE = """Device ID   Device Information
0           Device Name: fixture GPU zero
            PCI BDF Address: 0000:03:00.0
            DRM Device: /dev/dri/card0
1           Device Name: fixture GPU one
            PCI BDF Address: 0000:04:00.0
            DRM Device: /dev/dri/card1
"""
BORDERED_TABLE = """+-----------+--------------------------------------------+
| Device ID | Device Information                         |
| 0         | Device Name: fixture GPU zero              |
|           | PCI BDF Address: 0000:03:00.0               |
| 1         | Device Name: fixture GPU one               |
|           | PCI BDF Address: 0000:04:00.0               |
+-----------+--------------------------------------------+
"""
JSON_METRICS = {
    "utilization.gpu": "42.00", "power.draw": "20.00",
    "clocks.current.graphics": "1000.00", "temperature.gpu": "35.00",
    "utilization.memory": "25.00", "memory.used": "4096.00",
    "utilization.compute": "40.00", "utilization.render": "2.00",
    "utilization.media": "3.00", "utilization.copy": "1.00",
}
CSV_HEADER = (
    "Timestamp,DeviceId,Average % utilization of all GPU Engines,GPU Power (W),"
    "GPU Frequency (MHz),GPU Core Temperature (Celsius Degree),"
    "GPU Memory Utilization (%),GPU Memory Used (MiB),Compute Engine 0 (%),"
    "Render Engine 0 (%),Decoder Engine 0 (%),Encoder Engine 0 (%),Copy Engine 0 (%)\n"
)


def json_command(index, metrics=GROUPS):
    return ["xpu-smi", "dump", "--json", "--device", str(index),
            "--metrics", metrics, "--number", "1"]


def legacy_command(index):
    return ["xpu-smi", "dump", "-d", str(index), "-m", LEGACY_METRICS,
            "-i", "1", "-n", "1"]


def missing_csv_dump(index, power="N/A"):
    values = ["N/A"] * 11
    values[1] = power
    return CSV_HEADER.replace(",", ", ") + f"19:00:00.000, {index}, " + ", ".join(values) + "\n"


def json_dump(index=0, metrics=None):
    return json.dumps({"timestamp": "19:00:00.000", "device": index,
                       "metrics": JSON_METRICS if metrics is None else metrics})


def csv_dump(index=0, zero=False):
    values = [0] * 11 if zero else [42, 20, 1000, 35, 25, 4096, 40, 2, 3, 4, 1]
    return CSV_HEADER + f"19:00:00.000,{index}," + ",".join(map(str, values)) + "\n"


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.events = []
        self.clock = 0.0
        self.table = V2_TABLE
        self.response = lambda args: json_dump()
        guards = (
            patch.object(exporter.subprocess, "run", side_effect=self.command),
            patch.object(exporter.os.path, "realpath", side_effect=self.realpath),
            patch.object(exporter, "open", side_effect=self.open, create=True),
            patch.object(exporter.time, "monotonic", side_effect=lambda: self.clock),
        )
        for guard in guards:
            guard.start()
            self.addCleanup(guard.stop)

    def realpath(self, path):
        self.assertEqual(path, exporter.DRM_DEVICE)
        return "/offline/fixture"

    def open(self, path, mode="r", encoding=None):
        if path == "/offline/fixture/hwmon/hwmon5/temp2_input":
            self.assertEqual((mode, encoding), ("r", "utf-8"))
            self.events.append(("temperature", self.clock))
            return io.StringIO("42000")
        self.assertIn(path, [f"/offline/fixture/tile0/{gt}/gtidle/idle_residency_ms"
                             for gt in ("gt0", "gt1")])
        self.assertEqual((mode, encoding), ("r", "utf-8"))
        self.events.append(("idle", self.clock))
        return io.StringIO(str(int(self.clock * 1000)))

    def command(self, args, **kwargs):
        self.commands.append(args)
        self.assertEqual(kwargs, {"check": True, "text": True, "stdout": subprocess.PIPE,
                                  "stderr": subprocess.PIPE, "timeout": 15})
        if args == ["xpu-smi", "discovery"]:
            return SimpleNamespace(stdout=self.table)
        self.assertEqual(args[:2], ["xpu-smi", "dump"])
        self.events.append(("dump", self.clock))
        self.clock += 1.0
        return SimpleNamespace(stdout=self.response(args))

    def reject(self, args):
        raise subprocess.CalledProcessError(1, args, stderr="fixture command rejected")

    def assert_metrics(self, result, index=0):
        self.assertEqual(result["device_id"], str(index))
        self.assertEqual(result["utilization_percent"], 42.0)
        self.assertEqual(result["memory_used_mib"], 4096.0)
        self.assertEqual(result["temperature_c"], 35.0)

    def test_discovery_reads_plain_device_name_rows(self):
        self.assertEqual(exporter.discover_indices(), [0, 1])
        self.assertEqual(self.commands, [["xpu-smi", "discovery"]])

    def test_discovery_reads_bordered_device_name_rows(self):
        self.table = BORDERED_TABLE
        self.assertEqual(exporter.discover_indices(), [0, 1])

    def test_discovery_preserves_noncontiguous_multi_digit_indices(self):
        self.table = V2_TABLE.replace("0           Device Name", "2           Device Name")
        self.table = self.table.replace("1           Device Name", "17          Device Name")
        self.assertEqual(exporter.discover_indices(), [2, 17])

    def test_discovery_deduplicates_explicit_labels_and_rows(self):
        text = "Device ID: 0\nDevice Index: 1\n" + V2_TABLE + BORDERED_TABLE
        self.assertEqual(exporter._collect_discovery_indices_from_text(text), [0, 1])

    def test_discovery_ignores_headers_and_continuation_rows(self):
        text = "Device ID Device Information\n| Device ID | Device Information |\n"
        text += "| | PCI BDF Address: 0000:03:00.0 |\n DRM Device: /dev/dri/card9\n"
        self.assertEqual(exporter._collect_discovery_indices_from_text(text), [])

    def test_discovery_keeps_zero_fallback_when_no_indices_found(self):
        self.table = "No devices\n"
        self.assertEqual(exporter.discover_indices(), [0])

    def test_discovery_keeps_json_object_fallback(self):
        self.table = json.dumps({"device_list": [{"device_id": 2}, {"device_id": 17}]})
        self.assertEqual(exporter.discover_indices(), [2, 17])

    def test_v2_group_success_does_not_try_fallbacks(self):
        self.assert_metrics(exporter.sample_dump())
        self.assertEqual(self.commands[1:], [json_command(0)])

    def test_v2_all_metrics_success_does_not_try_legacy(self):
        self.response = lambda args: json_dump() if args == json_command(0, "all") else self.reject(args)
        self.assert_metrics(exporter.sample_dump())
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all")])

    def test_invalid_group_output_tries_all_metrics(self):
        self.response = lambda args: json_dump() if args == json_command(0, "all") else "not metrics"
        self.assert_metrics(exporter.sample_dump())
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all")])

    def test_legacy_uses_numeric_metrics_short_count_and_csv(self):
        # The pinned legacy CLI rejects --number, named metrics and daemonless JSON.
        self.response = lambda args: csv_dump() if args == legacy_command(0) else self.reject(args)
        self.assert_metrics(exporter.sample_dump())
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"), legacy_command(0)])

    def test_invalid_json_outputs_fall_back_to_legacy_csv(self):
        self.response = lambda args: csv_dump() if args == legacy_command(0) else "not metrics"
        self.assert_metrics(exporter.sample_dump())
        self.assertEqual(self.commands[-1], legacy_command(0))

    def test_unavailable_zero_does_not_hide_working_v2_device_one(self):
        self.response = lambda args: json_dump(1) if args == json_command(1) else self.reject(args)
        self.assert_metrics(exporter.sample_dump(), index=1)
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"),
                                            legacy_command(0), json_command(1)])

    def test_unavailable_zero_does_not_hide_working_legacy_device_one(self):
        self.table = BORDERED_TABLE
        self.response = lambda args: csv_dump(1) if args == legacy_command(1) else self.reject(args)
        self.assert_metrics(exporter.sample_dump(), index=1)
        self.assertEqual(self.commands[1:], [command for index in (0, 1) for command in
                                            (json_command(index), json_command(index, "all"), legacy_command(index))])

    def test_json_wrong_device_response_is_rejected_before_acceptance(self):
        self.response = lambda args: json_dump(1)
        self.assert_metrics(exporter.sample_dump(), index=1)
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"),
                                            legacy_command(0), json_command(1)])

    def test_csv_wrong_device_response_is_rejected_before_acceptance(self):
        self.response = lambda args: csv_dump(1) if args == legacy_command(0) else self.reject(args)
        with self.assertRaisesRegex(RuntimeError, "returned device '1', expected 0"):
            exporter.sample_dump()

    def test_missing_device_identity_cannot_be_accepted(self):
        self.response = lambda args: json.dumps({"metrics": JSON_METRICS})
        with self.assertRaisesRegex(RuntimeError, "returned device '', expected"):
            exporter.sample_dump()

    def test_unrelated_json_identity_types_cannot_be_accepted(self):
        for identity in (None, False, True, 0.0, 1.0, [], {}, "", "0.0"):
            with self.subTest(identity=identity):
                self.response = lambda args: json_dump(identity)
                with self.assertRaisesRegex(RuntimeError, "returned device"):
                    exporter.sample_dump()

    def test_missing_csv_device_identity_cannot_be_accepted(self):
        self.response = lambda args: csv_dump("") if args == legacy_command(0) else self.reject(args)
        with self.assertRaisesRegex(RuntimeError, "returned device '', expected 0"):
            exporter.sample_dump()

    def test_nondefault_device_keeps_own_metrics_without_default_metadata(self):
        own_metrics = dict(JSON_METRICS, **{"temperature.gpu": "55.00", "memory.used": "8192.00"})
        self.response = lambda args: json_dump(1, own_metrics) if args == json_command(1) else self.reject(args)
        metadata = {"device_name": "fixture GPU zero", "pci_bdf": "0000:03:00.0",
                    "drm_device": "/dev/dri/card0", "device_indices": [0],
                    "memory_total_mib": 16384.0, "temperature_c": 90.0}
        result = exporter.collect(metadata)
        self.assertEqual(result["device_id"], "1")
        self.assertEqual(result["temperature_c"], 55.0)
        self.assertEqual(result["memory_used_mib"], 8192.0)
        self.assertTrue(result["ok"])
        for key in ("device_name", "pci_bdf", "drm_device", "memory_total_mib"):
            self.assertIn(key, result)
            self.assertIsNone(result[key])
        self.assertEqual(result["device_indices"], [1])
        self.assertEqual([event for event in self.events if event[0] == "idle"],
                         [("idle", 0.0), ("idle", 0.0)])

    def test_nondefault_device_missing_metrics_do_not_use_card0_fallbacks(self):
        own_metrics = dict(JSON_METRICS, **{"temperature.gpu": "N/A", "utilization.gpu": "N/A"})
        self.response = lambda args: json_dump(1, own_metrics) if args == json_command(1) else self.reject(args)
        result = exporter.collect({"device_name": "fixture GPU zero", "memory_total_mib": 16384.0})
        self.assertEqual(result["device_id"], "1")
        self.assertIsNone(result["temperature_c"])
        self.assertIsNone(result["utilization_percent"])
        self.assertIsNone(result["memory_total_mib"])

    def test_default_device_still_receives_discovery_metadata(self):
        metadata = {"device_name": "fixture GPU zero", "memory_total_mib": 16384.0}
        result = exporter.collect(metadata)
        self.assert_metrics(result)
        self.assertEqual(result["device_name"], metadata["device_name"])
        self.assertEqual(result["memory_total_mib"], metadata["memory_total_mib"])

    def test_nondefault_missing_json_retries_all_before_accepting(self):
        def response(args):
            if args == json_command(1):
                return json_dump(1, {key: "N/A" for key in JSON_METRICS})
            if args == json_command(1, "all"):
                return json_dump(1)
            return self.reject(args)
        self.response = response
        self.assert_metrics(exporter.sample_dump(), index=1)
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"), legacy_command(0),
                                            json_command(1), json_command(1, "all")])

    def test_nondefault_missing_json_retries_legacy_before_next_device(self):
        def response(args):
            if args in (json_command(1), json_command(1, "all")):
                return json_dump(1, {key: "N/A" for key in JSON_METRICS})
            if args == legacy_command(1):
                return csv_dump(1)
            return self.reject(args)
        self.response = response
        self.assert_metrics(exporter.sample_dump(), index=1)
        self.assertEqual(self.commands[1:], [command for index in (0, 1) for command in
                                            (json_command(index), json_command(index, "all"), legacy_command(index))])

    def test_nondefault_missing_json_does_not_hide_working_device_two(self):
        self.table += "2           Device Name: fixture GPU two\n"
        def response(args):
            if args in (json_command(1), json_command(1, "all")):
                return json_dump(1, {key: "N/A" for key in JSON_METRICS})
            if args == json_command(2):
                return json_dump(2)
            return self.reject(args)
        self.response = response
        self.assert_metrics(exporter.sample_dump(), index=2)
        expected = [command for index in (0, 1) for command in
                    (json_command(index), json_command(index, "all"), legacy_command(index))]
        self.assertEqual(self.commands[1:], expected + [json_command(2)])

    def test_nondefault_missing_csv_does_not_hide_working_device_two(self):
        self.table += "2           Device Name: fixture GPU two\n"
        def response(args):
            if args == legacy_command(1):
                return missing_csv_dump(1)
            if args == legacy_command(2):
                return csv_dump(2)
            return self.reject(args)
        self.response = response
        self.assert_metrics(exporter.sample_dump(), index=2)
        self.assertEqual(self.commands[1:], [command for index in (0, 1, 2) for command in
                                            (json_command(index), json_command(index, "all"), legacy_command(index))])

    def test_empty_or_unknown_json_metrics_retry_instead_of_accepting(self):
        self.table = "1 Device Name: fixture GPU one\n2 Device Name: fixture GPU two\n"
        for values in ({}, {"future.metric": "42.00"}):
            with self.subTest(metrics=values):
                self.commands.clear()
                self.response = lambda args: json_dump(2) if args == json_command(2) else json_dump(1, values)
                self.assert_metrics(exporter.sample_dump(), index=2)
                self.assertEqual(self.commands[1:], [json_command(1), json_command(1, "all"),
                                                    legacy_command(1), json_command(2)])

    def test_nondefault_partial_json_metrics_including_zero_remain_valid(self):
        for value in ("0.00", "42.00"):
            with self.subTest(power=value):
                self.commands.clear()
                self.response = lambda args: json_dump(1, {"power.draw": value}) if args == json_command(1) else self.reject(args)
                result = exporter.collect({"device_name": "fixture GPU zero"})
                self.assertEqual(result["power_watts"], float(value))
                self.assertIsNone(result["utilization_percent"])
                self.assertIsNone(result["temperature_c"])
                self.assertTrue(result["ok"])
                self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"),
                                                    legacy_command(0), json_command(1)])

    def test_nondefault_partial_csv_metrics_including_zero_remain_valid(self):
        for value in ("0.00", "42.00"):
            with self.subTest(power=value):
                self.commands.clear()
                self.response = lambda args: missing_csv_dump(1, power=value) if args == legacy_command(1) else self.reject(args)
                result = exporter.collect({"device_name": "fixture GPU zero"})
                self.assertEqual(result["power_watts"], float(value))
                self.assertIsNone(result["utilization_percent"])
                self.assertIsNone(result["temperature_c"])
                self.assertTrue(result["ok"])
                self.assertEqual(self.commands[1:], [command for index in (0, 1) for command in
                                                    (json_command(index), json_command(index, "all"), legacy_command(index))])

    def test_default_all_missing_json_still_uses_sysfs(self):
        self.response = lambda args: json_dump(0, {key: "N/A" for key in JSON_METRICS})
        result = exporter.collect({"device_name": "fixture GPU zero"})
        self.assertEqual(result["device_id"], "0")
        self.assertEqual(result["utilization_percent"], 0.0)
        self.assertEqual(result["temperature_c"], 42.0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.commands[1:], [json_command(0)])

    def test_default_all_missing_csv_still_uses_sysfs(self):
        self.response = lambda args: missing_csv_dump(0) if args == legacy_command(0) else self.reject(args)
        result = exporter.collect({"device_name": "fixture GPU zero"})
        self.assertEqual(result["device_id"], "0")
        self.assertEqual(result["utilization_percent"], 0.0)
        self.assertEqual(result["temperature_c"], 42.0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.commands[1:], [json_command(0), json_command(0, "all"), legacy_command(0)])

    def test_exhausted_missing_nondefault_metrics_report_failure(self):
        self.table = "1 Device Name: fixture GPU one\n"
        self.response = lambda args: json_dump(1, {key: "N/A" for key in JSON_METRICS})
        with self.assertRaisesRegex(RuntimeError, "no usable metrics for device 1"):
            exporter.sample_dump()
        self.assertEqual(self.commands[1:], [json_command(1), json_command(1, "all"), legacy_command(1)])

    def test_exhausted_commands_preserve_diagnostics(self):
        self.response = self.reject
        with self.assertRaisesRegex(RuntimeError, "fixture command rejected") as caught:
            exporter.sample_dump()
        self.assertEqual(len(self.commands), 7)
        self.assertIn("i=0", str(caught.exception))
        self.assertIn("i=1", str(caught.exception))
        self.assertIn(LEGACY_METRICS, str(caught.exception))

    def test_json_zero_metrics_survive_real_collect(self):
        self.response = lambda args: json_dump(metrics={key: "0.00" for key in JSON_METRICS})
        result = exporter.collect({})
        self.assertTrue(result["ok"])
        for key, value in result.items():
            if key.endswith(("_percent", "_watts", "_mhz", "_c", "_mib")):
                self.assertEqual(value, 0.0, key)

    def test_legacy_csv_zero_metrics_survive_real_collect(self):
        self.response = lambda args: csv_dump(zero=True) if args == legacy_command(0) else self.reject(args)
        result = exporter.collect({})
        self.assertTrue(result["ok"])
        for key, value in result.items():
            if key.endswith(("_percent", "_watts", "_mhz", "_c", "_mib")):
                self.assertEqual(value, 0.0, key)

    def test_real_sampling_still_brackets_command_with_idle_counters(self):
        self.response = lambda args: json_dump(metrics=dict(JSON_METRICS, **{"utilization.gpu": "N/A"}))
        result = exporter.collect({})
        self.assertEqual(result["utilization_percent"], 0.0)
        self.assertEqual(self.events, [("idle", 0.0), ("idle", 0.0), ("dump", 0.0),
                                       ("idle", 1.0), ("idle", 1.0)])


if __name__ == "__main__":
    unittest.main()
