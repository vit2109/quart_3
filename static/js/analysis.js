/** Панель «Анализ» (E22). */

import {
  $,
  $$,
  api,
  ensureActiveDataset,
  escapeHtml,
  formatCell,
  pretty,
  renderResultWarningBanner,
  state,
  toast,
} from "./quart-core.js";
import {
  EXPORT_AGG_OPS,
  collectFiltersFromList,
  collectAggregationsFromList,
  createExportAggRow,
  exportColumnOptions,
  refreshFilterColumnSelects,
  saveFilters,
} from "./filters.js";
import {
  renderCollapsibleSection,
  destroyQuartCharts,
  renderTableBlock,
  setResultMessage,
  initPaginatedTables,
} from "./render-utils.js";
import { selectedColumns } from "./datasets-ui.js";
import { renderReportTables, loadReports as loadReportsDefault } from "./reports.js";
import { initHelpModal } from "./help-modal.js";

export async function loadAiModels() {
  const select = $("#aiModelSelect");
  if (!select) return;
  const current = select.value;
  try {
    const resp = await api("/analysis/ai/models", { timeoutMs: 15000 });
    const models = resp?.data || [];
    select.replaceChildren();
    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "По умолчанию (.env)";
    select.appendChild(defaultOpt);
    const seen = new Set();
    models.forEach((m) => {
      if (!m.path || seen.has(m.path)) return;
      seen.add(m.path);
      const opt = document.createElement("option");
      opt.value = m.path;
      const label = m.label || m.name;
      const size = m.size_mb ? ` · ${m.size_mb} MB` : "";
      const def = m.is_default ? " ★" : "";
      opt.textContent = `${label}${size}${def}`;
      select.appendChild(opt);
    });
    if (current && [...select.options].some((o) => o.value === current)) {
      select.value = current;
    }
  } catch (err) {
    console.warn("loadAiModels:", err);
  }
}

