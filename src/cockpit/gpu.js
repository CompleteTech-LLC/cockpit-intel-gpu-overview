(function () {
  "use strict";

  const SYSTEM_METRICS = "/run/cockpit-intel-gpu/metrics.json";
  const USER_METRICS = ".cache/cockpit-intel-gpu/metrics.json";
  let file = null;

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

  function watchMetrics(paths, index) {
    if (file) {
      file.close();
    }
    file = cockpit.file(paths[index], { syntax: JSON });
    let initial = true;
    file.watch((content, tag, error) => {
      if ((error || content === null) && initial && index + 1 < paths.length) {
        watchMetrics(paths, index + 1);
        return;
      }
      initial = false;
      if (error) {
        set("gpu-status", error.message || String(error));
        return;
      }
      render(content);
    });
  }

  cockpit.user()
          .then(user => watchMetrics([SYSTEM_METRICS, `${user.home}/${USER_METRICS}`], 0))
          .catch(() => watchMetrics([SYSTEM_METRICS], 0));

  window.addEventListener("unload", () => {
    if (file) {
      file.close();
    }
  });
}());
