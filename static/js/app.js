/** SPA bootstrap: данные, анализ, отчёты, задачи. */

import {
  API,
  $,
  $$,
  api,
  checkHealth,
  ensureActiveDataset,
  escapeHtml,
  formatCell,
  state,
  toast,
} from "./quart-core.js";
import {
  createDataFilterRow,
  refreshFilterColumnSelects,
  collectFiltersFromList,
  collectAggregationsFromList,
  refreshAggColumnSelects,
  setupAggList,
  copyFiltersToAllContexts,
  updateActiveFilterBadge,
  restoreAllSavedFilters as restoreAllSavedFiltersModule,
  saveFilters,
  setupFilterList as setupFilterListModule,
  updateDataFilterRow,
  applyFiltersToList,
} from "./filters.js";
import { renderTableBlock, setResultMessage } from "./render-utils.js";
import { setupAuth, syncAuthUi } from "./auth.js";
import {
  loadDatasets,
  loadDatasetPassport,
  setSelectedDataset,
  setupDatasets,
  setupDropzone,
  setupEtl,
  showPanel,
} from "./datasets-ui.js";
import {
  bindAnalysisColumnsLoaded,
  collectAnalysisAggregations,
  pollAiJob,
  refreshAiHealth,
  renderAnalysisResult,
  runAnalysis,
  setupAnalysis,
  setupMethodOptions,
  syncExploreModeUi,
} from "./analysis.js";
import {
  bindReportColumnsLoaded,
  loadReports,
  renderReportTables,
  setupReports,
} from "./reports.js";

function setupNavigation() {
  $$("[data-panel]").forEach((el) => {
    el.addEventListener("click", () => showPanel(el.dataset.panel));
  });
  $("#globalDatasetSelect")?.addEventListener("change", (e) => {
    const id = Number(e.target.value);
    if (id) {
      setSelectedDataset(id);
      loadDatasets();
    }
  });
}

function setupFilterSync() {
  $("#copyFiltersAll")?.addEventListener("click", () => {
    const active = document.querySelector(".panel.is-active")?.id?.replace("panel-", "");
    const ctxMap = { analysis: "analysis", reports: "report", export: "export" };
    const from = ctxMap[active] || "analysis";
    const n = copyFiltersToAllContexts(from, listHasRows);
    restoreAllSavedFilters();
    toast(n ? `Фильтры скопированы в ${n} вкладок` : "Нет сохранённых фильтров");
  });
  updateActiveFilterBadge();
}

function listHasRows(listSel, rowSel) {
  return $$(`${listSel} ${rowSel}`).length > 0;
}

function restoreAllSavedFilters() {
  restoreAllSavedFiltersModule(listHasRows);
}

function setupFilterList(listSelector, addButtonSelector, emptyHint, context = null) {
  setupFilterListModule(listSelector, addButtonSelector, emptyHint, context, listHasRows);
}

function bindExportColumnsLoaded() {
  document.addEventListener("quart:columns-loaded", (e) => {
    const columns = e.detail.columns || [];
    renderExportPickers(columns);
    restoreAllSavedFilters();
  });
}

async function drillDownToExplore(column, value) {
  ensureActiveDataset();
  showPanel("analysis");
  const method = $("#analysisMethod");
  if (method) {
    method.value = "explore";
    method.dispatchEvent(new Event("change"));
  }
  const exploreMode = $("#exploreMode");
  if (exploreMode) {
    exploreMode.value = "raw";
    syncExploreModeUi();
  }
  const list = $("#analysisFilterList");
  if (list) {
    list.innerHTML = "";
    list.insertAdjacentHTML("beforeend", createDataFilterRow());
    const rowEl = list.lastElementChild;
    const colSel = rowEl.querySelector('[name="filter_column"]');
    if (colSel) colSel.value = column;
    updateDataFilterRow(rowEl);
    const valEl = rowEl.querySelector('[name="filter_value"]');
    if (valEl) valEl.value = value;
    saveFilters("analysis");
  }
  const form = $("#analysisForm");
  const out = $("#analysisOutput");
  setResultMessage(out, "Детализация…");
  const data = await runAnalysis(form);
  renderAnalysisResult(out, data);
  toast(`Детализация: ${column} = ${value}`);
}

function setupDrillDown() {
  document.addEventListener("click", (e) => {
    const cell = e.target.closest(".drill-cell");
    if (!cell) return;
    const column = cell.dataset.drillColumn;
    const value = cell.dataset.drillValue;
    if (!column || value == null) return;
    drillDownToExplore(column, value).catch((err) => toast(err.message, true));
  });
}