export function renderAnalysisResult(el, payload) {
  destroyQuartCharts();

  const data = payload?.data || payload;
  if (!data || typeof data !== "object") {
    setResultMessage(el, pretty(payload));
    return;
  }

  const blocks = [];

  if (data.result_warning) {
    blocks.push(renderResultWarningBanner(data));
  }

  if (data.stats) {
    const rows = Object.entries(data.stats).map(([name, meta]) => ({
      Колонка: name,
      Тип: meta.dtype,
      Всего: meta.count,
      Пропуски: meta.missing,
      Уникальных: meta.unique,
      Среднее: meta.mean,
      Медиана: meta.median,
      СКО: meta.std,
      Мин: meta.min,
      Макс: meta.max,
      Q25: meta.q25,
      Q75: meta.q75,
    }));
    blocks.push(
      `<p class="result-meta">Строк: <strong>${escapeHtml(formatCell(data.rows))}</strong> · колонок в выборке: <strong>${escapeHtml(formatCell((data.columns || []).length))}</strong>` +
        (data.filtered_rows != null
          ? ` · после фильтров: <strong>${escapeHtml(formatCell(data.filtered_rows))}</strong> из ${escapeHtml(formatCell(data.source_rows))}`
          : "") +
        `</p>`
    );
    blocks.push(
      renderTableBlock(
        "Статистика",
        [
          "Колонка",
          "Тип",
          "Всего",
          "Пропуски",
          "Уникальных",
          "Среднее",
          "Медиана",
          "СКО",
          "Мин",
          "Макс",
          "Q25",
          "Q75",
        ],
        rows
      )
    );
  } else if (data.matrix) {
    const views = window.QuartAnalysisViews;
    blocks.push(
      views?.renderCorrelationHeatmap
        ? views.renderCorrelationHeatmap(data)
        : renderTableBlock(`Корреляции (${data.method === "spearman" ? "Спирмен (Spearman)" : data.method === "kendall" ? "Кендалл (Kendall)" : "Пирсон (Pearson)"})`, ["Колонка", ...(data.columns || [])], [])
    );
  } else if (data.metrics && data.period_a) {
    const views = window.QuartAnalysisViews;
    blocks.push(views?.renderCompareView ? views.renderCompareView(data) : "");
  } else if (data.rows && data.plan) {
    const views = window.QuartAnalysisViews;
    blocks.push(
      views?.renderNlQueryView
        ? views.renderNlQueryView(data, renderTableBlock)
        : renderTableBlock("Результат", data.columns || [], data.rows || [])
    );
  } else if (data.rows && data.mode) {
    const views = window.QuartAnalysisViews;
    blocks.push(views?.renderExploreView ? views.renderExploreView(data, renderTableBlock) : "");
  } else if (data.date_col && data.periods && data.series) {
    const views = window.QuartAnalysisViews;
    blocks.push(views?.renderTimeseriesView ? views.renderTimeseriesView(data, renderTableBlock) : "");
  } else if (data.rows && data.sql) {
    blocks.push(`<p class="result-meta">SQL · строк: <strong>${formatCell(data.returned_rows)}</strong></p>`);
    blocks.push(
      renderTableBlock(
        "Результат SQL",
        data.columns || (data.rows[0] ? Object.keys(data.rows[0]) : []),
        data.rows || []
      )
    );
  } else if (data.hhi != null && data.rows && data.metric) {
    const views = window.QuartAnalysisViews;
    blocks.push(views?.renderParetoView ? views.renderParetoView(data, renderTableBlock) : "");
  } else if (data.anomalies) {
    const rows = data.anomalies;
    const columns = rows.length ? Object.keys(rows[0]) : [];
    blocks.push(
      `<p class="result-meta">Найдено аномалий: <strong>${escapeHtml(formatCell(data.anomaly_count))}</strong></p>`
    );
    blocks.push(renderTableBlock("Аномалии", columns, rows));
  } else if (data.forecast) {
    const views = window.QuartAnalysisViews;
    blocks.push(
      views?.renderForecastChart
        ? views.renderForecastChart(data, renderTableBlock)
        : renderTableBlock("Прогноз", ["step", "yhat", "baseline_mean"], data.forecast)
    );
  } else if (data.kpis) {
    const views = window.QuartAnalysisViews;
    blocks.push(views?.renderKpiCards ? views.renderKpiCards(data) : "");
  } else if (data.answer && (data.knowledge_sources != null || data.table_query != null)) {
    blocks.push(`<p class="result-meta">Unified ask · набор #${escapeHtml(formatCell(data.dataset_id))}</p>`);
    if (data.question) blocks.push(`<p class="result-meta">Вопрос: ${escapeHtml(data.question)}</p>`);
    blocks.push(`<article class="ai-narrative">${escapeHtml(data.answer)}</article>`);
    const sources = data.knowledge_sources || [];
    if (sources.length) {
      blocks.push(
        renderCollapsibleSection(
          "Источники базы знаний",
          `<ul class="insights-list">${sources.map((s) => `<li>${escapeHtml(s.document_title || s.chunk_id)}: ${escapeHtml(s.preview || "")}</li>`).join("")}</ul>`,
          false,
          "knowledge"
        )
      );
    }
    if (data.table_query?.rows?.length) {
      const tq = data.table_query;
      blocks.push(
        renderTableBlock(
          "Табличный результат",
          tq.columns || Object.keys(tq.rows[0] || {}),
          tq.rows
        )
      );
    }
  } else if (data.analysis_text) {
    blocks.push(
      `<p class="result-meta">Модель: <strong>${escapeHtml(data.model || "local")}</strong>` +
        (data.backend ? ` · ${escapeHtml(data.backend)}` : "") +
        (data.report_id ? ` · отчёт #${escapeHtml(data.report_id)}` : "") +
        `</p>`
    );
    if (data.question) {
      blocks.push(`<p class="result-meta">Задача: ${escapeHtml(data.question)}</p>`);
    }
    if (data.context_preview) {
      const cp = data.context_preview;
      blocks.push(
        `<p class="result-meta">Контекст: <strong>${escapeHtml(formatCell(cp.rows))}</strong> строк · ` +
          `<strong>${escapeHtml(formatCell(cp.columns_count))}</strong> колонок в профиле</p>`
      );
    }
    blocks.push(`<article class="ai-narrative">${escapeHtml(data.analysis_text)}</article>`);
  } else if (Array.isArray(data.tables)) {
    renderReportTables(el, data);
    return;
  } else {
    // Generic object → key/value table
    const rows = Object.entries(data).map(([k, v]) => ({
      Поле: k,
      Значение: typeof v === "object" ? pretty(v) : v,
    }));
    blocks.push(renderTableBlock("Результат", ["Поле", "Значение"], rows));
  }

  el.innerHTML = blocks.join("");
  initPaginatedTables(el);
}

