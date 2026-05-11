(function () {
  "use strict";

  const SYSTEM_METRICS = "/run/cockpit-intel-gpu/metrics.json";
  const USER_METRICS = ".cache/cockpit-intel-gpu/metrics.json";
  let file = null;
  let lastData = null;
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

  function removeLegacyUsageRows() {
    document.querySelectorAll(".ct-intel-gpu-overview-row").forEach(row => row.remove());
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

  function overviewGallery() {
    return document.querySelector(".ct-system-overview") || document.querySelector(".pf-v5-l-gallery");
  }

  function ensureOverviewCard() {
    const gallery = overviewGallery();
    if (!gallery) {
      return null;
    }

    let card = gallery.querySelector(".ct-intel-gpu-card");
    if (!card) {
      card = document.createElement("article");
      card.className = "pf-v5-c-card ct-intel-gpu-card";
      card.innerHTML = [
        "<div class='pf-v5-c-card__title'><div class='pf-v5-c-card__title-text'>Intel Arc Pro B60</div></div>",
        "<div class='pf-v5-c-card__body'>",
        "  <div class='ct-intel-gpu-card-stack'>",
        "    <div class='ct-intel-gpu-card-metric ct-intel-gpu-card-gpu'>",
        "      <div><span>GPU</span><strong>--%</strong></div>",
        "      <span class='ct-intel-gpu-card-meter'><span></span></span>",
        "    </div>",
        "    <div class='ct-intel-gpu-card-metric ct-intel-gpu-card-memory'>",
        "      <div><span>GPU memory</span><strong>--</strong></div>",
        "      <span class='ct-intel-gpu-card-meter'><span></span></span>",
        "    </div>",
        "    <dl class='ct-intel-gpu-card-details'>",
        "      <div><dt>Power</dt><dd data-ct-intel-gpu-detail='power'>--</dd></div>",
        "      <div><dt>Temperature</dt><dd data-ct-intel-gpu-detail='temperature'>--</dd></div>",
        "    </dl>",
        "  </div>",
        "</div>",
      ].join("");
      gallery.appendChild(card);
    }
    return card;
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
    removeLegacyUsageRows();
    const card = ensureOverviewCard();
    if (!lastData) {
      return;
    }

    const util = lastData.ok === false ? null : lastData.utilization_percent;
    const memory = lastData.ok === false ? null : memoryPercent(lastData);

    if (card) {
      setText(card.querySelector(".ct-intel-gpu-card-gpu strong"), percent(util));
      setMeter(card.querySelector(".ct-intel-gpu-card-gpu .ct-intel-gpu-card-meter span"), util);
      setText(card.querySelector(".ct-intel-gpu-card-memory strong"), memoryLabel(lastData));
      setMeter(card.querySelector(".ct-intel-gpu-card-memory .ct-intel-gpu-card-meter span"), memory);
      setText(card.querySelector("[data-ct-intel-gpu-detail='power']"),
              number(lastData.power_watts, 1) === null ? "--" : number(lastData.power_watts, 1) + " W");
      setText(card.querySelector("[data-ct-intel-gpu-detail='temperature']"),
              number(lastData.temperature_c, 0) === null ? "--" : number(lastData.temperature_c, 0) + " C");
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
      if (!error) {
        lastData = content;
        scheduleRender();
      }
    });
  }

  cockpit.user()
          .then(user => watchMetrics([SYSTEM_METRICS, `${user.home}/${USER_METRICS}`], 0))
          .catch(() => watchMetrics([SYSTEM_METRICS], 0));

  const observer = new MutationObserver(scheduleRender);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("unload", () => {
    observer.disconnect();
    if (file) {
      file.close();
    }
  });
}());
