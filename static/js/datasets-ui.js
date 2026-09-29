/** Панель «Данные»: наборы, паспорт, ETL, join (E22). */

import {
  ACTIVE_DATASET_KEY,
  $,
  $$,
  api,
  ensureActiveDataset,
  escapeHtml,
  formatCell,
  formatSize,
  state,
  toast,
} from "./quart-core.js";
import {
  initPaginatedTables,
  renderQualityResult,
  renderTableBlock,
  setResultMessage,
} from "./render-utils.js";

export function showPanel(name) {
  const aliases = { etl: "datasets", export: "reports", investigate: "analysis" };
  const requested = name;
  name = aliases[name] || name;
  $$(".panel").forEach((panel) => {
    const active = panel.id === `panel-${name}`;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  $$(".nav-link").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.panel === name);
  });
  $$(".workflow-step").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.panel === name);
  });
  const hero = $(".hero");
  if (hero) hero.style.display = "none";
  if (requested === "etl") {
    const etl = $("#etlSection");
    if (etl) etl.open = true;
  }
  if (requested === "export") {
    const exp = $("#exportSection");
    if (exp) exp.open = true;
  }
  document.dispatchEvent(new CustomEvent("quart:panel-shown", { detail: { panel: name } }));
}

export function datasetLabel(id) {
  const d = state.datasetsCache.find((x) => x.id === Number(id));
  if (!d) return id ? `#${id}` : "—";
  return `${d.name || "Набор"} (#${d.id})`;
}

export function updateActiveDatasetLabels() {
  const label = datasetLabel(state.selectedDatasetId);
  $$(".active-dataset-label").forEach((el) => {
    el.textContent = label;
  });
  const meta = $("#globalDatasetMeta");
  if (meta) {
    const d = state.datasetsCache.find((x) => x.id === state.selectedDatasetId);
    meta.textContent = d
      ? `${formatSize(d.size)} · ${d.filename || ""}`
      : state.selectedDatasetId
        ? "Набор не найден в списке"
        : "Выберите или загрузите набор";
  }
  const sel = $("#globalDatasetSelect");
  if (sel && state.selectedDatasetId) {
    sel.value = String(state.selectedDatasetId);
  }
}

export function populateGlobalDatasetSelect(items) {
  const sel = $("#globalDatasetSelect");
  if (!sel) return;
  if (!items.length) {
    sel.innerHTML = `<option value="">— нет наборов —</option>`;
    return;
  }
  sel.innerHTML = items
    .map(
      (d) =>
        `<option value="${d.id}">${escapeHtml(d.name || `Набор #${d.id}`)} (#${d.id})</option>`
    )
    .join("");
  if (state.selectedDatasetId && items.some((d) => d.id === state.selectedDatasetId)) {
    sel.value = String(state.selectedDatasetId);
  } else if (items[0]) {
    setSelectedDataset(items[0].id, { skipSelectSync: true });
    sel.value = String(items[0].id);
  }
  updateActiveDatasetLabels();
}

export function setSelectedDataset(id, options = {}) {
  const numId = Number(id);
  if (!numId || Number.isNaN(numId)) return;
  state.selectedDatasetId = numId;
  localStorage.setItem(ACTIVE_DATASET_KEY, String(numId));
  const etl = $("#etlDatasetId");
  const analysis = $("#analysisDatasetId");
  const report = $("#reportDatasetId") || $('#reportForm input[name="dataset_id"]');
  const exportId = $("#exportDatasetId");
  const knowledgeDs = $("#knowledgeDatasetId");
  if (etl) etl.value = numId;
  if (analysis) analysis.value = numId;
  if (report) report.value = numId;
  if (exportId) exportId.value = numId;
  if (knowledgeDs) knowledgeDs.value = numId;
  if (!options.skipSelectSync) {
    const sel = $("#globalDatasetSelect");
    if (sel) sel.value = String(numId);
  }
  updateActiveDatasetLabels();
  state.filterValueSuggestCache.clear();
  loadDatasetColumns(numId);
  loadDatasetPassport(numId);
  document.dispatchEvent(new CustomEvent("quart:dataset-changed", { detail: { id: numId } }));
}