export function renderAnalysisExplorePickers(columns) {
  const groupPicker = $("#analysisGroupPicker");
  const colPicker = $("#exploreColumnPicker");
  const sortSelect = $("#exploreSortBy");
  const chartLabel = $("#exploreChartLabel");
  const chartValue = $("#exploreChartValue");

  refreshFilterColumnSelects("#analysisFilterList", columns);
  refreshAnalysisAggColumnSelects(columns);

  if (!columns.length) {
    if (groupPicker) groupPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    if (colPicker) colPicker.innerHTML = `<p class="column-picker-empty">Нет колонок</p>`;
    if (sortSelect) sortSelect.innerHTML = `<option value="">— без сортировки —</option>`;
    if (chartLabel) chartLabel.innerHTML = `<option value="">—</option>`;
    if (chartValue) chartValue.innerHTML = `<option value="">—</option>`;
    return;
  }

  const categorical = columns.filter((c) => c.kind !== "number");
  const groupSource = categorical.length ? categorical : columns;

  if (groupPicker) {
    groupPicker.innerHTML = groupSource
      .map(
        (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="analysis_group_by" value="${escapeHtml(col.name)}" ${i === 0 ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
      )
      .join("");
  }

  if (colPicker) {
    colPicker.innerHTML = columns
      .map(
        (col) => `
      <label class="column-chip">
        <input type="checkbox" name="explore_column" value="${escapeHtml(col.name)}" checked />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
      )
      .join("");
  }

  const sortOpts =
    `<option value="">— без сортировки —</option>` +
    columns.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
  if (sortSelect) sortSelect.innerHTML = sortOpts;

  if (chartLabel) {
    chartLabel.innerHTML =
      `<option value="">— выберите —</option>` +
      columns.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
    if (groupSource[0]) chartLabel.value = groupSource[0].name;
  }
  if (chartValue) {
    const numeric = columns.filter((c) => c.kind === "number");
    chartValue.innerHTML =
      `<option value="">— выберите —</option>` +
      numeric.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
    if (numeric[0]) chartValue.value = numeric[0].name;
  }

  const tsPicker = $("#timeseriesMetricPicker");
  if (tsPicker) {
    const numeric = columns.filter((c) => c.kind === "number");
    if (!numeric.length) {
      tsPicker.innerHTML = `<p class="column-picker-empty">Числовых колонок нет</p>`;
    } else {
      tsPicker.innerHTML = numeric
        .map(
          (col, i) => `
      <label class="column-chip">
        <input type="checkbox" name="timeseries_metric" value="${escapeHtml(col.name)}" ${i < 2 ? "checked" : ""} />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
        )
        .join("");
    }
  }

  const paretoSel = $("#paretoMetricSelect");
  if (paretoSel) {
    const numeric = columns.filter((c) => c.kind === "number");
    paretoSel.innerHTML =
      `<option value="">— выберите —</option>` +
      numeric.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
    if (numeric[0]) paretoSel.value = numeric[0].name;
  }
}

export function refreshAnalysisAggColumnSelects(columns) {
  const cols = columns.length ? columns : state.columns;
  $$("#analysisAggList select[name=agg_column], #analysisKpiAggList select[name=agg_column]").forEach((sel) => {
    const prev = sel.value;
    sel.innerHTML = exportColumnOptions(cols, sel.closest("#analysisKpiAggList") != null);
    if (prev && cols.some((c) => c.name === prev)) sel.value = prev;
  });
}

export function collectAnalysisAggregations(listSelector) {
  return collectAggregationsFromList(listSelector);
}

export function syncExploreModeUi() {
  const mode = $("#exploreMode")?.value || "grouped";
  const grouped = $("#exploreGroupedBlock");
  const raw = $("#exploreRawBlock");
  if (grouped) grouped.hidden = mode !== "grouped";
  if (raw) raw.hidden = mode !== "raw";
}

export function analysisFiltersPayload() {
  return collectFiltersFromList("#analysisFilterList");
}

export function setupMethodOptions() {
  const select = $("#analysisMethod");
  if (!select) return;
  const contamination = $('input[name="contamination"]');
  const out = $("#contaminationOut");

  const sync = () => {
    const method = select.value;
    const hide = (sel, on) => {
      const el = $(sel);
      if (el) el.hidden = on;
    };
    const filterMethods = ["explore", "timeseries", "pareto", "statistics", "correlations", "anomalies", "kpis", "compare", "ai"];
    hide("#opt-filters", !filterMethods.includes(method));
    hide("#opt-explore", !["explore", "pareto"].includes(method));
    hide("#opt-timeseries", method !== "timeseries");
    hide("#opt-pareto", method !== "pareto");
    const chartFs = $("#exploreChartEnable")?.closest("fieldset");
    const exploreModeRow = $("#exploreMode")?.closest(".field-row");
    if (method === "pareto") {
      hide("#exploreGroupedBlock", false);
      hide("#exploreRawBlock", true);
      if (chartFs) chartFs.hidden = true;
      if (exploreModeRow) exploreModeRow.hidden = true;
    } else {
      if (chartFs) chartFs.hidden = false;
      if (exploreModeRow) exploreModeRow.hidden = false;
    }
    hide("#opt-columns", !["statistics", "anomalies", "compare"].includes(method));
    hide("#opt-kpi-agg-list", method !== "kpis");
    hide("#opt-corr-method", method !== "correlations");
    hide("#opt-contamination", method !== "anomalies");
    hide("#opt-forecast", method !== "forecast");
    hide("#opt-compare", method !== "compare");
    hide("#opt-nl-query", method !== "nl-query");
    hide("#opt-ai", method !== "ai");
    hide("#opt-sql", method !== "sql");
    if (method === "explore") syncExploreModeUi();
    if (method === "ai") loadAiModels();
    $$("#analysisMethodGroups .method-chip").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.method === method);
    });
  };

  $("#analysisMethodGroups")?.addEventListener("click", (e) => {
    if (e.target.closest("[data-help]")) return;
    const chip = e.target.closest(".method-chip");
    if (!chip || !select) return;
    select.value = chip.dataset.method;
    select.dispatchEvent(new Event("change"));
  });

  select.addEventListener("change", sync);
  contamination?.addEventListener("input", () => {
    if (out) out.textContent = Number(contamination.value).toFixed(2);
  });
  $("#selectAllColumns")?.addEventListener("click", () => {
    const boxes = $$('#columnPicker input[name="column"]');
    const allChecked = boxes.length && boxes.every((b) => b.checked);
    boxes.forEach((b) => {
      b.checked = !allChecked;
    });
  });
  sync();
}

