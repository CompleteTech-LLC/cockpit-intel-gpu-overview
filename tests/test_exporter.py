"""Offline exporter regressions; never run xpu-smi or read host devices.

Run with: python3 -m unittest discover -s tests -v
"""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "src/exporter/cockpit-intel-gpu-exporter.py"
SPEC = importlib.util.spec_from_file_location("intel_gpu_exporter", SOURCE)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class CollectTests(unittest.TestCase):
    def setUp(self):
        # Fail closed if a test accidentally reaches a real command or device.
        guards = (
            patch.object(exporter.subprocess, "run", side_effect=AssertionError("unexpected subprocess")),
            patch.object(exporter.os.path, "realpath", side_effect=AssertionError("unexpected device path")),
            patch.object(exporter, "open", side_effect=AssertionError("unexpected file read"), create=True),
        )
        for guard in guards:
            guard.start()
            self.addCleanup(guard.stop)

    def test_idle_counter_samples_bracket_the_dump(self):
        clock = 0.0
        calls = []

        def sample():
            nonlocal clock
            calls.append("sysfs")
            snapshot = {"time": clock, "idle_ms": [int(clock * 1000)]}
            clock += 0.0001
            return snapshot

        def dump():
            nonlocal clock
            calls.append("dump")
            clock += 1.0
            return {"device_id": "0", "utilization_percent": None, "temperature_c": 30.0}

        with patch.object(exporter, "sample_sysfs_gpu", side_effect=sample), patch.object(
            exporter, "sample_dump", side_effect=dump
        ):
            metrics = exporter.collect({"device_name": "fixture GPU"})

        # A millisecond-resolution idle counter cannot advance between immediate
        # reads. Sampling around the dump provides the intended measurement span.
        self.assertAlmostEqual(metrics["utilization_percent"], 0.0099990001)
        self.assertEqual(calls, ["sysfs", "dump", "sysfs"])
        self.assertEqual(metrics["device_name"], "fixture GPU")
        self.assertTrue(metrics["ok"])

    def test_reported_zero_values_are_not_replaced(self):
        with patch.object(exporter, "sample_sysfs_gpu", return_value={}), patch.object(
            exporter, "sample_dump", return_value={"device_id": "0", "utilization_percent": 0.0, "temperature_c": 0.0}
        ), patch.object(exporter, "sysfs_gpu_util_percent") as util, patch.object(
            exporter, "sysfs_temperature_c"
        ) as temperature:
            metrics = exporter.collect({})

        self.assertEqual(metrics["utilization_percent"], 0.0)
        self.assertEqual(metrics["temperature_c"], 0.0)
        util.assert_not_called()
        temperature.assert_not_called()

    def test_missing_metrics_use_sysfs_fallbacks(self):
        samples = [{"time": 1.0, "idle_ms": [100]}, {"time": 2.0, "idle_ms": [850]}]
        with patch.object(exporter, "sample_sysfs_gpu", side_effect=samples), patch.object(
            exporter, "sample_dump", return_value={"device_id": "0", "utilization_percent": None, "temperature_c": None}
        ), patch.object(exporter, "sysfs_temperature_c", return_value=46.75) as temperature:
            metrics = exporter.collect({})

        self.assertEqual(metrics["utilization_percent"], 25.0)
        self.assertEqual(metrics["temperature_c"], 46.75)
        temperature.assert_called_once_with()

    def test_unavailable_sysfs_leaves_metrics_missing(self):
        samples = [{"time": 1.0, "idle_ms": []}, {"time": 2.0, "idle_ms": []}]
        with patch.object(exporter, "sample_sysfs_gpu", side_effect=samples), patch.object(
            exporter, "sample_dump", return_value={"device_id": "0", "utilization_percent": None, "temperature_c": None}
        ), patch.object(exporter, "sysfs_temperature_c", return_value=None):
            metrics = exporter.collect({})

        self.assertIsNone(metrics["utilization_percent"])
        self.assertIsNone(metrics["temperature_c"])
        self.assertTrue(metrics["ok"])

    def test_failed_dump_propagates_without_fallback_metrics(self):
        with patch.object(exporter, "sample_sysfs_gpu", return_value={}), patch.object(
            exporter, "sample_dump", side_effect=RuntimeError("fixture dump failure")
        ), patch.object(exporter, "sysfs_gpu_util_percent") as util, patch.object(
            exporter, "sysfs_temperature_c"
        ) as temperature:
            with self.assertRaisesRegex(RuntimeError, "fixture dump failure"):
                exporter.collect({})

        util.assert_not_called()
        temperature.assert_not_called()


if __name__ == "__main__":
    unittest.main()
