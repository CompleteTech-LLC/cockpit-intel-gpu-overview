(function () {
  "use strict";

  const SYSTEM_METRICS = "/run/cockpit-intel-gpu/metrics.json";
  const SYSTEM_HISTORY = "/run/cockpit-intel-gpu/history.json";
  const USER_METRICS = ".cache/cockpit-intel-gpu/metrics.json";
  const USER_HISTORY = ".cache/cockpit-intel-gpu/history.json";
  let file = null;
  let historyFile = null;
  let lastData = null;
  let lastHistory = [];
  let renderQueued = false;

  function number(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return null;
    }
    return Number(value).toFixed(digits);
  }

  function percent(value) {
    const digits = value && value < 10 ? 1 : 0;
    const formatted = number(value, digits);
    return formatted === null ? "--%" : formatted + "%";
  }

  function width(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return "0%";
    }
    return Math.max(0, Math.min(100, Number(value))) + "%";
  }

  function memoryPercent(data) {
    if (!data) {
      return null;
    }
    if (data.memory_util_percent !== null && data.memory_util_percent !== undefined) {
      return data.memory_util_percent;
    }
    if (data.memory_used_mib !== null && data.memory_used_mib !== undefined && data.memory_total_mib) {
      return (Number(data.memory_used_mib) / Number(data.memory_total_mib)) * 100;
    }
    return null;
  }

  function gib(value) {
    const formatted = number(Number(value) / 1024, 1);
    return formatted === null ? "--" : formatted + " GiB";
  }

  function memoryLabel(data) {
    if (!data || data.ok === false) {
      return "--";
    }
    if (data.memory_used_mib !== null && data.memory_used_mib !== undefined && data.memory_total_mib) {
      return `${gib(data.memory_used_mib)} / ${gib(data.memory_total_mib)}`;
    }
    return percent(memoryPercent(data));
  }

  function metricRatio(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return null;
    }
    return Math.max(0, Math.min(1, Number(value) / 100));
  }

  function setText(node, text) {
    if (node && node.textContent !== text) {
      node.textContent = text;
    }
  }

  function setMeter(node, value) {
    const next = width(value);
    if (node && node.style.width !== next) {
      node.style.width = next;
    }
  }

  function ensureMetricsCard() {
    const gallery = document.querySelector(".current-metrics");
    if (!gallery) {
      return null;
    }

    let card = gallery.querySelector(".ct-intel-gpu-metrics-card");
    if (!card) {
      card = document.createElement("article");
      card.className = "pf-v5-c-card ct-intel-gpu-metrics-card";
      card.innerHTML = [
        "<div class='pf-v5-c-card__title'><div class='pf-v5-c-card__title-text'>Intel Arc Pro B60</div></div>",
        "<div class='pf-v5-c-card__body'>",
        "  <div class='ct-intel-gpu-metrics-stack'>",
        "    <div class='ct-intel-gpu-metrics-row ct-intel-gpu-metrics-gpu'>",
        "      <div><span>GPU</span><strong>--%</strong></div>",
        "      <span class='ct-intel-gpu-metrics-meter'><span></span></span>",
        "    </div>",
        "    <div class='ct-intel-gpu-metrics-row ct-intel-gpu-metrics-memory'>",
        "      <div><span>GPU memory</span><strong>--</strong></div>",
        "      <span class='ct-intel-gpu-metrics-meter'><span></span></span>",
        "    </div>",
        "    <dl class='ct-intel-gpu-metrics-details'>",
        "      <div><dt>Power</dt><dd data-ct-intel-gpu-detail='power'>--</dd></div>",
        "      <div><dt>Temperature</dt><dd data-ct-intel-gpu-detail='temperature'>--</dd></div>",
        "      <div><dt>Frequency</dt><dd data-ct-intel-gpu-detail='frequency'>--</dd></div>",
        "    </dl>",
        "  </div>",
        "</div>",
      ].join("");
      gallery.appendChild(card);
    }
    return card;
  }

  function createHistoryLabel(kind, title, subtitle) {
    const label = document.createElement("div");
    label.className = `metrics-label metrics-label-graph ct-intel-gpu-history-label ct-intel-gpu-history-label-${kind}`;
    label.innerHTML = [
      `<span>${title}</span>`,
      `<div class='pf-v5-c-content metrics-sublabels'><small>${subtitle}</small></div>`,
    ].join("");
    return label;
  }

  function createHistoryData(kind) {
    const data = document.createElement("div");
    data.className = `metrics-data empty-data ct-intel-gpu-history-data ct-intel-gpu-history-data-${kind}`;
    data.setAttribute("aria-hidden", "true");
    data.innerHTML = "<div class='ct-intel-gpu-history-bar compressed'></div>";
    return data;
  }

  function appendAtEnd(parent, node) {
    if (node && (node.parentElement !== parent || node.nextSibling)) {
      parent.appendChild(node);
    }
  }

  function ensureHistoryColumns() {
    const headingGraphs = document.querySelector(".metrics-heading-graphs");
    if (headingGraphs) {
      headingGraphs.classList.add("ct-intel-gpu-history-graphs");
      const gpuLabel = headingGraphs.querySelector(".ct-intel-gpu-history-label-gpu") ||
        createHistoryLabel("gpu", "GPU", "Usage");
      const memoryLabel = headingGraphs.querySelector(".ct-intel-gpu-history-label-memory") ||
        createHistoryLabel("memory", "GPU memory", "Usage");
      appendAtEnd(headingGraphs, gpuLabel);
      appendAtEnd(headingGraphs, memoryLabel);
    }

    document.querySelectorAll(".metrics-minute .metrics-graphs").forEach(graphs => {
      graphs.classList.add("ct-intel-gpu-history-graphs");
      const gpuData = graphs.querySelector(".ct-intel-gpu-history-data-gpu") || createHistoryData("gpu");
      const memoryData = graphs.querySelector(".ct-intel-gpu-history-data-memory") || createHistoryData("memory");
      appendAtEnd(graphs, gpuData);
      appendAtEnd(graphs, memoryData);
    });
  }

  function sampleMap() {
    const map = new Map();
    lastHistory.forEach(sample => {
      if (sample && sample.time_ms !== undefined) {
        map.set(Number(sample.time_ms), sample);
      }
    });
    return map;
  }

  function hourStartMs(hour) {
    const id = hour && hour.id ? hour.id.match(/^metrics-hour-(\d+)$/) : null;
    return id ? Number(id[1]) : null;
  }

  function updateHistoryData() {
    const samples = sampleMap();
    document.querySelectorAll(".metrics-hour").forEach(hour => {
      const start = hourStartMs(hour);
      if (start === null) {
        return;
      }

      hour.querySelectorAll(".metrics-minute").forEach(minute => {
        const minuteNumber = Number(minute.dataset.minute);
        if (Number.isNaN(minuteNumber)) {
          return;
        }

        const sample = samples.get(start + minuteNumber * 60 * 1000);
        const gpu = metricRatio(sample && sample.utilization_percent);
        const memory = metricRatio(sample && memoryPercent(sample));
        updateHistoryCell(minute.querySelector(".ct-intel-gpu-history-data-gpu"), gpu);
        updateHistoryCell(minute.querySelector(".ct-intel-gpu-history-data-memory"), memory);
      });
    });
  }

  function updateHistoryCell(cell, ratio) {
    if (!cell) {
      return;
    }
    const bar = cell.querySelector(".ct-intel-gpu-history-bar");
    if (ratio === null) {
      cell.classList.add("empty-data");
      cell.classList.remove("valid-data");
      if (bar) {
        bar.style.removeProperty("height");
      }
      return;
    }

    cell.classList.remove("empty-data");
    cell.classList.add("valid-data");
    if (bar) {
      const height = `${ratio * 100}%`;
      if (bar.style.height !== height) {
        bar.style.height = height;
      }
    }
  }

  function scheduleRender() {
    if (renderQueued) {
      return;
    }
    renderQueued = true;
    window.requestAnimationFrame(() => {
      renderQueued = false;
      render();
    });
  }

  function render() {
    const card = ensureMetricsCard();
    ensureHistoryColumns();
    updateHistoryData();
    if (!card || !lastData) {
      return;
    }

    const util = lastData.ok === false ? null : lastData.utilization_percent;
    const memory = lastData.ok === false ? null : memoryPercent(lastData);
    setText(card.querySelector(".ct-intel-gpu-metrics-gpu strong"), percent(util));
    setMeter(card.querySelector(".ct-intel-gpu-metrics-gpu .ct-intel-gpu-metrics-meter span"), util);
    setText(card.querySelector(".ct-intel-gpu-metrics-memory strong"), memoryLabel(lastData));
    setMeter(card.querySelector(".ct-intel-gpu-metrics-memory .ct-intel-gpu-metrics-meter span"), memory);
    setText(card.querySelector("[data-ct-intel-gpu-detail='power']"),
            number(lastData.power_watts, 1) === null ? "--" : number(lastData.power_watts, 1) + " W");
    setText(card.querySelector("[data-ct-intel-gpu-detail='temperature']"),
            number(lastData.temperature_c, 0) === null ? "--" : number(lastData.temperature_c, 0) + " C");
    setText(card.querySelector("[data-ct-intel-gpu-detail='frequency']"),
            number(lastData.frequency_mhz, 0) === null ? "--" : number(lastData.frequency_mhz, 0) + " MHz");
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
      if (!error) {
        lastData = content;
        scheduleRender();
      }
    });
  }

  function watchHistory(paths, index) {
    if (historyFile) {
      historyFile.close();
    }
    historyFile = cockpit.file(paths[index], { syntax: JSON });
    let initial = true;
    historyFile.watch((content, tag, error) => {
      if ((error || content === null) && initial && index + 1 < paths.length) {
        watchHistory(paths, index + 1);
        return;
      }
      initial = false;
      if (!error && content && Array.isArray(content.samples)) {
        lastHistory = content.samples;
        scheduleRender();
      }
    });
  }

  cockpit.user()
          .then(user => {
            watchMetrics([SYSTEM_METRICS, `${user.home}/${USER_METRICS}`], 0);
            watchHistory([SYSTEM_HISTORY, `${user.home}/${USER_HISTORY}`], 0);
          })
          .catch(() => {
            watchMetrics([SYSTEM_METRICS], 0);
            watchHistory([SYSTEM_HISTORY], 0);
          });

  const observer = new MutationObserver(scheduleRender);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("unload", () => {
    observer.disconnect();
    if (file) {
      file.close();
    }
    if (historyFile) {
      historyFile.close();
    }
  });
}());