export async function runAnalysis(form) {
  const fd = new FormData(form);
  const datasetId = ensureActiveDataset();
  const method = fd.get("method");
  const columns = selectedColumns();
  const filters = analysisFiltersPayload();

  let path = "";
  let options = { method: "POST" };

  switch (method) {
    case "explore": {
      const mode = String(fd.get("explore_mode") || "grouped");
      const groupBy = $$('#analysisGroupPicker input[name="analysis_group_by"]:checked').map((el) => el.value);
      const aggregations = collectAnalysisAggregations("#analysisAggList");
      const exploreColumns = $$('#exploreColumnPicker input[name="explore_column"]:checked').map((el) => el.value);
      if (mode === "grouped" && !groupBy.length) {
        throw new Error("Выберите хотя бы одно поле группировки");
      }
      const chartEnabled = fd.get("explore_chart_enable") === "on";
      path = `/analysis/explore/${datasetId}`;
      options.json = {
        mode,
        filters,
        group_by: groupBy,
        aggregations,
        columns: exploreColumns,
        sort_by: String(fd.get("explore_sort_by") || "") || null,
        sort_dir: String(fd.get("explore_sort_dir") || "asc"),
        limit: Number(fd.get("explore_limit") || 200),
        chart: chartEnabled
          ? {
              enabled: true,
              type: String(fd.get("explore_chart_type") || "bar"),
              label_column: String(fd.get("explore_chart_label") || "") || null,
              value_column: String(fd.get("explore_chart_value") || "") || null,
              top_n: Number(fd.get("explore_chart_top_n") || 20),
            }
          : { enabled: false },
      };
      break;
    }
    case "timeseries": {
      const dateCol = fd.get("timeseries_date_col");
      const metrics = $$('#timeseriesMetricPicker input[name="timeseries_metric"]:checked').map(
        (el) => el.value
      );
      if (!dateCol) throw new Error("Выберите колонку даты");
      if (!metrics.length) throw new Error("Выберите хотя бы одну метрику");
      path = `/analysis/timeseries/${datasetId}`;
      options.json = {
        date_col: String(dateCol),
        metrics,
        granularity: String(fd.get("timeseries_granularity") || "day"),
        agg: String(fd.get("timeseries_agg") || "sum"),
        filters,
        limit: Number(fd.get("timeseries_limit") || 500),
      };
      break;
    }
    case "pareto": {
      const groupBy = $$('#analysisGroupPicker input[name="analysis_group_by"]:checked').map((el) => el.value);
      const metric = String(fd.get("pareto_metric") || "");
      if (!groupBy.length) throw new Error("Выберите поле группировки");
      if (!metric) throw new Error("Выберите метрику Pareto");
      path = `/analysis/pareto/${datasetId}`;
      options.json = {
        group_by: groupBy,
        metric,
        agg: String(fd.get("pareto_agg") || "sum"),
        top_n: Number(fd.get("pareto_top_n") || 20),
        filters,
      };
      break;
    }
    case "statistics": {
      path = `/analysis/statistics/${datasetId}`;
      options.json = { columns, filters };
      break;
    }
    case "correlations":
      path = `/analysis/correlations/${datasetId}`;
      options.json = {
        method: String(fd.get("corr_method") || "pearson"),
        filters,
      };
      break;
    case "anomalies":
      if (!columns.length) throw new Error("Выберите хотя бы одну колонку");
      path = `/analysis/anomalies/${datasetId}?contamination=${encodeURIComponent(fd.get("contamination"))}`;
      options.json = { columns, filters };
      break;
    case "forecast": {
      const dateCol = fd.get("date_col");
      const targetCol = fd.get("target_col");
      if (!dateCol || !targetCol) {
        throw new Error("Выберите колонки даты и цели");
      }
      path =
        `/analysis/forecast/${datasetId}?` +
        new URLSearchParams({
          date_col: String(dateCol),
          target_col: String(targetCol),
          periods: String(fd.get("periods") || 30),
        });
      break;
    }
    case "kpis": {
      const aggs = collectAnalysisAggregations("#analysisKpiAggList");
      if (!aggs.length) throw new Error("Добавьте хотя бы одну KPI-агрегацию (поле + тип)");
      path = `/analysis/kpis/${datasetId}`;
      options.json = {
        definitions: Object.fromEntries(aggs.map((a) => [a.column, { agg: a.agg }])),
        filters,
      };
      break;
    }
    case "compare": {
      const dateCol = fd.get("compare_date_col");
      const aFrom = fd.get("period_a_from");
      const aTo = fd.get("period_a_to");
      const bFrom = fd.get("period_b_from");
      const bTo = fd.get("period_b_to");
      if (!dateCol || !aFrom || !aTo || !bFrom || !bTo) {
        throw new Error("Заполните колонку даты и оба периода");
      }
      path = `/analysis/compare/${datasetId}`;
      options.json = {
        date_col: String(dateCol),
        period_a: { from: String(aFrom), to: String(aTo) },
        period_b: { from: String(bFrom), to: String(bTo) },
        metrics: columns.length ? columns : null,
      };
      break;
    }
    case "nl-query": {
      const question = String(fd.get("nl_question") || "").trim();
      if (!question) throw new Error("Введите вопрос к данным");
      if (fd.get("nl_unified_knowledge") === "on" || $("#nlUnifiedKnowledge")?.checked) {
        path = `/analysis/unified-ask/${datasetId}`;
        options.json = {
          question,
          include_knowledge: true,
          include_table_query: true,
          save_report: false,
        };
        options.timeoutMs = 900000;
        break;
      }
      path = `/analysis/nl-query/${datasetId}`;
      options.json = { question };
      options.timeoutMs = 900000;
      break;
    }
    case "ai": {
      const question = String(fd.get("question") || "").trim() || null;
      if (fd.get("ai_unified_knowledge") === "on" || $("#aiUnifiedKnowledge")?.checked) {
        if (!question) throw new Error("Введите вопрос для сквозного анализа");
        path = `/analysis/unified-ask/${datasetId}`;
        options.json = {
          question,
          include_knowledge: true,
          include_table_query: true,
          save_report: true,
        };
        options.timeoutMs = 900000;
        break;
      }
      path = `/analysis/ai/analyze/${datasetId}`;
      const modelPath = String(fd.get("ai_model_path") || "").trim();
      options.json = {
        question,
        save_report: true,
        background: true,
        filters,
        group_by: $$('#analysisGroupPicker input[name="analysis_group_by"]:checked').map((el) => el.value),
        aggregations: collectAnalysisAggregations("#analysisAggList"),
        model_path: modelPath || null,
      };
      options.timeoutMs = 60000;
      break;
    }
    case "sql": {
      const sql = String(fd.get("sql_query") || "").trim();
      if (!sql) throw new Error("Введите SQL-запрос");
      const tables = [{ alias: "ds", dataset_id: datasetId }];
      const alias2 = String(fd.get("sql_alias2") || "").trim();
      const ds2 = Number(fd.get("sql_dataset2") || 0);
      if (alias2 && ds2) tables.push({ alias: alias2, dataset_id: ds2 });
      path = "/analysis/sql";
      options.json = { sql, tables, limit: 500 };
      break;
    }
    default:
      throw new Error("Неизвестный метод");
  }

  return api(path, options);
}