export function renderColumnPicker(columns) {
  const picker = $("#columnPicker");
  if (!picker) return;

  if (!columns.length) {
    picker.innerHTML = `<p class="column-picker-empty">В датасете нет колонок</p>`;
    return;
  }

  picker.innerHTML = columns
    .map(
      (col) => `
      <label class="column-chip">
        <input type="checkbox" name="column" value="${escapeHtml(col.name)}" />
        <span>
          <strong>${escapeHtml(col.name)}</strong>
          <small>${escapeHtml(col.kind)} · ${escapeHtml(col.dtype)}</small>
        </span>
      </label>`
    )
    .join("");
}

export function fillColumnSelect(selectEl, columns, preferredKinds = []) {
  if (!selectEl) return;
  const previous = selectEl.value;
  const ranked = [...columns].sort((a, b) => {
    const aScore = preferredKinds.includes(a.kind) ? 0 : 1;
    const bScore = preferredKinds.includes(b.kind) ? 0 : 1;
    return aScore - bScore;
  });

  selectEl.innerHTML =
    `<option value="">— выберите колонку —</option>` +
    ranked
      .map(
        (col) =>
          `<option value="${escapeHtml(col.name)}">${escapeHtml(col.name)}</option>`
      )
      .join("");

  if (previous && ranked.some((c) => c.name === previous)) {
    selectEl.value = previous;
  } else {
    const preferred = ranked.find((c) => preferredKinds.includes(c.kind));
    if (preferred) selectEl.value = preferred.name;
  }
}

export async function loadDatasetColumns(datasetId) {
  const id = Number(datasetId);
  const picker = $("#columnPicker");
  if (!id || Number.isNaN(id)) {
    state.columns = [];
    state.columnsDatasetId = null;
    if (picker) {
      picker.innerHTML = `<p class="column-picker-empty">Укажите ID набора данных</p>`;
    }
    return;
  }

  if (picker) {
    picker.innerHTML = `<p class="column-picker-empty">Загрузка колонок…</p>`;
  }

  try {
    const data = await api(`/datasets/${id}/columns`, { timeoutMs: 20000 });
    const columns = data?.data?.columns || [];
    state.columns = columns;
    state.columnsDatasetId = id;
    renderColumnPicker(columns);
    fillColumnSelect($("#dateColSelect"), columns, ["datetime", "string"]);
    fillColumnSelect($("#compareDateColSelect"), columns, ["datetime", "string"]);
    fillColumnSelect($("#targetColSelect"), columns, ["number"]);
    fillColumnSelect($("#timeseriesDateColSelect"), columns, ["datetime", "string"]);
    document.dispatchEvent(new CustomEvent("quart:columns-loaded", { detail: { columns } }));
  } catch (err) {
    state.columns = [];
    state.columnsDatasetId = null;
    if (picker) {
      picker.innerHTML = `<p class="column-picker-error">${escapeHtml(err.message)}</p>`;
    }
    fillColumnSelect($("#dateColSelect"), []);
    fillColumnSelect($("#compareDateColSelect"), []);
    fillColumnSelect($("#targetColSelect"), []);
    fillColumnSelect($("#timeseriesDateColSelect"), []);
    document.dispatchEvent(new CustomEvent('quart:columns-loaded', { detail: { columns: [] } }));
  }
}

export async function loadDatasetPassport(datasetId) {
  const panel = $("#datasetPassport");
  const body = $("#datasetPassportBody");
  const meta = $("#passportMeta");
  const id = Number(datasetId);
  if (!panel || !body) return;
  if (!id || Number.isNaN(id)) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  body.innerHTML = `<p class="result-placeholder">Загрузка паспорта…</p>`;
  if (meta) meta.textContent = "";
  try {
    const data = await api(`/datasets/${id}/profile?sample=50`, { timeoutMs: 30000 });
    renderDatasetPassport(body, meta, data?.data || data);
  } catch (err) {
    body.innerHTML = `<p class="result-error">${escapeHtml(err.message)}</p>`;
  }
}

