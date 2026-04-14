(function () {
  "use strict";

  const file = cockpit.file("/run/cockpit-intel-gpu/metrics.json", { syntax: JSON });

  function value(metric, suffix, digits) {
    if (metric === null || metric === undefined) {
      return "--" + (suffix || "");
    }
    const places = digits === undefined ? 0 : digits;
    return Number(metric).toFixed(places) + (suffix || "");
  }

  function percent(metric) {
    return value(metric, "%", metric && metric < 10 ? 1 : 0);
  }

  function width(metric) {
    if (metric === null || metric === undefined || Number.isNaN(Number(metric))) {
      return "0%";
    }
    return Math.max(0, Math.min(100, Number(metric))) + "%";
  }

  function set(id, text) {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = text;
    }
  }

  function render(data) {
    if (!data || data.ok === false) {
      set("gpu-status", data && data.error ? data.error : "Waiting for telemetry");
      return;
    }

    set("gpu-title", data.device_name || "Intel GPU");
    set("gpu-status", "Live");
    set("gpu-util", percent(data.utilization_percent));
    set("gpu-memory", data.memory_total_mib ? `${value(data.memory_used_mib / 1024, " GiB", 1)} / ${value(data.memory_total_mib / 1024, " GiB", 1)}` : value(data.memory_used_mib, " MiB"));
    set("gpu-power", value(data.power_watts, " W", 1));
    set("gpu-temp", value(data.temperature_c, " C", 0));
    set("gpu-frequency", value(data.frequency_mhz, " MHz", 0));
    set("gpu-render", percent(data.render_percent));
    set("gpu-compute", percent(data.compute_percent));
    set("gpu-copy", percent(data.copy_percent));
    set("gpu-decoder", percent(data.decoder_percent));
    set("gpu-encoder", percent(data.encoder_percent));
    set("gpu-pci", data.pci_bdf || "--");
    set("gpu-drm", data.drm_device || "--");
    set("gpu-updated", data.updated_at || data.timestamp || "--");

    const util = document.getElementById("gpu-util-meter");
    if (util) {
      util.style.width = width(data.utilization_percent);
    }

    const memory = document.getElementById("gpu-memory-meter");
    if (memory) {
      memory.style.width = width(data.memory_util_percent);
    }
  }

  file.watch((content, tag, error) => {
    if (error) {
      set("gpu-status", error.message || String(error));
      return;
    }
    render(content);
  });

  window.addEventListener("unload", () => file.close());
}());

