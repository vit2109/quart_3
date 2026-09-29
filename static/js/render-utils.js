/** Общие хелперы отрисовки таблиц, секций и Chart.js. */

import { $, escapeHtml, formatCell, isNumericLike } from "./quart-core.js";

/** Chart.js — локальная копия (офлайн). */
export function loadChartJs() {
  if (typeof Chart !== "undefined") return Promise.resolve(Chart);
  if (loadChartJs._promise) return loadChartJs._promise;
  loadChartJs._promise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "/static/js/vendor/chart.umd.min.js";
    script.async = true;
    script.onload = () => resolve(window.Chart);
    script.onerror = () =>
      reject(new Error("Не удалось загрузить Chart.js из /static/js/vendor/"));
    document.head.appendChild(script);
  });
  return loadChartJs._promise;
}

export function destroyQuartCharts() {
  (window.__quartCharts || []).forEach((c) => {
    try {
      c.destroy();
    } catch (_) {
      /* ignore */
    }
  });
  window.__quartCharts = [];
}

/**
 * Универсальный column-chip picker.
 * @param {Array} columns
 * @param {{ inputName: string, checked?: (col,i)=>boolean, showDtype?: boolean }} opts
 */
export function renderColumnChipPicker(columns, opts) {
  const { inputName, checked = () => true, showDtype = true } = opts;
  if (!columns?.length) {
    return `<p class="column-picker-empty">Нет колонок</p>`;
  }
  return columns
    .map(
      (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="${escapeHtml(inputName)}" value="${escapeHtml(col.name)}" ${checked(col, i) ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)}${showDtype && col.dtype ? ` · ${escapeHtml(col.dtype)}` : ""}</small>
        </span>
      </label>`
    )
    .join("");
}

export function palette(index, alpha = 1) {
  const colors = [
    [15, 118, 110],
    [180, 83, 9],
    [37, 99, 135],
    [124, 58, 237],
    [190, 24, 93],
    [22, 163, 74],
  ];
  const [r, g, b] = colors[index % colors.length];
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function renderCollapsibleSection(title, innerHtml, defaultOpen = true, section = "") {
  const openAttr = defaultOpen ? " open" : "";
  const sectionCls = section ? ` collapsible-section collapsible-${section}` : " collapsible-section";
  return `
    <details class="${sectionCls.trim()}"${openAttr}>
      <summary>${escapeHtml(title)}</summary>
      <div class="collapsible-body">${innerHtml}</div>
    </details>`;
}

export function classifyReportSection(title) {
  const t = (title || "").toLowerCase();
  if (t.includes("обзор")) return { section: "overview", defaultOpen: true };
  if (t.includes("статистик")) return { section: "statistics", defaultOpen: false };
  if (t.includes("вывод") || t.includes("заключ")) return { section: "conclusions", defaultOpen: true };
  if (t.includes("коррел") || t.includes("аномал") || t.includes("закономер"))
    return { section: "analysis", defaultOpen: false };
  if (t.includes("топ") || t.includes("группир")) return { section: "grouping", defaultOpen: false };
  return { section: "other", defaultOpen: false };
}

export function setResultMessage(el, message, isError = false) {
  if (!el) return;
  el.innerHTML = `<p class="${isError ? "result-error" : "result-placeholder"}">${escapeHtml(message)}</p>`;
}

const TABLE_STORE = new Map();
let tableSeq = 0;

function renderTableBody(columns, rows, drillSet) {
  return (rows || [])
    .map((row) => {
      const cells = columns
        .map((c) => {
          const val = row?.[c];
          const numCls = isNumericLike(val) ? " num" : "";
          if (drillSet.has(c) && val != null && val !== "") {
            return `<td class="drill-cell${numCls}" data-drill-column="${escapeHtml(c)}" data-drill-value="${escapeHtml(String(val))}" title="Детализация: ${escapeHtml(c)} = ${escapeHtml(formatCell(val))}">${escapeHtml(formatCell(val))}</td>`;
          }
          const cls = isNumericLike(val) ? ' class="num"' : "";
          return `<td${cls}>${escapeHtml(formatCell(val))}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
}

function renderTablePagination(tableId, page, pageSize, totalRows) {
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));
  return `
    <div class="table-pagination" data-table-id="${escapeHtml(tableId)}" data-page="${page}" data-page-size="${pageSize}">
      <button type="button" class="btn-sm table-page-prev" ${page <= 1 ? "disabled" : ""}>← Назад</button>
      <span class="table-page-info">Стр. ${page} из ${totalPages} · всего ${totalRows} строк</span>
      <button type="button" class="btn-sm table-page-next" ${page >= totalPages ? "disabled" : ""}>Вперёд →</button>
    </div>`;
}