export function renderDatasetPassport(bodyEl, metaEl, profile) {
  if (!profile || !bodyEl) return;
  if (metaEl) {
    metaEl.textContent = `${formatCell(profile.rows)} строк · ${formatCell(profile.columns_count)} колонок`;
  }
  const insights = (profile.insights || [])
    .map((i) => `<li>${escapeHtml(i)}</li>`)
    .join("");
  const colRows = (profile.columns || []).map((c) => ({
    Колонка: c.name,
    Тип: c.kind,
    Пропуски: c.missing_pct != null ? `${c.missing_pct}%` : c.missing,
    Уникальных: c.unique,
    Min: c.min ?? "—",
    Max: c.max ?? "—",
  }));
  const sampleCols = profile.sample_columns || [];
  const sampleRows = profile.sample_rows || [];

  let lineageHtml = "";
  const lin = profile.lineage;
  if (lin && typeof lin === "object") {
    const parts = [];
    if (lin.type === "etl" && lin.source_dataset_ids?.length) {
      parts.push(
        `ETL из набора #${lin.source_dataset_ids.join(", #")}` +
          (lin.rows_before != null ? ` · ${lin.rows_before} → ${lin.rows_after} строк` : "")
      );
    } else if (lin.type === "join" || lin.left_id) {
      parts.push(
        `Join: #${lin.left_id || "?"} × #${lin.right_id || "?"} (${escapeHtml(lin.how || "inner")}) → ${escapeHtml(formatCell(lin.joined_rows))} строк`
      );
    }
    if (lin.steps?.length) parts.push(`Шаги: ${escapeHtml(lin.steps.join(", "))}`);
    if (parts.length) {
      lineageHtml = `<div class="passport-lineage"><strong>Происхождение:</strong> ${parts.join(" · ")}</div>`;
    }
  }

  const kDocs = profile.knowledge_documents || [];
  const knowledgeHtml = kDocs.length
    ? `<div class="passport-knowledge"><strong>База знаний:</strong><ul class="link-list">${kDocs
        .map(
          (d) =>
            `<li><button type="button" class="btn-link" data-open-knowledge-doc="${escapeHtml(d.id)}">${escapeHtml(d.title || d.id)}</button> · ${escapeHtml(formatCell(d.chunk_count))} фр.</li>`
        )
        .join("")}</ul></div>`
    : `<div class="passport-knowledge"><button type="button" class="btn-sm btn-ghost" data-index-to-knowledge="${profile.dataset_id}">+ Индексировать в базу знаний</button></div>`;

  bodyEl.innerHTML =
    `<div class="passport-stats">
      <div class="passport-stat"><span>Строк</span><strong>${escapeHtml(formatCell(profile.rows))}</strong></div>
      <div class="passport-stat"><span>Заполненность</span><strong>${escapeHtml(formatCell(Math.round((profile.completeness || 1) * 1000) / 10))}%</strong></div>
      <div class="passport-stat"><span>Дубликаты</span><strong>${escapeHtml(formatCell(profile.duplicate_rows))}</strong></div>
    </div>` +
    lineageHtml +
    knowledgeHtml +
    (insights ? `<ul class="passport-insights">${insights}</ul>` : "") +
    `<div class="passport-columns">${renderTableBlock("Профиль колонок", ["Колонка", "Тип", "Пропуски", "Уникальных", "Min", "Max"], colRows, { collapsible: true, defaultOpen: false, section: "profile-cols" })}</div>` +
    renderTableBlock(`Пример данных (${sampleRows.length} строк)`, sampleCols, sampleRows, {
      collapsible: true,
      defaultOpen: true,
      section: "profile-sample",
    });

  initPaginatedTables(bodyEl);

  bodyEl.querySelectorAll("[data-open-knowledge-doc]").forEach((btn) => {
    btn.addEventListener("click", () => {
      showPanel("knowledge");
      document.dispatchEvent(
        new CustomEvent("quart:highlight-knowledge-doc", { detail: { documentId: btn.dataset.openKnowledgeDoc } })
      );
    });
  });
  bodyEl.querySelectorAll("[data-index-to-knowledge]").forEach((btn) => {
    btn.addEventListener("click", () => {
      showPanel("knowledge");
      document.dispatchEvent(
        new CustomEvent("quart:index-dataset-knowledge", { detail: { datasetId: Number(btn.dataset.indexToKnowledge) } })
      );
    });
  });
}

