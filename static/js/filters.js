/** Фильтры: UI, autocomplete, localStorage (Фаза D). */

import {
  $,
  $$,
  FILTERS_STORAGE_PREFIX,
  api,
  escapeHtml,
  ensureActiveDataset,
  state,
} from "./quart-core.js";

export const EXPORT_FILTER_OPS = [
  { value: "eq", label: "равно" },
  { value: "ne", label: "не равно" },
  { value: "contains", label: "содержит" },
  { value: "not_contains", label: "не содержит" },
  { value: "gt", label: "больше" },
  { value: "gte", label: "больше или равно" },
  { value: "lt", label: "меньше" },
  { value: "lte", label: "меньше или равно" },
  { value: "between", label: "между" },
  { value: "is_null", label: "пусто" },
  { value: "not_null", label: "не пусто" },
  { value: "in_list", label: "в списке" },
];

const FILTER_OPS_BY_KIND = {
  number: ["eq", "ne", "gt", "gte", "lt", "lte", "between", "is_null", "not_null"],
  string: ["eq", "ne", "contains", "not_contains", "in_list", "is_null", "not_null"],
  datetime: ["eq", "ne", "gte", "lte", "gt", "lt", "between", "is_null", "not_null"],
  boolean: ["eq", "ne", "is_null", "not_null"],
};

const FILTER_SUGGEST_TTL_MS = 60_000;
let filterSuggestTimer = null;