export function createKpiAggRow() {
  const cols = state.columns.filter((c) => c.kind === "number");
  const aggs = EXPORT_AGG_OPS.filter((o) => o.value !== "n_unique").map(
    (o) => `<option value="${o.value}">${escapeHtml(o.label)}</option>`
  ).join("");
  return `
    <div class="export-agg-row">
      <select name="agg_column">${exportColumnOptions(cols, true)}</select>
      <select name="agg_func">${aggs}</select>
      <input type="text" name="agg_alias" placeholder="Псевдоним (опц.)" />
      <button type="button" class="btn-sm btn-danger" data-remove-agg aria-label="Удалить">×</button>
    </div>`;
}

export async function pollAiJob(jobId, outEl) {
  const start = Date.now();
  const maxWaitMs = 900000;
  for (;;) {
    const resp = await api(`/jobs/runs/${encodeURIComponent(jobId)}`, { timeoutMs: 60000 });
    const run = resp?.data || {};
    const elapsed = Math.floor((Date.now() - start) / 1000);
    if (run.status === "queued") {
      setResultMessage(
        outEl,
        `AI-анализ поставлен в очередь… ${elapsed} с. Первая загрузка модели может занять 1–3 мин.`
      );
    } else if (run.status === "running") {
      setResultMessage(
        outEl,
        `AI-анализ выполняется (модель + генерация)… ${elapsed} с. Не закрывайте вкладку.`
      );
    } else if (run.status === "completed") {
      return run.result || {};
    } else if (run.status === "failed") {
      throw new Error(run.error || "AI-анализ завершился с ошибкой");
    }
    if (Date.now() - start > maxWaitMs) {
      throw new Error(
        "Превышено время ожидания AI-анализа. Увеличьте LLM_TIMEOUT в .env или выберите меньшую модель."
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

export async function refreshAiHealth(hintEl) {
  const hint = hintEl || $("#aiHealthHint");
  if (!hint) return;
  try {
    const data = await api("/analysis/ai/health", { timeoutMs: 10000 });
    const info = data?.data || {};
    if (info.ok) {
      const extra = info.message ? ` · ${info.message}` : "";
      hint.textContent = `LLM: ${info.backend || "local"} · ${info.model || "model"} · ${info.device || "cpu"}${info.cuda_device_name ? ` · ${info.cuda_device_name}` : ""}${extra}`;
      hint.classList.add("is-ok");
      hint.classList.remove("is-bad");
    } else {
      hint.textContent = `LLM недоступна: ${info.error || "ошибка"}`;
      hint.classList.add("is-bad");
      hint.classList.remove("is-ok");
    }
  } catch (err) {
    hint.textContent = `LLM недоступна: ${err.message}`;
    hint.classList.add("is-bad");
    hint.classList.remove("is-ok");
  }
}

export function bindAnalysisColumnsLoaded() {
  document.addEventListener("quart:columns-loaded", (e) => {
    renderAnalysisExplorePickers(e.detail.columns || []);
  });
}

export function setupAnalysis(deps = {}) {
  const {
    loadReports = loadReportsDefault,
    listHasRows = () => false,
    setupFilterList = () => {},
  } = deps;
  return setupAnalysisPanel({ loadReports, listHasRows, setupFilterList });
}

function setupAnalysisPanel({ loadReports, listHasRows, setupFilterList }) {
  initHelpModal();

  $("#analysisForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = $("#analysisOutput");
    setResultMessage(out, "Выполнение…");
    try {
      const fd = new FormData(e.target);
      const method = fd.get("method");
      if (method === "ai" || method === "nl-query") {
        setResultMessage(
          out,
          method === "ai"
            ? "AI-анализ: загрузка модели и генерация текста… Первая загрузка GGUF может занять 1–3 мин."
            : "NL-запрос: LLM строит план и выполняет Polars-запрос…"
        );
      }
      const data = await runAnalysis(e.target);
      saveFilters("analysis");
      if (method === "ai" && data?.data?.job_id) {
        const result = await pollAiJob(data.data.job_id, out);
        renderAnalysisResult(out, { data: result });
        if (result?.report_id) await loadReports();
      } else {
        renderAnalysisResult(out, data);
        if (data?.data?.report_id) await loadReports();
      }
      toast("Анализ завершён");
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

  refreshAiHealth();
  loadAiModels();

  setupFilterList(
    "#analysisFilterList",
    "#addAnalysisFilter",
    "Нажмите «Добавить фильтр» для условия по колонке",
    "analysis"
  );

  $("#exploreMode")?.addEventListener("change", syncExploreModeUi);
  $("#exploreChartEnable")?.addEventListener("change", (e) => {
    const opts = $("#exploreChartOptions");
    if (opts) opts.hidden = !e.target.checked;
  });

  $("#addAnalysisAgg")?.addEventListener("click", () => {
    const list = $("#analysisAggList");
    const empty = list?.querySelector(".column-picker-empty");
    if (empty) empty.remove();
    list?.insertAdjacentHTML("beforeend", createExportAggRow());
  });

  $("#addKpiAgg")?.addEventListener("click", () => {
    const list = $("#analysisKpiAggList");
    const empty = list?.querySelector(".column-picker-empty");
    if (empty) empty.remove();
    list?.insertAdjacentHTML("beforeend", createKpiAggRow());
  });

  const bindAggListRemove = (listId) => {
    $(listId)?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove-agg]");
      if (!btn) return;
      btn.closest(".export-agg-row")?.remove();
      const list = $(listId);
      if (list && !listHasRows(listId, ".export-agg-row")) {
        list.innerHTML = `<p class="column-picker-empty">${
          listId === "#analysisKpiAggList"
            ? "Добавьте числовое поле и тип агрегации"
            : "Добавьте поле и тип агрегации (sum, mean, min, max, count, n_unique)"
        }</p>`;
      }
    });
  };
  bindAggListRemove("#analysisAggList");
  bindAggListRemove("#analysisKpiAggList");

  $("#clearAnalysisGroupBy")?.addEventListener("click", () => {
    $$('#analysisGroupPicker input[name="analysis_group_by"]').forEach((el) => {
      el.checked = false;
    });
  });
  $("#selectAllExploreColumns")?.addEventListener("click", () => {
    const boxes = $$('#exploreColumnPicker input[name="explore_column"]');
    const all = boxes.length && boxes.every((b) => b.checked);
    boxes.forEach((b) => {
      b.checked = !all;
    });
  });

}