export function selectedColumns() {
  return $$('#columnPicker input[name="column"]:checked').map((el) => el.value);
}

export async function loadDatasets() {
  const list = $("#datasetList");
  const count = $("#datasetCount");
  list.innerHTML = `<li class="empty">Загрузка…</li>`;
  try {
    const data = await api("/datasets/", { timeoutMs: 15000 });
    const items = data?.data || [];
    state.datasetsCache = items;
    count.textContent = String(items.length);
    populateGlobalDatasetSelect(items);
    populateJoinSelects(items);
    if (!items.length) {
      list.innerHTML = `<li class="empty">Пока нет наборов — загрузите первый файл</li>`;
      return items;
    }
    list.innerHTML = items
      .map(
        (d) => `
        <li class="${state.selectedDatasetId === d.id ? "is-selected" : ""}">
          <div>
            <strong>${escapeHtml(d.name || `Dataset #${d.id}`)}</strong>
            <div class="meta">ID ${d.id} · ${escapeHtml(d.filename || "")} · ${formatSize(d.size)}${d.description ? ` · ${escapeHtml(d.description)}` : ""}</div>
          </div>
          <div class="list-actions">
            <button type="button" class="btn-sm" data-select="${d.id}">Выбрать</button>
            <button type="button" class="btn-sm btn-ghost" data-edit="${d.id}">Изменить</button>
            <button type="button" class="btn-sm btn-danger" data-delete="${d.id}">Удалить</button>
          </div>
        </li>`
      )
      .join("");
    return items;
  } catch (err) {
    list.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
    return [];
  }
}

export function populateJoinSelects(items) {
  const opts =
    (items || state.datasetsCache || [])
      .map(
        (d) =>
          `<option value="${d.id}">${escapeHtml(d.name || `Набор #${d.id}`)} (#${d.id})</option>`
      )
      .join("") || `<option value="">— нет наборов —</option>`;
  const left = $("#joinLeftId");
  const right = $("#joinRightId");
  if (left) {
    left.innerHTML = opts;
    if (state.selectedDatasetId) left.value = String(state.selectedDatasetId);
  }
  if (right) right.innerHTML = opts;
}

export function setupDropzone() {
  const zone = $("#dropzone");
  const input = $("#fileInput");
  const nameEl = $("#fileName");

  const setFile = (file) => {
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    nameEl.textContent = file.name;
  };

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    if (input.files?.[0]) nameEl.textContent = input.files[0].name;
  });

  ["dragenter", "dragover"].forEach((ev) => {
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.add("is-dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.remove("is-dragover");
    });
  });
  zone.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    setFile(file);
  });
}

export function openEditDatasetModal(dataset) {
  const modal = $("#editDatasetModal");
  if (!modal || !dataset) return;
  $("#editDatasetId").value = dataset.id;
  $("#editDatasetName").value = dataset.name || "";
  $("#editDatasetDescription").value = dataset.description || "";
  const fileInput = $("#editDatasetFile");
  if (fileInput) fileInput.value = "";
  modal.showModal();
}