function renderExportPickers(columns) {
  const groupPicker = $("#exportGroupPicker");
  const colPicker = $("#exportColumnPicker");
  const sortSelect = $("#exportSortBy");
  if (!groupPicker || !colPicker) return;

  if (!columns.length) {
    groupPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    colPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    if (sortSelect) sortSelect.innerHTML = `<option value="">— без сортировки —</option>`;
    return;
  }

  groupPicker.innerHTML = columns
    .map(
      (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="export_group_by" value="${escapeHtml(col.name)}" />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)}</small>
        </span>
      </label>`
    )
    .join("");

  colPicker.innerHTML = columns
    .map(
      (col) => `
      <label class="column-chip">
        <input type="checkbox" name="export_column" value="${escapeHtml(col.name)}" checked />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)}</small>
        </span>
      </label>`
    )
    .join("");

  if (sortSelect) {
    sortSelect.innerHTML =
      `<option value="">— без сортировки —</option>` +
      columns.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
  }

  refreshFilterColumnSelects("#exportFilterList", columns);
  refreshAggColumnSelects("#exportAggList", columns);
  refreshFilterColumnSelects("#reportFilterList", columns);
}

function syncExportModeUi() {
  const mode = $("#exportMode")?.value || "raw";
  const groupBlock = $("#exportGroupBlock");
  const colBlock = $("#exportColumnsBlock");
  if (groupBlock) groupBlock.hidden = mode !== "grouped";
  if (colBlock) colBlock.hidden = mode === "grouped";
}

function collectExportFilters() {
  return collectFiltersFromList("#exportFilterList");
}

function buildExportPayload(offset = state.exportOffset) {
  const mode = $("#exportMode")?.value || "raw";
  const limit = Number($("#exportLimit")?.value || 100);
  state.exportLimit = limit;
  state.exportOffset = offset;

  const payload = {
    mode,
    filters: collectExportFilters(),
    group_by: $$('#exportGroupPicker input[name="export_group_by"]:checked').map((el) => el.value),
    aggregations: collectAggregationsFromList("#exportAggList"),
    columns: $$('#exportColumnPicker input[name="export_column"]:checked').map((el) => el.value),
    sort_by: $("#exportSortBy")?.value || null,
    sort_dir: $("#exportSortDir")?.value || "asc",
    limit,
    offset,
  };

  if (payload.sort_by === "") payload.sort_by = null;
  return payload;
}

function renderExportResult(data) {
  const out = $("#exportOutput");
  const meta = $("#exportMeta");
  const pagination = $("#exportPagination");
  if (!out) return;

  state.exportTotal = data.total_rows || 0;

  if (meta) {
    meta.hidden = false;
    meta.innerHTML =
      (data.result_warning
        ? `<span class="result-warning-inline">${escapeHtml(data.result_warning)}</span>`
        : "") +
      `<span>Источник: <strong>${formatCell(data.source_rows)}</strong> строк</span>` +
      `<span>После фильтров: <strong>${formatCell(data.filtered_rows)}</strong></span>` +
      `<span>Результат: <strong>${formatCell(data.total_rows)}</strong></span>` +
      `<span>Показано: <strong>${formatCell(data.returned_rows)}</strong></span>` +
      (data.mode === "grouped"
        ? `<span>Группировка: <strong>${escapeHtml((data.group_by || []).join(", ") || "—")}</strong></span>`
        : "");
  }

  if (pagination) {
    pagination.hidden = false;
    const page = Math.floor(state.exportOffset / state.exportLimit) + 1;
    const totalPages = Math.max(1, Math.ceil(state.exportTotal / state.exportLimit));
    const info = $("#exportPageInfo");
    if (info) info.textContent = `Стр. ${page} из ${totalPages}`;
    $("#exportPrev").disabled = state.exportOffset <= 0;
    $("#exportNext").disabled = state.exportOffset + state.exportLimit >= state.exportTotal;
  }

  if (!data.rows?.length) {
    out.innerHTML = `<p class="result-placeholder">Нет строк по заданным условиям</p>`;
    return;
  }

  out.innerHTML = renderTableBlock(
    data.mode === "grouped" ? "Сгруппированные данные" : "Данные",
    data.columns || [],
    data.rows || [],
    { paginate: false }
  );
}

async function runExportQuery(offset = 0) {
  const datasetId = ensureActiveDataset();
  const payload = buildExportPayload(offset);
  if (payload.mode === "grouped" && !payload.group_by.length) {
    throw new Error("В режиме группировки выберите хотя бы одно поле");
  }
  const out = $("#exportOutput");
  setResultMessage(out, "Загрузка данных…");
  const res = await api(`/export/query/${datasetId}`, { method: "POST", json: payload });
  renderExportResult(res?.data || res);
  return res?.data || res;
}

async function downloadExportFile(format) {
  let datasetId;
  try {
    datasetId = ensureActiveDataset();
  } catch (err) {
    toast(err.message, true);
    return;
  }
  const payload = buildExportPayload(0);
  payload.limit = 100000;
  payload.offset = 0;
  const url = `${API}/export/download/${datasetId}?format=${encodeURIComponent(format)}`;
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  try {
    const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(payload) });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch {
        /* ignore */
      }
      throw new Error(typeof detail === "string" ? detail : "Export failed");
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] || `export_${datasetId}.${format}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`Скачан ${filename}`);
  } catch (err) {
    toast(err.message, true);
  }
}

