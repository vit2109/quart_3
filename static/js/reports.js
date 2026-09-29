/** Панель «Отчёты» (E22). */

import { API, $, $$, api, ensureActiveDataset, escapeHtml, formatCell, state, toast } from "./quart-core.js";
import {
  applyFiltersToList,
  buildDefaultPeriodFilter,
  collectFiltersFromList,
  refreshFilterColumnSelects,
  saveFilters,
} from "./filters.js";
import {
  classifyReportSection,
  destroyQuartCharts,
  initPaginatedTables,
  loadChartJs,
  renderCollapsibleSection,
  renderTableBlock,
  setResultMessage,
} from "./render-utils.js";
import {
  bindChartSettings,
  buildReportChartConfig,
  loadChartOpts,
  renderChartSettingsPanel,
} from "./chart-options.js";
import { showPanel } from "./datasets-ui.js";

export function renderReportFieldPickers(columns) {
  const groupPicker = $("#reportGroupPicker");
  const metricPicker = $("#reportMetricPicker");
  const metricSelect = $("#reportChartMetric");
  if (!groupPicker || !metricPicker) return;

  if (!columns.length) {
    groupPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    metricPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    if (metricSelect) metricSelect.innerHTML = `<option value="">— авто —</option>`;
    return;
  }

  const categorical = columns.filter((c) => c.kind !== "number");
  const numeric = columns.filter((c) => c.kind === "number");
  const groupSource = categorical.length ? categorical : columns;

  groupPicker.innerHTML = groupSource
    .map(
      (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="group_by" value="${escapeHtml(col.name)}" ${i === 0 ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
    )
    .join("");

  if (!numeric.length) {
    metricPicker.innerHTML = `<p class="column-picker-empty">Числовых колонок нет — агрегация по count</p>`;
  } else {
    metricPicker.innerHTML = numeric
      .map(
        (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="metric" value="${escapeHtml(col.name)}" ${i < 3 ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
      )
      .join("");
  }

  if (metricSelect) {
    metricSelect.innerHTML =
      `<option value="">— авто —</option>` +
      numeric
        .map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`)
        .join("");
    if (numeric[0]) metricSelect.value = numeric[0].name;
  }
  refreshFilterColumnSelects("#reportFilterList", columns);
}

export function renderReportTables(el, report) {
  destroyQuartCharts();

  state.currentReportId = report?.id ?? null;
  const toolbar = $("#reportToolbar");
  const toolbarTitle = $("#reportToolbarTitle");
  if (toolbar) {
    toolbar.hidden = !state.currentReportId;
    if (toolbarTitle && state.currentReportId) {
      toolbarTitle.textContent = report?.name || `Отчёт #${state.currentReportId}`;
    }
  }

  if (report?.analysis_text && !(report?.tables || []).length) {
    el.innerHTML =
      `<p class="result-meta"><strong>${escapeHtml(report.name || `Отчёт #${report.id}`)}</strong> · AI</p>` +
      renderCollapsibleSection("AI-анализ", `<article class="ai-narrative">${escapeHtml(report.analysis_text)}</article>`, true, "conclusions");
    return;
  }

  const tables = report?.tables || [];
  const charts = report?.charts || [];
  if (!tables.length && !charts.length && !report?.analysis_text) {
    setResultMessage(el, "В отчёте нет таблиц и графиков");
    return;
  }

  const groupBy = (report.group_by || []).join(", ") || "—";
  const metrics = (report.metrics || []).join(", ") || "—";
  const meta = `<p class="result-meta"><strong>${escapeHtml(report.name || `Отчёт #${report.id}`)}</strong> · набор #${escapeHtml(formatCell(report.dataset_id))} · ${escapeHtml(report.report_type || "")}<br/>Группировка: <strong>${escapeHtml(groupBy)}</strong> · Метрики: <strong>${escapeHtml(metrics)}</strong></p>`;

  const groupByCols = report.group_by || [];

  const tableHtml = tables
    .map((t) => {
      const title = t.title || "Таблица";
      const cls = classifyReportSection(title);
      if (
        title.toLowerCase().includes("ai") &&
        (t.rows || []).some((r) => String(r["Содержание"] || "").length > 200)
      ) {
        const text =
          (t.rows || []).find((r) => r["Раздел"] === "Текст анализа")?.["Содержание"] ||
          (t.rows || []).map((r) => `${r["Раздел"]}: ${r["Содержание"]}`).join("\n\n");
        return renderCollapsibleSection(title, `<article class="ai-narrative">${escapeHtml(text)}</article>`, cls.defaultOpen, cls.section);
      }
      const tableColumns = t.columns || [];
      const drillable = groupByCols.filter((col) => tableColumns.includes(col));
      return renderTableBlock(title, tableColumns, t.rows || [], {
        collapsible: true,
        defaultOpen: cls.defaultOpen,
        section: cls.section,
        drillableColumns: drillable,
      });
    })
    .join("");

  const chartsInner = charts.length
    ? `<div class="charts-grid">${charts
        .map(
          (c, i) => `
      <div class="chart-card" data-chart-index="${i}">
        <h3>${escapeHtml(c.title || c.type || "График")}</h3>
        ${state.currentReportId != null ? renderChartSettingsPanel(state.currentReportId, i, c) : ""}
        <canvas id="reportChart_${i}" height="220"></canvas>
        <p class="chart-meta">Поля: ${escapeHtml((c.source_columns || []).join(", ") || "—")}</p>
      </div>`
        )
        .join("")}</div>`
    : `<p class="result-placeholder">Графики не сгенерированы</p>`;

  const chartsHtml = charts.length
    ? renderCollapsibleSection("Графики", chartsInner, false, "charts")
    : "";

  const insights = report.insights || [];
  const insightsHtml = insights.length
    ? renderCollapsibleSection(
        "Ключевые выводы",
        `<ul class="insights-list">${insights.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`,
        true,
        "conclusions"
      )
    : "";

  const aiHtml = report.analysis_text
    ? renderCollapsibleSection(
        "AI-анализ",
        `<article class="ai-narrative">${escapeHtml(report.analysis_text)}</article>`,
        true,
        "conclusions"
      )
    : "";

  el.innerHTML = meta + tableHtml + chartsHtml + insightsHtml + aiHtml;
  initPaginatedTables(el);

  if (charts.length) {
    const reportId = state.currentReportId;
    const chartInstances = new Map();

    const renderOneChart = (i) => {
      const canvas = document.getElementById(`reportChart_${i}`);
      if (!canvas || typeof Chart === "undefined") return;
      const existing = Chart.getChart(canvas);
      if (existing) existing.destroy();
      const spec = charts[i];
      const opts = reportId != null ? loadChartOpts(reportId, i) : {};
      const cfg = buildReportChartConfig(spec, opts);
      const instance = new Chart(canvas, cfg);
      chartInstances.set(i, instance);
      const idx = (window.__quartCharts || []).findIndex((c) => c.canvas === canvas);
      if (idx >= 0) window.__quartCharts[idx] = instance;
      else window.__quartCharts.push(instance);
    };

    loadChartJs()
      .then(() => {
        charts.forEach((_, i) => renderOneChart(i));
        if (reportId != null) {
          bindChartSettings(el, reportId, charts, renderOneChart);
        }
      })
      .catch((err) => toast(err.message, true));
  }
}

export async function exportCurrentReport() {
  const id = state.currentReportId;
  if (!id) {
    toast("Сначала откройте или сгенерируйте отчёт", true);
    return;
  }
  const format = $("#exportFormat")?.value || "json";
  const url = `${API}/reports/${id}/export?format=${encodeURIComponent(format)}`;
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  try {
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || `report_${id}.${format}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Экспорт: ${filename}`);
  } catch (err) {
    toast(err.message || "Ошибка экспорта", true);
  }
}

export async function loadReports() {
  const list = $("#reportList");
  const count = $("#reportCount");
  list.innerHTML = `<li class="empty">Загрузка…</li>`;
  try {
    const data = await api("/reports/", { timeoutMs: 15000 });
    const items = data?.data || [];
    if (count) count.textContent = String(items.length);
    if (!items.length) {
      list.innerHTML = `<li class="empty">Отчётов пока нет — выполните анализ или сгенерируйте отчёт</li>`;
      return;
    }
    list.innerHTML = items
      .map(
        (r) => `
        <li class="${state.currentReportId === r.id ? "is-selected" : ""}">
          <div>
            <strong>${escapeHtml(r.name || `Report #${r.id}`)}</strong>
            <div class="meta">ID ${r.id} · набор #${r.dataset_id} · ${escapeHtml(r.report_type || "")} · ${formatDate(r.created_at)} · таблиц: ${r.tables_count ?? "—"}</div>
          </div>
          <div class="list-item-actions">
            <button type="button" class="btn-sm" data-report="${r.id}">Открыть</button>
            <button type="button" class="btn-sm btn-danger" data-delete-report="${r.id}" aria-label="Удалить">×</button>
          </div>
        </li>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
  }
}

export function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return String(iso);
  }
}

export function bindReportColumnsLoaded() {
  document.addEventListener("quart:columns-loaded", (e) => {
    renderReportFieldPickers(e.detail.columns || []);
  });
}

export function setupReports(deps = {}) {
  const {
    listHasRows = () => false,
    setupFilterList = () => {},
  } = deps;
  return setupReportsPanel({ listHasRows, setupFilterList });
}

function setupReportsPanel({ listHasRows, setupFilterList }) {

  const reportTemplates = [
    {
      id: "weekly_sc",
      name: "Еженедельная сводка",
      report_type: "summary",
      group_by: ["region"],
      top_n: 10,
      period_days: 30,
    },
    {
      id: "full_review",
      name: "Полный обзор",
      report_type: "full",
      top_n: 15,
    },
    {
      id: "executive",
      name: "Для руководства",
      report_type: "executive",
      top_n: 8,
    },
  ];
  const tplSel = $("#reportTemplate");
  if (tplSel && reportTemplates.length) {
    tplSel.innerHTML =
      `<option value="">— без шаблона —</option>` +
      reportTemplates
        .map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`)
        .join("");
  }
  $("#applyReportTemplate")?.addEventListener("click", () => {
    const id = $("#reportTemplate")?.value;
    const tpl = reportTemplates.find((t) => t.id === id);
    if (!tpl) {
      toast("Выберите шаблон", true);
      return;
    }
    if (tpl.report_type) {
      const rt = $('#reportForm select[name="report_type"]');
      if (rt) rt.value = tpl.report_type;
    }
    if (tpl.top_n) {
      const tn = $('#reportForm input[name="top_n"]');
      if (tn) tn.value = tpl.top_n;
    }
    if (tpl.group_by?.length) {
      $$('#reportGroupPicker input[name="group_by"]').forEach((el) => {
        el.checked = tpl.group_by.includes(el.value);
      });
    }
    if (tpl.period_days) {
      const pf = buildDefaultPeriodFilter(tpl.period_days, tpl.date_col);
      if (pf) applyFiltersToList("#reportFilterList", [pf], "Нажмите «Добавить фильтр»", listHasRows);
    }
    toast(`Шаблон «${tpl.name}» применён`);
  });

  function buildReportPayloadFromForm() {
    const fd = new FormData($("#reportForm"));
    return {
      dataset_id: ensureActiveDataset(),
      report_type: String(fd.get("report_type") || "summary"),
      group_by: $$('#reportGroupPicker input[name="group_by"]:checked').map((el) => el.value),
      metrics: $$('#reportMetricPicker input[name="metric"]:checked').map((el) => el.value),
      top_n: Number(fd.get("top_n") || 10),
      chart_types: $$('#reportChartTypes input[name="chart_type"]:checked').map((el) => el.value),
      chart_metric: String(fd.get("chart_metric") || "") || null,
      filters: collectFiltersFromList("#reportFilterList"),
    };
  }

  $("#scheduleReportBtn")?.addEventListener("click", async () => {
    try {
      const payload = buildReportPayloadFromForm();
      const name = prompt("Название расписания:", `Отчёт #${payload.dataset_id} daily`);
      if (!name?.trim()) return;
      const cron = prompt("Cron (min hour day month dow, UTC):", "0 8 * * *");
      if (!cron?.trim()) return;
      const webhook = prompt("Webhook URL (опционально, Enter — пропустить):", "")?.trim();
      await api("/jobs/schedules", {
        method: "POST",
        json: {
          name: name.trim(),
          job_type: "report_generate",
          cron: cron.trim(),
          payload,
          webhook_url: webhook || null,
        },
      });
      toast("Расписание создано");
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#reportForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const groupBy = $$('#reportGroupPicker input[name="group_by"]:checked').map((el) => el.value);
    const metrics = $$('#reportMetricPicker input[name="metric"]:checked').map((el) => el.value);
    const chartTypes = $$('#reportChartTypes input[name="chart_type"]:checked').map((el) => el.value);
    const body = {
      dataset_id: ensureActiveDataset(),
      report_type: String(fd.get("report_type") || "summary"),
      group_by: groupBy,
      metrics,
      top_n: Number(fd.get("top_n") || 10),
      chart_types: chartTypes,
      chart_metric: String(fd.get("chart_metric") || "") || null,
      filters: collectFiltersFromList("#reportFilterList"),
    };
    const out = $("#reportOutput");
    setResultMessage(out, "Генерация отчёта с группировкой и графиками…");
    try {
      const data = await api(`/reports/generate`, { method: "POST", json: body });
      saveFilters("report");
      const report = data?.data || data;
      renderReportTables(out, report);
      toast("Отчёт создан");
      const history = $("#reportHistorySection");
      if (history) history.open = true;
      await loadReports();
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

  $("#refreshReports")?.addEventListener("click", () => loadReports());

  $("#clearReportHistory")?.addEventListener("click", async () => {
    if (!confirm("Удалить всю историю отчётов? Это действие нельзя отменить.")) return;
    try {
      const data = await api("/reports/", { method: "DELETE" });
      const deleted = data?.data?.deleted ?? 0;
      state.currentReportId = null;
      const toolbar = $("#reportToolbar");
      if (toolbar) toolbar.hidden = true;
      setResultMessage($("#reportOutput"), "История очищена. Сгенерируйте новый отчёт.");
      toast(`Удалено отчётов: ${deleted}`);
      await loadReports();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#clearReportGroupBy")?.addEventListener("click", () => {
    $$('#reportGroupPicker input[name="group_by"]').forEach((el) => {
      el.checked = false;
    });
  });
  $("#selectAllReportMetrics")?.addEventListener("click", () => {
    const boxes = $$('#reportMetricPicker input[name="metric"]');
    const all = boxes.length && boxes.every((b) => b.checked);
    boxes.forEach((b) => {
      b.checked = !all;
    });
  });

  $("#exportReport")?.addEventListener("click", () => exportCurrentReport());

  setupFilterList(
    "#reportFilterList",
    "#addReportFilter",
    "Нажмите «Добавить фильтр» для условия по колонке",
    "report"
  );

  $("#reportList").addEventListener("click", async (e) => {
    const deleteBtn = e.target.closest("[data-delete-report]");
    if (deleteBtn) {
      e.stopPropagation();
      const id = Number(deleteBtn.dataset.deleteReport);
      if (!confirm(`Удалить отчёт #${id} из истории?`)) return;
      try {
        await api(`/reports/${id}`, { method: "DELETE" });
        if (state.currentReportId === id) {
          state.currentReportId = null;
          const toolbar = $("#reportToolbar");
          if (toolbar) toolbar.hidden = true;
          setResultMessage($("#reportOutput"), "Отчёт удалён. Сгенерируйте или откройте другой.");
        }
        toast(`Отчёт #${id} удалён`);
        await loadReports();
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }

    const btn = e.target.closest("[data-report]");
    if (!btn) return;
    const out = $("#reportOutput");
    setResultMessage(out, "Загрузка отчёта…");
    try {
      const data = await api(`/reports/${btn.dataset.report}`);
      renderReportTables(out, data?.data || data);
      await loadReports();
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

}