export function setupDatasets() {
  $("#uploadForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const file = $("#fileInput").files?.[0];
    if (!file) {
      toast("Выберите файл", true);
      return;
    }
    const body = new FormData();
    body.append("file", file);
    const name = form.name.value.trim();
    const description = form.description.value.trim();
    if (name) body.append("name", name);
    if (description) body.append("description", description);

    const btn = $("#uploadBtn");
    btn.disabled = true;
    try {
      const data = await api("/datasets/upload", { method: "POST", body });
      const created = data?.data;
      if (created?.id) setSelectedDataset(created.id);
      toast(created?.name ? `Загружено: ${created.name}` : "Файл загружен");
      form.reset();
      $("#fileName").textContent = "Файл не выбран";
      await loadDatasets();
    } catch (err) {
      const dup = err.details?.existing_id;
      if (dup || err.message.includes("identical content") || err.message.includes("Duplicate")) {
        toast(dup ? `Файл уже загружен как набор #${dup}` : "Этот файл уже загружен", true);
      } else {
        toast(err.message, true);
      }
    } finally {
      btn.disabled = false;
    }
  });

  $("#refreshDatasets").addEventListener("click", () => loadDatasets());

  $("#datasetList").addEventListener("click", async (e) => {
    const selectBtn = e.target.closest("[data-select]");
    if (selectBtn) {
      setSelectedDataset(Number(selectBtn.dataset.select));
      await loadDatasets();
      toast(`Выбран набор #${selectBtn.dataset.select}`);
      return;
    }

    const editBtn = e.target.closest("[data-edit]");
    if (editBtn) {
      try {
        const data = await api(`/datasets/${editBtn.dataset.edit}`);
        openEditDatasetModal(data?.data || data);
      } catch (err) {
        toast(err.message, true);
      }
      return;
    }

    const deleteBtn = e.target.closest("[data-delete]");
    if (deleteBtn) {
      const id = Number(deleteBtn.dataset.delete);
      if (!confirm(`Удалить набор #${id}? Файл будет удалён безвозвратно.`)) return;
      try {
        await api(`/datasets/${id}`, { method: "DELETE" });
        toast(`Набор #${id} удалён`);
        if (state.selectedDatasetId === id) {
          state.selectedDatasetId = null;
        }
        await loadDatasets();
      } catch (err) {
        toast(err.message, true);
      }
    }
  });

  const editModal = $("#editDatasetModal");
  $("#closeEditModal")?.addEventListener("click", () => editModal?.close());
  $("#cancelEditModal")?.addEventListener("click", () => editModal?.close());

  $("#editDatasetForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = Number($("#editDatasetId").value);
    const body = new FormData();
    body.append("name", $("#editDatasetName").value.trim());
    body.append("description", $("#editDatasetDescription").value.trim());
    const file = $("#editDatasetFile").files?.[0];
    if (file) body.append("file", file);

    try {
      const data = await api(`/datasets/${id}`, { method: "PUT", body });
      editModal?.close();
      toast(`Набор #${id} обновлён`);
      if (data?.data?.id) setSelectedDataset(data.data.id);
      await loadDatasets();
    } catch (err) {
      if (err.message.includes("identical content") || err.message.includes("Duplicate")) {
        toast("Файл с таким содержимым уже существует", true);
      } else {
        toast(err.message, true);
      }
    }
  });

  $("#joinForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      left_id: Number(fd.get("left_id")),
      right_id: Number(fd.get("right_id")),
      left_on: [String(fd.get("left_on") || "").trim()],
      right_on: [String(fd.get("right_on") || "").trim()],
      how: String(fd.get("how") || "inner"),
      name: String(fd.get("name") || "").trim() || null,
    };
    const out = $("#joinOutput");
    setResultMessage(out, "Join и сохранение…");
    try {
      const data = await api("/datasets/join", { method: "POST", json: body });
      const ds = data?.data?.dataset || data?.data;
      out.innerHTML =
        `<p class="result-meta">Создан набор #${escapeHtml(formatCell(ds?.id))} · ${escapeHtml(formatCell(data?.data?.joined_rows))} строк</p>` +
        renderTableBlock(
          "Колонки",
          ["Колонка"],
          (data?.data?.joined_columns || []).map((c) => ({ Колонка: c }))
        );
      if (ds?.id) setSelectedDataset(ds.id);
      await loadDatasets();
      toast("Join сохранён");
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

  $("#previewJoin")?.addEventListener("click", async () => {
    const fd = new FormData($("#joinForm"));
    const body = {
      left_id: Number(fd.get("left_id")),
      right_id: Number(fd.get("right_id")),
      left_on: [String(fd.get("left_on") || "").trim()],
      right_on: [String(fd.get("right_on") || "").trim()],
      how: String(fd.get("how") || "inner"),
      sample: 15,
    };
    const out = $("#joinOutput");
    setResultMessage(out, "Preview join…");
    try {
      const data = await api("/datasets/join/preview", { method: "POST", json: body });
      const p = data?.data || data;
      out.innerHTML =
        `<p class="result-meta">Join preview: ${escapeHtml(formatCell(p.left_rows))} × ${escapeHtml(formatCell(p.right_rows))} → <strong>${escapeHtml(formatCell(p.joined_rows))}</strong> строк</p>` +
        renderTableBlock(
          "Sample",
          p.sample_columns || [],
          p.sample_rows || []
        );
    } catch (err) {
      setResultMessage(out, err.message, true);
    }
  });
}