function resetExportForm() {
  state.exportOffset = 0;
  $("#exportFilterList").innerHTML =
    `<p class="column-picker-empty">Нажмите «Добавить фильтр» для условия по колонке</p>`;
  $("#exportAggList").innerHTML =
    `<p class="column-picker-empty">По умолчанию — count; добавьте sum/mean/min/max</p>`;
  $$('#exportGroupPicker input[name="export_group_by"]').forEach((el) => {
    el.checked = false;
  });
  $$('#exportColumnPicker input[name="export_column"]').forEach((el) => {
    el.checked = true;
  });
  if ($("#exportSortBy")) $("#exportSortBy").value = "";
  if ($("#exportMeta")) $("#exportMeta").hidden = true;
  if ($("#exportPagination")) $("#exportPagination").hidden = true;
  setResultMessage($("#exportOutput"), "Настройте фильтры и нажмите «Применить».");
}

function setupExport() {
  $("#exportMode")?.addEventListener("change", syncExportModeUi);

  setupFilterList(
    "#exportFilterList",
    "#addExportFilter",
    "Нажмите «Добавить фильтр» для условия по колонке",
    "export"
  );

  setupAggList({
    listSelector: "#exportAggList",
    addButtonSelector: "#addExportAgg",
    emptyHint: "По умолчанию — count; добавьте sum/mean/min/max",
    listHasRows,
  });

  $("#clearExportGroupBy")?.addEventListener("click", () => {
    $$('#exportGroupPicker input[name="export_group_by"]').forEach((el) => {
      el.checked = false;
    });
  });

  $("#selectAllExportColumns")?.addEventListener("click", () => {
    const boxes = $$('#exportColumnPicker input[name="export_column"]');
    const all = boxes.length && boxes.every((b) => b.checked);
    boxes.forEach((b) => {
      b.checked = !all;
    });
  });

  $("#exportForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    state.exportOffset = 0;
    try {
      await runExportQuery(0);
      saveFilters("export");
      toast("Данные загружены");
    } catch (err) {
      setResultMessage($("#exportOutput"), err.message, true);
      toast(err.message, true);
    }
  });

  $("#resetExportForm")?.addEventListener("click", resetExportForm);
  $("#exportDownloadCsv")?.addEventListener("click", () => downloadExportFile("csv"));
  $("#exportDownloadJson")?.addEventListener("click", () => downloadExportFile("json"));
  $("#exportDownloadXlsx")?.addEventListener("click", () => downloadExportFile("xlsx"));

  $("#exportPrev")?.addEventListener("click", async () => {
    state.exportOffset = Math.max(0, state.exportOffset - state.exportLimit);
    try {
      await runExportQuery(state.exportOffset);
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#exportNext")?.addEventListener("click", async () => {
    if (state.exportOffset + state.exportLimit >= state.exportTotal) return;
    state.exportOffset += state.exportLimit;
    try {
      await runExportQuery(state.exportOffset);
    } catch (err) {
      toast(err.message, true);
    }
  });

  syncExportModeUi();
}


function init() {
  window.__quart = {
    api,
    toast,
    escapeHtml,
    formatCell,
    state,
    $,
    $$,
    ensureActiveDataset,
    setSelectedDataset,
    loadDatasetPassport,
    collectFiltersFromList,
    collectAnalysisAggregations,
    renderTableBlock,
    setResultMessage,
    renderAnalysisResult,
    renderReportTables,
    showPanel,
    applyFiltersToList,
    pollAiJob,
    refreshAiHealth,
    API,
  };

  bindAnalysisColumnsLoaded();
  bindReportColumnsLoaded();
  bindExportColumnsLoaded();

  try {
    setupNavigation();
    setupDropzone();
    setupMethodOptions();
    setupAuth();
    setupFilterSync();
    setupDatasets();
    setupEtl();
    setupAnalysis({ loadReports, listHasRows, setupFilterList });
    setupReports({ listHasRows, setupFilterList });
    setupExport();
    setupDrillDown();
    syncAuthUi();
    checkHealth();
    loadDatasets().catch((err) => toast(err.message, true));
    loadReports();
    setInterval(checkHealth, 15000);
  } catch (err) {
    console.error("Init failed:", err);
    toast(`Ошибка инициализации: ${err.message}`, true);
  }
}

init();