export function exportColumnOptions(columns, numericOnly = false) {
  const list = numericOnly ? columns.filter((c) => c.kind === "number") : columns;
  return list
    .map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`)
    .join("");
}

export function columnKindByName(name) {
  return state.columns.find((c) => c.name === name)?.kind || "string";
}

function filterOpsForKind(kind) {
  const keys = FILTER_OPS_BY_KIND[kind] || FILTER_OPS_BY_KIND.string;
  return EXPORT_FILTER_OPS.filter((o) => keys.includes(o.value));
}

function filterOpsHtml(kind, selectedOp) {
  const ops = filterOpsForKind(kind);
  const selected = ops.some((o) => o.value === selectedOp) ? selectedOp : ops[0]?.value;
  return ops
    .map(
      (o) =>
        `<option value="${o.value}"${o.value === selected ? " selected" : ""}>${escapeHtml(o.label)}</option>`
    )
    .join("");
}

function filterValueControlHtml(kind, op) {
  if (op === "is_null" || op === "not_null") {
    return `<span class="filter-value-wrap filter-value-muted" hidden aria-hidden="true">—</span>`;
  }
  if (op === "between") {
    if (kind === "datetime") {
      return `<span class="filter-value-wrap filter-between">
        <input type="date" name="filter_value_from" placeholder="От" autocomplete="off" />
        <input type="date" name="filter_value_to" placeholder="До" autocomplete="off" />
      </span>`;
    }
    const inputType = kind === "number" ? "number" : "text";
    return `<span class="filter-value-wrap filter-between">
      <input type="${inputType}" name="filter_value_from" step="any" placeholder="От" autocomplete="off" />
      <input type="${inputType}" name="filter_value_to" step="any" placeholder="До" autocomplete="off" />
    </span>`;
  }
  if (kind === "boolean") {
    return `<span class="filter-value-wrap"><select name="filter_value"><option value="true">true</option><option value="false">false</option></select></span>`;
  }
  if (kind === "datetime") {
    return `<span class="filter-value-wrap filter-autocomplete">
      <input type="date" name="filter_value" placeholder="YYYY-MM-DD" autocomplete="off" />
      <ul class="filter-suggest-list" role="listbox" hidden></ul>
    </span>`;
  }
  if (kind === "number") {
    return `<span class="filter-value-wrap filter-autocomplete">
      <input type="number" name="filter_value" step="any" placeholder="Число" autocomplete="off" />
      <ul class="filter-suggest-list" role="listbox" hidden></ul>
    </span>`;
  }
  const placeholder = op === "in_list" ? "a, b, c" : "Значение";
  return `<span class="filter-value-wrap filter-autocomplete">
    <input type="text" name="filter_value" placeholder="${escapeHtml(placeholder)}" autocomplete="off" />
    <ul class="filter-suggest-list" role="listbox" hidden></ul>
  </span>`;
}

async function fetchColumnValueSuggestions(column, q) {
  const datasetId = ensureActiveDataset();
  const cacheKey = `${datasetId}:${column}:${(q || "").toLowerCase()}`;
  const cached = state.filterValueSuggestCache.get(cacheKey);
  if (cached && Date.now() - cached.ts < FILTER_SUGGEST_TTL_MS) {
    return cached.values;
  }
  const params = new URLSearchParams({
    column,
    q: q || "",
    limit: "25",
  });
  const data = await api(`/export/column-values/${datasetId}?${params.toString()}`, {
    timeoutMs: 15000,
  });
  const values = (data?.data?.values || []).map((v) => String(v ?? ""));
  state.filterValueSuggestCache.set(cacheKey, { values, ts: Date.now() });
  return values;
}

function hideFilterSuggestions(input) {
  const list = input?.closest(".filter-autocomplete")?.querySelector(".filter-suggest-list");
  if (list) list.hidden = true;
}

function renderFilterSuggestions(input, values) {
  const wrap = input.closest(".filter-autocomplete");
  if (!wrap) return;
  const list = wrap.querySelector(".filter-suggest-list");
  if (!list) return;
  if (!values.length) {
    list.hidden = true;
    list.innerHTML = "";
    return;
  }
  list.innerHTML = values
    .map(
      (v) =>
        `<li role="option" tabindex="-1" data-value="${escapeHtml(v)}">${escapeHtml(v)}</li>`
    )
    .join("");
  list.hidden = false;
}

function scheduleFilterSuggestions(row, input) {
  clearTimeout(filterSuggestTimer);
  filterSuggestTimer = setTimeout(async () => {
    const column = row.querySelector('[name="filter_column"]')?.value;
    const op = row.querySelector('[name="filter_op"]')?.value;
    if (!column || op === "is_null" || op === "not_null") return;
    const q = input.value || "";
    if (q.length < 1 && op !== "eq") {
      hideFilterSuggestions(input);
      return;
    }
    try {
      const values = await fetchColumnValueSuggestions(column, q);
      renderFilterSuggestions(input, values);
    } catch {
      hideFilterSuggestions(input);
    }
  }, 280);
}

export function bindFilterValueAutocomplete(row) {
  if (!row) return;
  row.querySelectorAll(
    '[name="filter_value"], [name="filter_value_from"], [name="filter_value_to"]'
  ).forEach((input) => {
    if (input.dataset.suggestBound) return;
    input.dataset.suggestBound = "1";
    input.addEventListener("input", () => scheduleFilterSuggestions(row, input));
    input.addEventListener("focus", () => scheduleFilterSuggestions(row, input));
    input.addEventListener("blur", () => {
      setTimeout(() => hideFilterSuggestions(input), 150);
    });
  });

  const list = row.querySelector(".filter-suggest-list");
  if (list && !list.dataset.suggestBound) {
    list.dataset.suggestBound = "1";
    list.addEventListener("mousedown", (e) => {
      const item = e.target.closest("[data-value]");
      if (!item) return;
      e.preventDefault();
      const input = row.querySelector('[name="filter_value"]') || row.querySelector('[name="filter_value_from"]');
      if (input) {
        let val = item.dataset.value || "";
        const kind = columnKindByName(row.querySelector('[name="filter_column"]')?.value);
        if (kind === "datetime" && input.type === "date") {
          val = val.slice(0, 10);
        }
        input.value = val;
        hideFilterSuggestions(input);
      }
    });
  }
}

export function updateDataFilterRow(row) {
  if (!row) return;
  const colName = row.querySelector('[name="filter_column"]')?.value;
  const kind = columnKindByName(colName);
  const opSel = row.querySelector('[name="filter_op"]');
  const prevOp = opSel?.value || "eq";
  if (opSel) opSel.innerHTML = filterOpsHtml(kind, prevOp);
  const op = opSel?.value || "eq";
  const oldWrap = row.querySelector(".filter-value-wrap");
  const oldVal =
    oldWrap?.querySelector('[name="filter_value"]')?.value ??
    (oldWrap?.hidden ? null : oldWrap?.textContent);
  oldWrap?.replaceWith(
    (() => {
      const tpl = document.createElement("template");
      tpl.innerHTML = filterValueControlHtml(kind, op);
      return tpl.content.firstElementChild;
    })()
  );
  const valEl = row.querySelector('[name="filter_value"]');
  if (valEl && oldVal != null && oldVal !== "" && oldVal !== "—") {
    valEl.value = oldVal;
  }
  bindFilterValueAutocomplete(row);
}

export function createDataFilterRow() {
  const cols = state.columns;
  const firstCol = cols[0]?.name || "";
  const kind = columnKindByName(firstCol);
  return `
    <div class="export-filter-row">
      <select name="filter_column">${exportColumnOptions(cols)}</select>
      <select name="filter_op">${filterOpsHtml(kind, "eq")}</select>
      ${filterValueControlHtml(kind, "eq")}
      <button type="button" class="btn-sm btn-danger" data-remove-filter aria-label="Удалить">×</button>
    </div>`;
}

export function refreshFilterColumnSelects(listSelector, columns) {
  const cols = columns.length ? columns : state.columns;
  $$(`${listSelector} select[name=filter_column]`).forEach((sel) => {
    const prev = sel.value;
    sel.innerHTML = exportColumnOptions(cols);
    if (prev && cols.some((c) => c.name === prev)) sel.value = prev;
    updateDataFilterRow(sel.closest(".export-filter-row"));
  });
}

export function collectFiltersFromList(listSelector) {
  return $$(`${listSelector} .export-filter-row`)
    .map((row) => {
      const column = row.querySelector('[name="filter_column"]')?.value;
      const op = row.querySelector('[name="filter_op"]')?.value || "eq";
      if (!column) return null;
      if (op === "is_null" || op === "not_null") {
        return { column, op, value: null };
      }
      const kind = columnKindByName(column);
      if (op === "between") {
        const fromRaw = row.querySelector('[name="filter_value_from"]')?.value;
        const toRaw = row.querySelector('[name="filter_value_to"]')?.value;
        if (!fromRaw || !toRaw) return null;
        let fromVal = fromRaw;
        let toVal = toRaw;
        if (kind === "number") {
          fromVal = Number(fromRaw);
          toVal = Number(toRaw);
          if (Number.isNaN(fromVal) || Number.isNaN(toVal)) return null;
        }
        return { column, op, value: [fromVal, toVal] };
      }
      const valueEl = row.querySelector('[name="filter_value"]');
      const valueRaw = valueEl?.value;
      if (valueRaw === "" || valueRaw == null) return null;
      let value = valueRaw;
      if (op === "in_list") {
        value = valueRaw.includes(",")
          ? valueRaw.split(",").map((s) => s.trim()).filter(Boolean)
          : valueRaw.trim();
      } else if (kind === "boolean") {
        value = valueRaw === "true";
      } else if (kind === "number" && !Number.isNaN(Number(valueRaw)) && valueRaw.trim() !== "") {
        value = Number(valueRaw);
      }
      return { column, op, value };
    })
    .filter(Boolean);
}

export function buildDefaultPeriodFilter(days, dateColName) {
  const columns = state.columns || [];
  const dateColumns = columns.filter((c) => c.kind === "datetime");
  const col = dateColName || dateColumns[0]?.name;
  if (!col || !days) return null;
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - Number(days));
  const fmt = (d) => d.toISOString().slice(0, 10);
  return { column: col, op: "between", value: [fmt(from), fmt(to)] };
}

function filtersStorageKey(context) {
  const ds = state.selectedDatasetId;
  if (!ds || !context) return null;
  return `${FILTERS_STORAGE_PREFIX}_${ds}_${context}`;
}

function filterListSelector(context) {
  if (context === "analysis") return "#analysisFilterList";
  if (context === "report") return "#reportFilterList";
  if (context === "export") return "#exportFilterList";
  return null;
}

export function saveFilters(context) {
  const key = filtersStorageKey(context);
  const listSelector = filterListSelector(context);
  if (!key || !listSelector) return;
  const rows = $$(`${listSelector} .export-filter-row`).map((row) => ({
    column: row.querySelector('[name="filter_column"]')?.value || "",
    op: row.querySelector('[name="filter_op"]')?.value || "eq",
    value: row.querySelector('[name="filter_value"]')?.value ?? "",
    value_from: row.querySelector('[name="filter_value_from"]')?.value ?? "",
    value_to: row.querySelector('[name="filter_value_to"]')?.value ?? "",
  }));
  localStorage.setItem(key, JSON.stringify({ rows }));
  updateActiveFilterBadge();
}

export function restoreFilters(context, emptyHint, listHasRows) {
  const key = filtersStorageKey(context);
  const listSelector = filterListSelector(context);
  const list = listSelector ? $(listSelector) : null;
  if (!key || !list) return;
  const raw = localStorage.getItem(key);
  if (!raw) return;
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    return;
  }
  const rows = data?.rows || [];
  if (!rows.length) return;
  list.innerHTML = "";
  rows.forEach((r) => {
    list.insertAdjacentHTML("beforeend", createDataFilterRow());
    const rowEl = list.lastElementChild;
    const colSel = rowEl.querySelector('[name="filter_column"]');
    if (colSel && r.column && state.columns.some((c) => c.name === r.column)) {
      colSel.value = r.column;
    }
    updateDataFilterRow(rowEl);
    const opSel = rowEl.querySelector('[name="filter_op"]');
    if (opSel && r.op) opSel.value = r.op;
    updateDataFilterRow(rowEl);
    const valEl = rowEl.querySelector('[name="filter_value"]');
    if (valEl && r.value != null && r.value !== "") valEl.value = r.value;
    const fromEl = rowEl.querySelector('[name="filter_value_from"]');
    if (fromEl && r.value_from) fromEl.value = r.value_from;
    const toEl = rowEl.querySelector('[name="filter_value_to"]');
    if (toEl && r.value_to) toEl.value = r.value_to;
  });
  if (listHasRows && !listHasRows(listSelector, ".export-filter-row") && emptyHint) {
    list.innerHTML = `<p class="column-picker-empty">${emptyHint}</p>`;
  }
}

export function restoreAllSavedFilters(listHasRows) {
  restoreFilters("analysis", "Нажмите «Добавить фильтр» для условия по колонке", listHasRows);
  restoreFilters("report", "Нажмите «Добавить фильтр» для условия по колонке", listHasRows);
  restoreFilters("export", "Нажмите «Добавить фильтр» для условия по колонке", listHasRows);
}

export function applyFiltersToList(listSelector, filters, emptyHint = "", listHasRows = null) {
  const list = $(listSelector);
  if (!list || !filters?.length) return;
  list.innerHTML = "";
  filters.forEach((f) => {
    if (!f?.column) return;
    list.insertAdjacentHTML("beforeend", createDataFilterRow());
    const rowEl = list.lastElementChild;
    const colSel = rowEl.querySelector('[name="filter_column"]');
    if (colSel && state.columns.some((c) => c.name === f.column)) colSel.value = f.column;
    updateDataFilterRow(rowEl);
    const opSel = rowEl.querySelector('[name="filter_op"]');
    if (opSel && f.op) opSel.value = f.op;
    updateDataFilterRow(rowEl);
    if (f.op === "between" && Array.isArray(f.value)) {
      const fromEl = rowEl.querySelector('[name="filter_value_from"]');
      const toEl = rowEl.querySelector('[name="filter_value_to"]');
      if (fromEl) fromEl.value = f.value[0];
      if (toEl) toEl.value = f.value[1];
    } else {
      const valEl = rowEl.querySelector('[name="filter_value"]');
      if (valEl && f.value != null && f.value !== "") {
        valEl.value = Array.isArray(f.value) ? f.value.join(", ") : String(f.value);
      }
    }
  });
  if (listHasRows && !listHasRows(listSelector, ".export-filter-row") && emptyHint) {
    list.innerHTML = `<p class="column-picker-empty">${emptyHint}</p>`;
  }
}

export function setupFilterList(listSelector, addButtonSelector, emptyHint, context = null, listHasRows) {
  const list = $(listSelector);
  const addBtn = $(addButtonSelector);
  if (!list || !addBtn) return;

  addBtn.addEventListener("click", () => {
    const empty = list.querySelector(".column-picker-empty");
    if (empty) empty.remove();
    list.insertAdjacentHTML("beforeend", createDataFilterRow());
    const row = list.lastElementChild;
    updateDataFilterRow(row);
    if (context) saveFilters(context);
  });

  list.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-filter]");
    if (!btn) return;
    btn.closest(".export-filter-row")?.remove();
    if (listHasRows && !listHasRows(listSelector, ".export-filter-row")) {
      list.innerHTML = `<p class="column-picker-empty">${emptyHint}</p>`;
    }
    if (context) saveFilters(context);
  });

  list.addEventListener("change", (e) => {
    const row = e.target.closest(".export-filter-row");
    if (!row) return;
    if (e.target.matches('[name="filter_column"], [name="filter_op"]')) {
      updateDataFilterRow(row);
    }
    if (context) saveFilters(context);
  });

  if (context) {
    list.addEventListener("input", () => {
      clearTimeout(list._filterSaveT);
      list._filterSaveT = setTimeout(() => saveFilters(context), 400);
    });
  }
}

export const EXPORT_AGG_OPS = [
  { value: "sum", label: "sum" },
  { value: "mean", label: "mean" },
  { value: "min", label: "min" },
  { value: "max", label: "max" },
  { value: "count", label: "count" },
  { value: "n_unique", label: "n_unique" },
];

export function createExportAggRow(options = {}) {
  const { numericOnly = false } = options;
  const cols = numericOnly ? state.columns.filter((c) => c.kind === "number") : state.columns;
  const aggs = EXPORT_AGG_OPS.map(
    (o) => `<option value="${o.value}">${escapeHtml(o.label)}</option>`
  ).join("");
  return `
    <div class="export-agg-row">
      <select name="agg_column">${exportColumnOptions(cols, numericOnly)}</select>
      <select name="agg_func">${aggs}</select>
      <input type="text" name="agg_alias" placeholder="Псевдоним (опц.)" />
      <button type="button" class="btn-sm btn-danger" data-remove-agg aria-label="Удалить">×</button>
    </div>`;
}

/** Собрать агрегации из списка agg-row. */
export function collectAggregationsFromList(listSelector) {
  return $$(`${listSelector} .export-agg-row`)
    .map((row) => {
      const column = row.querySelector('[name="agg_column"]')?.value;
      const agg = row.querySelector('[name="agg_func"]')?.value || "sum";
      const alias = row.querySelector('[name="agg_alias"]')?.value?.trim();
      if (!column) return null;
      return { column, agg, alias: alias || null };
    })
    .filter(Boolean);
}

/** Обновить select колонок во всех agg-row списка. */
export function refreshAggColumnSelects(listSelector, columns, { numericOnly = false } = {}) {
  const cols = columns?.length ? columns : state.columns;
  $$(`${listSelector} select[name=agg_column]`).forEach((sel) => {
    const prev = sel.value;
    sel.innerHTML = exportColumnOptions(cols, numericOnly);
    if (prev && cols.some((c) => c.name === prev)) sel.value = prev;
  });
}

/** Подключить кнопки add/remove для agg-list. */
export function setupAggList({
  listSelector,
  addButtonSelector,
  emptyHint,
  createRowFn = () => createExportAggRow(),
  listHasRows,
}) {
  const list = $(listSelector);
  const addBtn = $(addButtonSelector);
  if (!list || !addBtn) return;

  addBtn.addEventListener("click", () => {
    const empty = list.querySelector(".column-picker-empty");
    if (empty) empty.remove();
    list.insertAdjacentHTML("beforeend", createRowFn());
  });

  list.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-agg]");
    if (!btn) return;
    btn.closest(".export-agg-row")?.remove();
    if (listHasRows && !listHasRows(listSelector, ".export-agg-row") && emptyHint) {
      list.innerHTML = `<p class="column-picker-empty">${emptyHint}</p>`;
    }
  });
}

const FILTER_CONTEXTS = ["analysis", "report", "export"];

/** Скопировать фильтры из одного контекста во все остальные. */
export function copyFiltersToAllContexts(fromContext, listHasRows) {
  const fromKey = filtersStorageKey(fromContext);
  if (!fromKey) return 0;
  const raw = localStorage.getItem(fromKey);
  if (!raw) return 0;
  let copied = 0;
  for (const ctx of FILTER_CONTEXTS) {
    if (ctx === fromContext) continue;
    const toKey = filtersStorageKey(ctx);
    if (!toKey) continue;
    localStorage.setItem(toKey, raw);
    copied += 1;
  }
  if (copied) restoreAllSavedFilters(listHasRows);
  updateActiveFilterBadge();
  return copied;
}

/** Обновить badge активных фильтров в шапке. */
export function updateActiveFilterBadge() {
  const el = $("#activeFiltersBadge");
  if (!el) return;
  let total = 0;
  for (const ctx of FILTER_CONTEXTS) {
    const key = filtersStorageKey(ctx);
    if (!key) continue;
    try {
      const data = JSON.parse(localStorage.getItem(key) || "{}");
      const rows = Array.isArray(data) ? data : data?.rows || [];
      total += rows.filter((f) => f?.column).length;
    } catch {
      /* ignore */
    }
  }
  el.textContent = total > 0 ? String(total) : "";
  el.hidden = total === 0;
}