export function setupEtl() {
  $("#etlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    let datasetId;
    try {
      datasetId = ensureActiveDataset();
    } catch (err) {
      toast(err.message, true);
      return;
    }
    const config = {
      dataset_id: datasetId,
      clean_missing: fd.get("clean_missing") === "on",
      missing_strategy: String(fd.get("missing_strategy") || "drop"),
      remove_duplicates: fd.get("remove_duplicates") === "on",
      normalize_strings: fd.get("normalize_strings") === "on",
      remove_outliers: fd.get("remove_outliers") === "on",
    };
    const out = $("#etlOutput");
    setResultMessage(out, "Запуск ETL…");
    try {
      const data = await api(`/etl/process/${datasetId}`, {
        method: "POST",
        json: config,
      });
      const rows = Object.entries(data.config || config).map(([k, v]) => ({
        Параметр: k,
        Значение: String(v),
      }));
      out.innerHTML =
        `<p class="result-meta">${escapeHtml(data.message || "ETL завершён")} · dataset #${datasetId}</p>` +
        renderTableBlock("Параметры ETL", ["Параметр", "Значение"], rows);
      toast("ETL завершён");
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

  $("#checkQuality").addEventListener("click", async () => {
    const datasetId = Number($("#etlDatasetId").value);
    const out = $("#etlOutput");
    setResultMessage(out, "Проверка качества…");
    try {
      const data = await api(`/etl/quality/${datasetId}`);
      renderQualityResult(out, data);
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });

  $("#previewEtl")?.addEventListener("click", async () => {
    const fd = new FormData($("#etlForm"));
    let datasetId;
    try {
      datasetId = ensureActiveDataset();
    } catch (err) {
      toast(err.message, true);
      return;
    }
    const config = {
      dataset_id: datasetId,
      clean_missing: fd.get("clean_missing") === "on",
      missing_strategy: String(fd.get("missing_strategy") || "drop"),
      remove_duplicates: fd.get("remove_duplicates") === "on",
      normalize_strings: fd.get("normalize_strings") === "on",
      remove_outliers: fd.get("remove_outliers") === "on",
    };
    const out = $("#etlOutput");
    setResultMessage(out, "Preview ETL…");
    try {
      const data = await api(`/etl/preview/${datasetId}`, { method: "POST", json: config });
      const p = data?.data || data;
      const rows = [
        { Показатель: "Строк до", Значение: p.rows_before },
        { Показатель: "Строк после", Значение: p.rows_after },
        { Показатель: "Удалено строк", Значение: p.rows_removed },
        { Показатель: "Стратегия пропусков", Значение: p.missing_strategy },
        { Показатель: "Шаги", Значение: (p.steps || []).join(", ") },
      ];
      const changes = (p.sample_changes || []).map((c) => ({
        Строка: c.row,
        Колонка: c.column,
        Было: formatCell(c.before),
        Стало: formatCell(c.after),
      }));
      out.innerHTML =
        `<p class="result-meta">Preview ETL · набор #${datasetId}</p>` +
        renderTableBlock("Итог", ["Показатель", "Значение"], rows) +
        renderTableBlock("Примеры изменённых ячеек", ["Строка", "Колонка", "Было", "Стало"], changes);
      toast("Preview готов");
    } catch (err) {
      setResultMessage(out, err.message, true);
      toast(err.message, true);
    }
  });
}
