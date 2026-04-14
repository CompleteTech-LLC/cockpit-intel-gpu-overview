(function () {
  "use strict";

  const file = cockpit.file("/run/cockpit-intel-gpu/metrics.json", { syntax: JSON });
  let lastData = null;

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

  function usageCard() {
    const candidates = Array.from(document.querySelectorAll("h1,h2,h3,h4,div,span"));
    const heading = candidates.find(node => node.textContent.trim() === "Usage");
    if (!heading) {
      return null;
    }

    let node = heading;
    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
      if (node.querySelector && node.querySelector("a[href*='metrics']")) {
        return node;
      }
    }
    return heading.parentElement;
  }

  function ensureRow() {
    const card = usageCard();
    if (!card) {
      return null;
    }

    let row = card.querySelector(".ct-intel-gpu-overview-row");
    if (!row) {
      row = document.createElement("div");
      row.className = "ct-intel-gpu-overview-row";
      row.innerHTML = [
        "<span class='ct-intel-gpu-overview-label'>GPU</span>",
        "<span class='ct-intel-gpu-overview-meter'><span></span></span>",
        "<span class='ct-intel-gpu-overview-value'>--</span>",
      ].join("");

      const link = card.querySelector("a[href*='metrics']");
      if (link && link.parentElement) {
        link.parentElement.insertBefore(row, link);
      } else {
        card.appendChild(row);
      }
    }
    return row;
  }

  function render() {
    const row = ensureRow();
    if (!row || !lastData) {
      return;
    }

    const util = lastData.ok === false ? null : lastData.utilization_percent;
    const memory = lastData.memory_util_percent;
    row.querySelector(".ct-intel-gpu-overview-meter span").style.width =
      Math.max(0, Math.min(100, Number(util || 0))) + "%";
    row.querySelector(".ct-intel-gpu-overview-value").textContent =
      memory === null || memory === undefined ? `${percent(util)} GPU` : `${percent(util)} GPU, ${percent(memory)} mem`;
  }

  file.watch((content) => {
    lastData = content;
    render();
  });

  const observer = new MutationObserver(render);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("unload", () => {
    observer.disconnect();
    file.close();
  });
}());