function renderTableInner(columns, rows, drillSet, tableId, paginate, pageSize) {
  const totalRows = rows?.length || 0;
  const pageRows = paginate ? rows.slice(0, pageSize) : rows;
  const head = columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body =
    renderTableBody(columns, pageRows, drillSet) ||
    `<tr><td colspan="${columns.length}">Нет строк</td></tr>`;
  const pagination =
    paginate && totalRows > pageSize
      ? renderTablePagination(tableId, 1, pageSize, totalRows)
      : "";
  return `
      ${pagination}
      <div class="table-scroll">
        <table class="data-table" ${tableId ? `data-table-id="${escapeHtml(tableId)}"` : ""}>
          <thead><tr>${head}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;
}

/** Привязать обработчики пагинации к таблицам внутри контейнера. */
export function initPaginatedTables(root = document) {
  root.querySelectorAll(".table-pagination[data-table-id]").forEach((nav) => {
    if (nav.dataset.bound === "1") return;
    nav.dataset.bound = "1";
    const tableId = nav.dataset.tableId;
    const store = TABLE_STORE.get(tableId);
    if (!store) return;

    const table = nav.parentElement?.querySelector(`table[data-table-id="${tableId}"]`);
    const tbody = table?.querySelector("tbody");
    const info = nav.querySelector(".table-page-info");
    const prevBtn = nav.querySelector(".table-page-prev");
    const nextBtn = nav.querySelector(".table-page-next");
    if (!tbody || !info || !prevBtn || !nextBtn) return;

    const pageSize = Number(nav.dataset.pageSize) || 50;
    const drillSet = new Set(store.drillableColumns || []);
    const totalRows = store.rows.length;
    const totalPages = Math.max(1, Math.ceil(totalRows / pageSize));

    const renderPage = (page) => {
      const safePage = Math.max(1, Math.min(page, totalPages));
      nav.dataset.page = String(safePage);
      const start = (safePage - 1) * pageSize;
      const slice = store.rows.slice(start, start + pageSize);
      tbody.innerHTML =
        renderTableBody(store.columns, slice, drillSet) ||
        `<tr><td colspan="${store.columns.length}">Нет строк</td></tr>`;
      info.textContent = `Стр. ${safePage} из ${totalPages} · всего ${totalRows} строк`;
      prevBtn.disabled = safePage <= 1;
      nextBtn.disabled = safePage >= totalPages;
    };

    prevBtn.addEventListener("click", () => renderPage(Number(nav.dataset.page) - 1));
    nextBtn.addEventListener("click", () => renderPage(Number(nav.dataset.page) + 1));
  });
}

export function renderTableBlock(title, columns, rows, options = {}) {
  const {
    collapsible = false,
    defaultOpen = true,
    section = "",
    drillableColumns = [],
    paginate = true,
    pageSize = 50,
  } = options;
  const drillSet = new Set(drillableColumns || []);
  if (!columns?.length) {
    const inner = `<p class="result-placeholder">Нет данных</p>`;
    if (collapsible) {
      return renderCollapsibleSection(title, inner, defaultOpen, section);
    }
    return `<div class="table-block"><h3>${escapeHtml(title)}</h3>${inner}</div>`;
  }

  const allRows = rows || [];
  const usePagination = paginate !== false && allRows.length > pageSize;
  let tableId = "";
  if (usePagination) {
    tableId = `qt_${++tableSeq}`;
    TABLE_STORE.set(tableId, {
      columns,
      rows: allRows,
      drillableColumns: drillableColumns || [],
    });
  }

  const inner = renderTableInner(columns, allRows, drillSet, tableId, usePagination, pageSize);

  if (collapsible) {
    return renderCollapsibleSection(title, inner, defaultOpen, section);
  }

  return `
    <div class="table-block">
      <h3>${escapeHtml(title)}</h3>
      ${inner}
    </div>`;
}

export function renderQualityResult(el, payload) {
  const data = payload?.data || {};
  const rows = [
    { Показатель: "Completeness", Значение: data.completeness },
    { Показатель: "Validity", Значение: data.validity },
    { Показатель: "Consistency", Значение: data.consistency },
  ];
  if (el) el.innerHTML = renderTableBlock("Качество данных", ["Показатель", "Значение"], rows);
}
