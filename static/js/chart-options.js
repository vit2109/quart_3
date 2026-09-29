/** Настройки графиков отчётов: цвета, сетка, метки данных. */

import { escapeHtml, formatCell } from "./quart-core.js";
import { palette } from "./render-utils.js";

const STORAGE_KEY = "quart_report_chart_opts";

function loadAll() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveAll(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

export function loadChartOpts(reportId, chartIndex) {
  const all = loadAll();
  return all?.[String(reportId)]?.[String(chartIndex)] || {};
}

export function saveChartOpts(reportId, chartIndex, opts) {
  const all = loadAll();
  const rid = String(reportId);
  const idx = String(chartIndex);
  all[rid] = all[rid] || {};
  all[rid][idx] = { ...(all[rid][idx] || {}), ...opts };
  saveAll(all);
}

export function randomPieColors(n) {
  return Array.from({ length: n }, () => {
    const h = Math.floor(Math.random() * 360);
    return `hsla(${h}, 62%, 48%, 0.88)`;
  });
}

function colorWithAlpha(color, alpha) {
  if (!color) return palette(0, alpha);
  if (color.startsWith("#")) {
    const h = color.replace("#", "");
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  if (color.startsWith("rgb(")) {
    return color.replace("rgb(", "rgba(").replace(")", `, ${alpha})`);
  }
  if (color.startsWith("rgba(")) {
    return color.replace(/[\d.]+\)$/, `${alpha})`);
  }
  return color;
}

function dataLabelsPlugin(show, getLabel) {
  return {
    id: "quartDataLabels",
    afterDatasetsDraw(chart) {
      if (!show) return;
      const ctx = chart.ctx;
      chart.data.datasets.forEach((dataset, dsIndex) => {
        const meta = chart.getDatasetMeta(dsIndex);
        if (meta.hidden) return;
        meta.data.forEach((element, index) => {
          const raw = dataset.data[index];
          const label = getLabel(index, raw, chart.data.labels?.[index]);
          if (label == null || label === "") return;
          const pos = element.tooltipPosition?.() || { x: element.x, y: element.y };
          ctx.save();
          ctx.font = "11px Sora, sans-serif";
          ctx.fillStyle = "#334155";
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillText(String(label), pos.x, pos.y - 4);
          ctx.restore();
        });
      });
    },
  };
}

export function buildReportChartConfig(spec, opts = {}) {
  const type = spec.type || "bar";
  const labels = spec.labels || [];
  const datasets = spec.datasets || [];
  const isCircular = type === "pie" || type === "doughnut";
  const showGrid = opts.showGrid !== false;
  const showDataLabels = !!opts.showDataLabels;
  const labelOverrides = opts.labelOverrides || {};

  const seriesColor = opts.seriesColor || "#0f766e";
  const pieColors =
    opts.pieColors?.length === labels.length
      ? opts.pieColors
      : randomPieColors(Math.max(labels.length, 1));

  const mappedDatasets = datasets.map((ds, idx) => {
    const baseColor = opts.seriesColor || palette(idx, 1);
    if (isCircular) {
      return {
        ...ds,
        backgroundColor: pieColors,
        borderColor: "#fff",
        borderWidth: 1,
      };
    }
    if (type === "line") {
      return {
        ...ds,
        borderColor: baseColor,
        backgroundColor: colorWithAlpha(baseColor, 0.12),
        borderWidth: 2,
        tension: 0.25,
      };
    }
    return {
      ...ds,
      backgroundColor: colorWithAlpha(baseColor, 0.65),
      borderColor: baseColor,
      borderWidth: 1,
      tension: 0.25,
    };
  });

  const scales =
    isCircular || type === "radar"
      ? {}
      : {
          x: {
            ticks: { maxRotation: 45, minRotation: 0 },
            grid: { display: showGrid },
          },
          y: {
            beginAtZero: true,
            grid: { display: showGrid },
          },
        };

  const getLabel = (index, value, label) => {
    const key = String(label ?? index);
    if (labelOverrides[key] != null && labelOverrides[key] !== "") return labelOverrides[key];
    if (labelOverrides[String(index)] != null && labelOverrides[String(index)] !== "") {
      return labelOverrides[String(index)];
    }
    return formatCell(value);
  };

  return {
    type,
    data: { labels, datasets: mappedDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      indexAxis: spec.index_axis || "x",
      plugins: {
        legend: {
          display: datasets.length > 1 || isCircular,
        },
      },
      scales,
    },
    plugins: [dataLabelsPlugin(showDataLabels, getLabel)],
  };
}

export function renderChartSettingsPanel(reportId, chartIndex, spec) {
  const opts = loadChartOpts(reportId, chartIndex);
  const labels = spec.labels || [];
  const isCircular = spec.type === "pie" || spec.type === "doughnut";
  const labelRows = labels
    .map(
      (lbl, i) => `
      <label class="chart-label-override">
        <span>${escapeHtml(lbl)}</span>
        <input type="text" data-label-key="${escapeHtml(lbl)}" data-label-index="${i}" value="${escapeHtml(opts.labelOverrides?.[lbl] ?? opts.labelOverrides?.[String(i)] ?? "")}" placeholder="${escapeHtml(formatCell(spec.datasets?.[0]?.data?.[i]))}" />
      </label>`
    )
    .join("");

  return `
    <details class="chart-settings" data-chart-settings="${chartIndex}">
      <summary>Настройки графика</summary>
      <div class="chart-settings-body">
        <label class="chart-opt-row">
          <input type="checkbox" data-opt="showGrid" ${opts.showGrid !== false ? "checked" : ""} />
          Линии сетки
        </label>
        <label class="chart-opt-row">
          <input type="checkbox" data-opt="showDataLabels" ${opts.showDataLabels ? "checked" : ""} />
          Метки данных
        </label>
        ${
          isCircular
            ? `<button type="button" class="btn-sm" data-action="random-pie-colors">Случайные цвета секторов</button>`
            : `<label class="chart-opt-row">Цвет серии <input type="color" data-opt="seriesColor" value="${escapeHtml(opts.seriesColor || "#0f766e")}" /></label>`
        }
        ${
          labelRows
            ? `<div class="chart-label-overrides"><p class="meta">Подписи меток (пусто = значение)</p>${labelRows}</div>`
            : ""
        }
      </div>
    </details>`;
}

export function bindChartSettings(root, reportId, charts, rerenderChart) {
  root.querySelectorAll("[data-chart-settings]").forEach((details) => {
    const chartIndex = Number(details.dataset.chartSettings);
    const card = details.closest(".chart-card");
    if (!card || card.dataset.settingsBound === "1") return;
    card.dataset.settingsBound = "1";

    const persistAndRender = () => {
      const opts = readOptsFromPanel(details);
      saveChartOpts(reportId, chartIndex, opts);
      rerenderChart(chartIndex);
    };

    details.querySelectorAll('[data-opt="showGrid"], [data-opt="showDataLabels"]').forEach((el) => {
      el.addEventListener("change", persistAndRender);
    });
    details.querySelector('[data-opt="seriesColor"]')?.addEventListener("input", persistAndRender);
    details.querySelector('[data-action="random-pie-colors"]')?.addEventListener("click", () => {
      const spec = charts[chartIndex];
      const n = spec?.labels?.length || 1;
      saveChartOpts(reportId, chartIndex, { pieColors: randomPieColors(n) });
      rerenderChart(chartIndex);
    });
    details.querySelectorAll(".chart-label-override input").forEach((input) => {
      input.addEventListener("change", persistAndRender);
      input.addEventListener("blur", persistAndRender);
    });
  });
}

function readOptsFromPanel(details) {
  const labelOverrides = {};
  details.querySelectorAll(".chart-label-override input").forEach((input) => {
    const key = input.dataset.labelKey || input.dataset.labelIndex;
    if (input.value.trim()) labelOverrides[key] = input.value.trim();
  });
  return {
    showGrid: details.querySelector('[data-opt="showGrid"]')?.checked !== false,
    showDataLabels: !!details.querySelector('[data-opt="showDataLabels"]')?.checked,
    seriesColor: details.querySelector('[data-opt="seriesColor"]')?.value || "#0f766e",
    labelOverrides,
  };
}
