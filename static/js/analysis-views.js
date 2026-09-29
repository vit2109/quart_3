/** Специализированные представления результатов анализа. */

(function () {
  const q = () => window.__quart || {};
  const escapeHtml = (str) => q().escapeHtml?.(str) ?? String(str);
  const formatCell = (v) => q().formatCell?.(v) ?? String(v ?? "—");

  function corrColor(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "transparent";
    const v = Math.max(-1, Math.min(1, value));
    if (v >= 0) {
      const alpha = 0.15 + v * 0.55;
      return `rgba(15, 118, 110, ${alpha})`;
    }
    const alpha = 0.15 + Math.abs(v) * 0.55;
    return `rgba(185, 28, 28, ${alpha})`;
  }

  const CORR_METHOD_LABELS = {
    pearson: "Пирсон (Pearson)",
    spearman: "Спирмен (Spearman)",
    kendall: "Кендалл (Kendall)",
  };

  function corrMethodLabel(method) {
    const key = String(method || "pearson").toLowerCase();
    return CORR_METHOD_LABELS[key] || `${method} (${method})`;
  }

  function chartColors(type, labels, datasetIndex) {
    const palette = [
      "rgba(15,118,110,0.75)",
      "rgba(59,130,246,0.75)",
      "rgba(180,83,9,0.75)",
      "rgba(124,58,237,0.75)",
      "rgba(190,24,93,0.75)",
      "rgba(22,163,74,0.75)",
    ];
    const linePalette = [
      "rgb(15,118,110)",
      "rgb(59,130,246)",
      "rgb(180,83,9)",
      "rgb(124,58,237)",
    ];
    if (type === "pie" || type === "doughnut") {
      return labels.map((_, i) => palette[i % palette.length]);
    }
    if (type === "line") {
      return linePalette[datasetIndex % linePalette.length];
    }
    return palette[datasetIndex % palette.length];
  }

  function renderCorrelationHeatmap(data) {
    const cols = data.columns || Object.keys(data.matrix || {});
    const matrix = data.matrix || {};
    const method = corrMethodLabel(data.method || "pearson");
    if (!cols.length) return `<p class="result-placeholder">Нет данных для корреляций</p>`;

    const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
    const body = cols
      .map((left) => {
        const cells = cols
          .map((right) => {
            const val = matrix[left]?.[right];
            const bg = corrColor(val);
            return `<td class="num" style="background:${bg}">${formatCell(val)}</td>`;
          })
          .join("");
        return `<tr><th>${escapeHtml(left)}</th>${cells}</tr>`;
      })
      .join("");

    return (
      `<p class="result-meta">Матрица корреляций · метод <strong>${escapeHtml(method)}</strong> · зелёный — положительная связь, красный — отрицательная</p>` +
      `<div class="table-scroll"><table class="data-table heatmap-table"><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>`
    );
  }

  function renderCompareView(data) {
    const metrics = data.metrics || [];
    const pa = data.period_a || {};
    const pb = data.period_b || {};
    const meta =
      `<p class="result-meta">Период A: <strong>${escapeHtml(pa.from)} — ${escapeHtml(pa.to)}</strong> (${formatCell(pa.row_count)} строк) · ` +
      `Период B: <strong>${escapeHtml(pb.from)} — ${escapeHtml(pb.to)}</strong> (${formatCell(pb.row_count)} строк)</p>`;

    const cards = metrics
      .map((m) => {
        const d = m.delta || {};
        const sumPct = d.sum_pct;
        const cls =
          sumPct == null ? "" : sumPct > 0 ? "delta-up" : sumPct < 0 ? "delta-down" : "delta-flat";
        const sign = sumPct > 0 ? "+" : "";
        return `
        <article class="kpi-card compare-card">
          <h4>${escapeHtml(m.column)}</h4>
          <div class="compare-values">
            <div><span class="label">A sum</span><strong>${formatCell(m.period_a?.sum)}</strong></div>
            <div><span class="label">B sum</span><strong>${formatCell(m.period_b?.sum)}</strong></div>
          </div>
          <p class="compare-delta ${cls}">Δ sum: ${formatCell(d.sum)} · ${sign}${formatCell(sumPct)}%</p>
          <p class="meta">mean A/B: ${formatCell(m.period_a?.mean)} / ${formatCell(m.period_b?.mean)}</p>
        </article>`;
      })
      .join("");

    const chartId = "compareChart_" + Date.now();
    const chartBlock =
      metrics.length > 0
        ? `<div class="chart-card compact"><h3>Сравнение sum по метрикам</h3><canvas id="${chartId}" height="200"></canvas></div>`
        : "";

    setTimeout(() => {
      if (typeof Chart === "undefined" || !metrics.length) return;
      const canvas = document.getElementById(chartId);
      if (!canvas) return;
      const labels = metrics.map((m) => m.column);
      new Chart(canvas, {
        type: "bar",
        data: {
          labels,
          datasets: [
            { label: "Период A", data: metrics.map((m) => m.period_a?.sum ?? 0), backgroundColor: "rgba(15,118,110,0.7)" },
            { label: "Период B", data: metrics.map((m) => m.period_b?.sum ?? 0), backgroundColor: "rgba(59,130,246,0.7)" },
          ],
        },
        options: { responsive: true, plugins: { legend: { position: "bottom" } } },
      });
      (window.__quartCharts = window.__quartCharts || []).push(
        Chart.getChart(canvas)
      );
    }, 50);

    return meta + `<div class="kpi-grid">${cards}</div>` + chartBlock;
  }

  function renderKpiCards(data) {
    const kpis = data.kpis || {};
    const entries = Object.entries(kpis);
    if (!entries.length) return `<p class="result-placeholder">KPI не рассчитаны</p>`;
    return (
      `<div class="kpi-grid">` +
      entries
        .map(([name, meta]) => {
          const err = meta.error;
          return `
          <article class="kpi-card">
            <p class="kpi-label">${escapeHtml(name)}</p>
            <p class="kpi-value">${err ? escapeHtml(err) : formatCell(meta.value)}</p>
            <p class="meta">${escapeHtml(meta.agg || "—")}</p>
          </article>`;
        })
        .join("") +
      `</div>`
    );
  }

  function renderNlQueryView(data, renderTableBlock) {
    const plan = data.plan || {};
    const rows = data.rows || [];
    const cols = data.columns || (rows[0] ? Object.keys(rows[0]) : []);
    const planHtml = escapeHtml(JSON.stringify(plan, null, 2));
    let table = "";
    if (rows.length && renderTableBlock) {
      table = renderTableBlock(
        `Результат (${formatCell(data.row_count)} строк)`,
        cols,
        rows
      );
    } else {
      table = `<p class="result-placeholder">Запрос не вернул строк</p>`;
    }
    return (
      `<p class="result-meta">Вопрос: <strong>${escapeHtml(data.question || "")}</strong></p>` +
      (data.explanation
        ? `<p class="result-meta">План: ${escapeHtml(data.explanation)}</p>`
        : "") +
      table +
      `<details class="search-raw-details"><summary>JSON-план запроса</summary><pre class="code-block">${planHtml}</pre></details>`
    );
  }

  function renderForecastChart(data, renderTableBlock) {
    const points = data.forecast || [];
    const chartId = "forecastChart_" + Date.now();
    let html =
      `<p class="result-meta">Прогноз: <strong>${escapeHtml(data.target_col || "")}</strong> · ${escapeHtml(data.method || "baseline_drift")}</p>`;
    if (points.length) {
      html += `<div class="chart-card compact"><canvas id="${chartId}" height="200"></canvas></div>`;
      if (renderTableBlock) {
        html += renderTableBlock("Таблица прогноза", ["step", "yhat", "baseline_mean"], points);
      }
      setTimeout(() => {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById(chartId);
        if (!canvas) return;
        new Chart(canvas, {
          type: "line",
          data: {
            labels: points.map((p) => String(p.step)),
            datasets: [
              {
                label: "yhat",
                data: points.map((p) => p.yhat),
                borderColor: "rgb(15,118,110)",
                tension: 0.2,
              },
            ],
          },
          options: { responsive: true, plugins: { legend: { display: false } } },
        });
        (window.__quartCharts = window.__quartCharts || []).push(Chart.getChart(canvas));
      }, 50);
    }
    return html;
  }

  function renderExploreView(data, renderTableBlock) {
    const mode = data.mode || "grouped";
    const meta =
      `<p class="result-meta">Режим: <strong>${escapeHtml(mode)}</strong> · ` +
      `строк: <strong>${formatCell(data.returned_rows)}</strong> из ${formatCell(data.total_rows)}` +
      (data.filtered_rows != null
        ? ` · после фильтров: ${formatCell(data.filtered_rows)} из ${formatCell(data.source_rows)}`
        : "") +
      (data.group_by?.length ? ` · группировка: ${escapeHtml(data.group_by.join(", "))}` : "") +
      `</p>`;

    let table = "";
    const rows = data.rows || [];
    const cols = data.columns || (rows[0] ? Object.keys(rows[0]) : []);
    if (rows.length && renderTableBlock) {
      table = renderTableBlock(`Результат (${formatCell(data.returned_rows)} строк)`, cols, rows);
    } else {
      table = `<p class="result-placeholder">Нет данных по заданным условиям</p>`;
    }

    let chartBlock = "";
    const chart = data.chart;
    if (chart && chart.labels?.length) {
      const chartId = "exploreChart_" + Date.now();
      chartBlock = `<div class="chart-card compact"><h3>${escapeHtml(chart.title || "График")}</h3><canvas id="${chartId}" height="220"></canvas></div>`;
      setTimeout(() => {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById(chartId);
        if (!canvas) return;
        const chartType = chart.type || "bar";
        const cfg = {
          type: chartType,
          data: {
            labels: chart.labels,
            datasets: (chart.datasets || []).map((ds, i) => {
              const colors = chartColors(chartType, chart.labels || [], i);
              const isLine = chartType === "line";
              const isCircular = chartType === "pie" || chartType === "doughnut";
              return {
                label: ds.label || "Значение",
                data: ds.data || [],
                backgroundColor: isCircular ? colors : colors,
                borderColor: isLine ? colors : isCircular ? "#fff" : colors.replace("0.75", "1"),
                borderWidth: isCircular ? 1 : isLine ? 2 : 1,
                tension: 0.2,
              };
            }),
          },
          options: {
            responsive: true,
            indexAxis: chart.index_axis || "x",
            plugins: { legend: { position: "bottom" } },
            scales:
              chartType === "pie" || chartType === "doughnut"
                ? {}
                : { y: { beginAtZero: true } },
          },
        };
        new Chart(canvas, cfg);
        (window.__quartCharts = window.__quartCharts || []).push(Chart.getChart(canvas));
      }, 50);
    }

    return meta + chartBlock + table;
  }

  function renderTimeseriesView(data, renderTableBlock) {
    const meta =
      `<p class="result-meta">Дата: <strong>${escapeHtml(data.date_col || "")}</strong> · ` +
      `гранулярность: <strong>${escapeHtml(data.granularity || "day")}</strong> · ` +
      `агрегация: <strong>${escapeHtml(data.agg || "sum")}</strong> · ` +
      `периодов: <strong>${formatCell((data.periods || []).length)}</strong>` +
      (data.filtered_rows != null
        ? ` · после фильтров: ${formatCell(data.filtered_rows)} из ${formatCell(data.source_rows)}`
        : "") +
      `</p>`;

    let chartBlock = "";
    const chart = data.chart;
    if (chart && chart.labels?.length) {
      const chartId = "timeseriesChart_" + Date.now();
      chartBlock = `<div class="chart-card compact"><h3>${escapeHtml(chart.title || "Динамика")}</h3><canvas id="${chartId}" height="240"></canvas></div>`;
      setTimeout(() => {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById(chartId);
        if (!canvas) return;
        const palette = [
          "rgb(15,118,110)",
          "rgb(59,130,246)",
          "rgb(180,83,9)",
          "rgb(124,58,237)",
          "rgb(190,24,93)",
        ];
        new Chart(canvas, {
          type: chart.type || "line",
          data: {
            labels: chart.labels,
            datasets: (chart.datasets || []).map((ds, i) => ({
              label: ds.label || "Метрика",
              data: ds.data || [],
              borderColor: palette[i % palette.length],
              backgroundColor: palette[i % palette.length].replace("rgb", "rgba").replace(")", ",0.15)"),
              tension: 0.25,
              fill: false,
            })),
          },
          options: {
            responsive: true,
            plugins: { legend: { position: "bottom" } },
            scales: { y: { beginAtZero: true } },
          },
        });
        (window.__quartCharts = window.__quartCharts || []).push(Chart.getChart(canvas));
      }, 50);
    }

    const rows = data.rows || [];
    const cols = rows.length ? Object.keys(rows[0]) : [];
    let table = "";
    if (rows.length && renderTableBlock) {
      table = renderTableBlock(`Таблица (${formatCell(rows.length)} периодов)`, cols, rows);
    } else {
      table = `<p class="result-placeholder">Нет данных для выбранного периода</p>`;
    }

    return meta + chartBlock + table;
  }

  function renderParetoView(data, renderTableBlock) {
    const meta =
      `<p class="result-meta">Метрика: <strong>${escapeHtml(data.metric || "")}</strong> · ` +
      `группировка: <strong>${escapeHtml((data.group_by || []).join(", "))}</strong> · ` +
      `HHI: <strong>${formatCell(data.hhi)}</strong>` +
      (data.filtered_rows != null
        ? ` · после фильтров: ${formatCell(data.filtered_rows)} из ${formatCell(data.source_rows)}`
        : "") +
      `</p>`;

    const insights = data.insights || [];
    const insightsHtml = insights.length
      ? `<ul class="passport-insights">${insights.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
      : "";

    const hhiBlock = `<div class="passport-stats"><div class="passport-stat"><span>Концентрация HHI</span><strong>${formatCell(data.hhi)}</strong></div></div>`;

    let chartBlock = "";
    const chart = data.chart;
    if (chart && chart.labels?.length) {
      const chartId = "paretoChart_" + Date.now();
      chartBlock = `<div class="chart-card compact"><h3>${escapeHtml(chart.title || "Pareto")}</h3><canvas id="${chartId}" height="260"></canvas></div>`;
      setTimeout(() => {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById(chartId);
        if (!canvas) return;
        const barDs = chart.datasets?.[0];
        const lineDs = chart.datasets?.[1];
        new Chart(canvas, {
          data: {
            labels: chart.labels,
            datasets: [
              {
                type: "bar",
                label: barDs?.label || "Значение",
                data: barDs?.data || [],
                backgroundColor: "rgba(15,118,110,0.75)",
                yAxisID: "y",
              },
              {
                type: "line",
                label: lineDs?.label || "Накопленная %",
                data: lineDs?.data || [],
                borderColor: "rgb(180,83,9)",
                tension: 0.2,
                yAxisID: "y1",
              },
            ],
          },
          options: {
            responsive: true,
            plugins: { legend: { position: "bottom" } },
            scales: {
              y: { beginAtZero: true, position: "left" },
              y1: {
                beginAtZero: true,
                max: 100,
                position: "right",
                grid: { drawOnChartArea: false },
              },
            },
          },
        });
        (window.__quartCharts = window.__quartCharts || []).push(Chart.getChart(canvas));
      }, 50);
    }

    const rows = data.rows || [];
    const cols = rows.length ? Object.keys(rows[0]) : [];
    let table = "";
    if (rows.length && renderTableBlock) {
      table = renderTableBlock(`Pareto (${formatCell(rows.length)} групп)`, cols, rows);
    } else {
      table = `<p class="result-placeholder">Нет данных</p>`;
    }

    return meta + hhiBlock + insightsHtml + chartBlock + table;
  }

  window.QuartAnalysisViews = {
    renderCorrelationHeatmap,
    renderCompareView,
    renderKpiCards,
    renderNlQueryView,
    renderForecastChart,
    renderExploreView,
    renderTimeseriesView,
    renderParetoView,
  };
})();
