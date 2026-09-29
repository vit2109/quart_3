/** База знаний: отдельный модуль UI без изменения логики других вкладок. */

function q() {
  return window.__quart || {};
}

function $(sel, root = document) {
  return root.querySelector(sel);
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setResult(el, message, isError = false) {
  if (!el) return;
  el.innerHTML = `<p class="${isError ? "result-error" : "result-placeholder"}">${escapeHtml(message)}</p>`;
}

async function refreshStats() {
  const box = $("#knowledgeStats");
  if (!box) return;
  try {
    const [statsRes, healthRes] = await Promise.all([
      q().api("/knowledge/stats"),
      q().api("/knowledge/chroma-health").catch(() => null),
    ]);
    const d = statsRes?.data || {};
    const health = healthRes?.data || {};
    const healthLabel =
      health.ok === true
        ? `<span class="health-ok">Chroma: OK</span>`
        : health.ok === false
          ? `<span class="result-error">Chroma: повреждена</span>`
          : "";
    box.innerHTML =
      `<span>Документов: <strong>${d.documents ?? 0}</strong></span>` +
      `<span>Фрагментов: <strong>${d.chunks?.chunks_total ?? 0}</strong></span>` +
      `<span>Векторов: <strong>${d.vector?.vector_count ?? 0}</strong></span>` +
      `<span>Модель: <strong>${escapeHtml(d.embedding_model || "—")}</strong></span>` +
      healthLabel;
  } catch (err) {
    box.innerHTML = `<span class="result-error">${escapeHtml(err.message)}</span>`;
  }
}

async function loadDocuments() {
  const list = $("#knowledgeDocList");
  const filter = $("#knowledgeDocFilter");
  if (!list) return;
  list.innerHTML = `<li class="empty">Загрузка…</li>`;
  try {
    const res = await q().api("/knowledge/documents");
    const items = res?.data || [];
    if (filter) {
      const prev = filter.value;
      filter.innerHTML =
        `<option value="">Все документы</option>` +
        items
          .map(
            (d) =>
              `<option value="${escapeHtml(d.id)}">${escapeHtml(d.title || d.id)} (${d.chunk_count || 0})</option>`
          )
          .join("");
      if (prev) filter.value = prev;
    }
    const searchDoc = $("#knowledgeSearchDoc");
    if (searchDoc) {
      const prev = searchDoc.value;
      searchDoc.innerHTML =
        `<option value="">Во всей базе знаний</option>` +
        items.map((d) => `<option value="${escapeHtml(d.id)}">${escapeHtml(d.title || d.id)}</option>`).join("");
      if (prev) searchDoc.value = prev;
    }
    if (!items.length) {
      list.innerHTML = `<li class="empty">Документов пока нет</li>`;
      return;
    }
    list.innerHTML = items
      .map(
        (d) => {
          const dsId = d.extra?.dataset_id ?? d.dataset_id;
          const dsLink = dsId
            ? `<button type="button" class="btn-sm btn-ghost" data-open-dataset="${escapeHtml(String(dsId))}">Набор #${escapeHtml(String(dsId))}</button>`
            : "";
          return `
      <li>
        <div>
          <strong>${escapeHtml(d.title || d.id)}</strong>
          <div class="meta">${escapeHtml(d.filename || "")} · ${escapeHtml(d.source_type || "")} · фрагментов: ${d.chunk_count || 0}${d.chunk_count === 0 ? " · <span class=\"result-error\">не проиндексирован</span>" : ""}${dsLink ? ` · ${dsLink}` : ""}</div>
        </div>
        <div class="list-actions">
          ${d.chunk_count === 0 ? `<button type="button" class="btn-sm" data-reindex-doc="${escapeHtml(d.id)}">Переиндексировать</button>` : ""}
          <button type="button" class="btn-sm btn-danger" data-del-doc="${escapeHtml(d.id)}">Удалить</button>
        </div>
      </li>`;
        }
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
  }
}

async function loadChunks() {
  const list = $("#knowledgeChunkList");
  const count = $("#knowledgeChunkCount");
  const docId = $("#knowledgeDocFilter")?.value || "";
  const query = $("#knowledgeChunkQuery")?.value?.trim() || "";
  if (!list) return;
  list.innerHTML = `<li class="empty">Загрузка…</li>`;
  try {
    const params = new URLSearchParams({ limit: "30", offset: "0" });
    if (docId) params.set("document_id", docId);
    if (query) params.set("q", query);
    const res = await q().api(`/knowledge/chunks?${params}`);
    const data = res?.data || {};
    const items = data.items || [];
    if (count) count.textContent = String(data.total ?? items.length);
    if (!items.length) {
      list.innerHTML = `<li class="empty">Фрагменты не найдены</li>`;
      return;
    }
    list.innerHTML = items
      .map(
        (c) => `
      <li>
        <div>
          <strong>${escapeHtml(c.document_title || c.id)}</strong>
          <div class="meta">#${escapeHtml(c.id)} · ${c.char_count || 0} симв.</div>
          <p class="chunk-preview">${escapeHtml((c.text || "").slice(0, 180))}${(c.text || "").length > 180 ? "…" : ""}</p>
        </div>
        <div class="list-actions">
          <button type="button" class="btn-sm" data-edit-chunk="${escapeHtml(c.id)}">Изменить</button>
          <button type="button" class="btn-sm btn-danger" data-del-chunk="${escapeHtml(c.id)}">Удалить</button>
        </div>
      </li>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li class="empty">${escapeHtml(err.message)}</li>`;
  }
}

function renderSearchResults(data) {
  const out = $("#knowledgeSearchOutput");
  const results = data?.results || [];
  if (!results.length) {
    setResult(out, "Ничего не найдено");
    return;
  }
  out.innerHTML = results
    .map(
      (r, i) => `
    <div class="search-hit">
      <p class="result-meta">#${i + 1} · score ${escapeHtml(String(r.hybrid_score ?? r.vector_score ?? 0))} · ${escapeHtml(r.metadata?.document_title || r.id)}</p>
      <p>${escapeHtml(r.text || "")}</p>
    </div>`
    )
    .join("");
}

function renderAskResult(data) {
  const out = $("#knowledgeSearchOutput");
  const sources = (data?.sources || [])
    .map(
      (s) =>
        `<li><strong>${escapeHtml(s.document_title || s.chunk_id)}</strong>${s.section_title ? ` · ${escapeHtml(s.section_title)}` : ""}${s.page_number ? ` · стр. ${escapeHtml(String(s.page_number))}` : ""} · score ${s.score} — ${escapeHtml(s.preview || "")}</li>`
    )
    .join("");
  const hits = data?.search?.results || [];
  const rawBlock =
    hits.length > 0
      ? `<details class="search-raw-details"><summary>Найденные фрагменты (${hits.length})</summary>${hits
          .map(
            (r, i) =>
              `<div class="search-hit"><p class="result-meta">#${i + 1} · score ${escapeHtml(String(r.hybrid_score ?? r.vector_score ?? 0))}</p><p>${escapeHtml(r.text || "")}</p></div>`
          )
          .join("")}</details>`
      : "";
  out.innerHTML =
    `<p class="result-meta">Ответ LLM на основе поиска</p>` +
    `<article class="ai-narrative">${escapeHtml(data.answer || "")}</article>` +
    (sources ? `<ul class="insights-list">${sources}</ul>` : "") +
    rawBlock;
}

function setupDropzone() {
  const zone = $("#knowledgeDropzone");
  const input = $("#knowledgeFileInput");
  const nameEl = $("#knowledgeFileName");
  if (!zone || !input) return;
  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files?.[0]) nameEl.textContent = input.files[0].name;
  });
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("is-dragover");
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    nameEl.textContent = file.name;
  });
  ["dragenter", "dragover"].forEach((ev) =>
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.remove("is-dragover");
    })
  );
}

function loadKnowledgePanel() {
  refreshStats();
  loadDocuments();
  loadChunks();
}

async function pollKnowledgeJob(jobId, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    await new Promise((r) => setTimeout(r, 3000));
    try {
      const res = await q().api(`/jobs/runs/${jobId}`);
      const status = res?.data?.status;
      if (status === "completed") {
        const chunks = res?.data?.result?.chunks_indexed;
        q().toast(`Индексация завершена${chunks != null ? `: ${chunks} фрагм.` : ""}`);
        try {
          await q().api("/knowledge/refresh-chroma", { method: "POST" });
        } catch {
          /* stats refresh below */
        }
        await refreshStats();
        await loadDocuments();
        await loadChunks();
        return;
      }
      if (status === "failed") {
        q().toast(res?.data?.error || "Индексация не удалась", true);
        return;
      }
    } catch {
      /* retry */
    }
  }
  q().toast("Индексация ещё выполняется — проверьте вкладку «Задачи»", false);
}

function setupKnowledge() {
  if (!$("#panel-knowledge")) return;

  setupDropzone();

  $("#knowledgeUploadForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const file = $("#knowledgeFileInput").files?.[0];
    if (!file) {
      q().toast("Выберите файл", true);
      return;
    }
    const sizeKb = Math.round(file.size / 1024);
    const bgCheckbox = $("#knowledgeBackground");
    if (bgCheckbox && !bgCheckbox.checked) {
      bgCheckbox.checked = true;
      q().toast("Включена фоновая индексация (безопасный режим)", false);
    }
    if (file.size >= 5 * 1024 * 1024) {
      const ok = window.confirm(
        `Файл ${(file.size / (1024 * 1024)).toFixed(1)} МБ. Индексация загрузит модель эмбеддингов (~500 МБ RAM). Продолжить?`
      );
      if (!ok) return;
    }
    const body = new FormData();
    body.append("file", file);
    if (form.title.value.trim()) body.append("title", form.title.value.trim());
    if (form.description.value.trim()) body.append("description", form.description.value.trim());
    const background = $("#knowledgeBackground")?.checked;
    const uploadUrl = background
      ? "/knowledge/documents/upload?background=true"
      : "/knowledge/documents/upload";
    try {
      if (background) {
        q().toast("Файл поставлен в очередь индексации…");
      } else {
        q().toast("Индексация… Первая загрузка модели эмбеддингов может занять 1–3 мин.", false);
      }
      const res = await q().api(uploadUrl, { method: "POST", body, timeoutMs: 600000 });
      if (background && res?.data?.job_id) {
        q().toast(`Задача ${res.data.job_id.slice(0, 8)}… в очереди`);
        pollKnowledgeJob(res.data.job_id);
      } else {
        const truncated = res?.data?.truncated;
        const msg = truncated
          ? `Проиндексировано ${res?.data?.chunks_indexed ?? "—"} фрагм. (лимит, файл обрезан)`
          : `Проиндексировано фрагментов: ${res?.data?.chunks_indexed ?? "—"}`;
        q().toast(msg, Boolean(truncated));
      }
      form.reset();
      $("#knowledgeFileName").textContent = "Файл не выбран";
      await refreshStats();
      await loadDocuments();
      await loadChunks();
    } catch (err) {
      let msg = err.message;
      if (err.details?.existing_id && (err.details?.chunk_count ?? 0) === 0) {
        msg += " Нажмите «Переиндексировать» в списке документов.";
      }
      q().toast(msg, true);
    }
  });

  $("#knowledgeDatasetForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const datasetId = Number(q().state?.selectedDatasetId || $("#knowledgeDatasetId")?.value);
    if (!datasetId) {
      q().toast("Выберите активный набор в шапке", true);
      return;
    }
    try {
      const res = await q().api(`/knowledge/documents/ingest-dataset/${datasetId}`, {
        method: "POST",
        json: {},
        timeoutMs: 600000,
      });
      q().toast(`Датасет #${datasetId}: фрагментов ${res?.data?.chunks_indexed ?? "—"}`);
      await refreshStats();
      await loadDocuments();
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    }
  });

  $("#knowledgeSearchForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const query = String(fd.get("query") || "").trim();
    if (!query) {
      q().toast("Введите запрос", true);
      return;
    }
    const withLlm = Boolean($("#knowledgeSearchWithLlm")?.checked);
    const out = $("#knowledgeSearchOutput");
    setResult(
      out,
      withLlm
        ? "Поиск и обработка LLM… Это может занять несколько минут."
        : "Поиск…"
    );
    try {
      const res = await q().api("/knowledge/search", {
        method: "POST",
        json: {
          query,
          mode: String(fd.get("mode") || "hybrid"),
          top_k: Number(fd.get("top_k") || 6),
          document_id: $("#knowledgeSearchDoc")?.value || null,
          with_llm: withLlm,
        },
        timeoutMs: withLlm ? 900000 : 120000,
      });
      const data = res?.data || res;
      if (withLlm) {
        renderAskResult(data);
      } else {
        renderSearchResults(data);
      }
    } catch (err) {
      setResult(out, err.message, true);
      if (withLlm) q().toast(err.message, true);
    }
  });

  $("#refreshKnowledge")?.addEventListener("click", async () => {
    try {
      await q().api("/knowledge/refresh-chroma", { method: "POST" });
    } catch {
      /* fallback to stats-only refresh */
    }
    await refreshStats();
    await loadDocuments();
    await loadChunks();
  });

  $("#repairChroma")?.addEventListener("click", async () => {
    if (
      !confirm(
        "Пересоздать векторную БД Chroma из manifest? Это может занять несколько минут."
      )
    ) {
      return;
    }
    const btn = $("#repairChroma");
    if (btn) btn.disabled = true;
    q().toast("Восстановление Chroma… Это может занять несколько минут.", false);
    try {
      const res = await q().api("/knowledge/repair-chroma", {
        method: "POST",
        timeoutMs: 900000,
      });
      const d = res?.data || {};
      q().toast(
        `Chroma восстановлена: ${d.reindexed ?? d.vector_count ?? "—"} векторов`,
        false
      );
      await refreshStats();
      await loadDocuments();
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  $("#knowledgeFilterBtn")?.addEventListener("click", () => loadChunks());
  $("#knowledgeDocFilter")?.addEventListener("change", () => loadChunks());

  $("#knowledgeDocList")?.addEventListener("click", async (e) => {
    const reindexBtn = e.target.closest("[data-reindex-doc]");
    if (reindexBtn) {
      const docId = reindexBtn.dataset.reindexDoc;
      try {
        q().toast("Переиндексация… Это может занять несколько минут.", false);
        const res = await q().api(`/knowledge/documents/${docId}/reindex`, {
          method: "POST",
          timeoutMs: 600000,
        });
        q().toast(`Проиндексировано фрагментов: ${res?.data?.chunks_indexed ?? "—"}`);
        await refreshStats();
        await loadDocuments();
        await loadChunks();
      } catch (err) {
        q().toast(err.message, true);
      }
      return;
    }
    const dsBtn = e.target.closest("[data-open-dataset]");
    if (dsBtn) {
      const id = Number(dsBtn.dataset.openDataset);
      if (id && q().setSelectedDataset) {
        q().setSelectedDataset(id);
        q().showPanel?.("datasets");
      }
      return;
    }
    const btn = e.target.closest("[data-del-doc]");
    if (!btn) return;
    if (!confirm(`Удалить документ ${btn.dataset.delDoc} и все фрагменты?`)) return;
    try {
      await q().api(`/knowledge/documents/${btn.dataset.delDoc}`, { method: "DELETE" });
      q().toast("Документ удалён");
      await refreshStats();
      await loadDocuments();
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    }
  });

  $("#knowledgeChunkList")?.addEventListener("click", async (e) => {
    const editBtn = e.target.closest("[data-edit-chunk]");
    if (editBtn) {
      try {
        const id = editBtn.dataset.editChunk;
        const res = await q().api(`/knowledge/chunks/${id}`);
        const item = res?.data || res;
        $("#editChunkId").value = id;
        $("#editChunkText").value = item.text || "";
        $("#editChunkModal")?.showModal();
      } catch (err) {
        q().toast(err.message, true);
      }
      return;
    }
    const delBtn = e.target.closest("[data-del-chunk]");
    if (!delBtn) return;
    if (!confirm("Удалить фрагмент?")) return;
    try {
      await q().api(`/knowledge/chunks/${delBtn.dataset.delChunk}`, { method: "DELETE" });
      q().toast("Фрагмент удалён");
      await refreshStats();
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    }
  });

  const modal = $("#editChunkModal");
  $("#closeChunkModal")?.addEventListener("click", () => modal?.close());
  $("#cancelChunkModal")?.addEventListener("click", () => modal?.close());
  $("#editChunkForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = $("#editChunkId").value;
    const text = $("#editChunkText").value;
    try {
      await q().api(`/knowledge/chunks/${id}`, { method: "PUT", json: { text } });
      modal?.close();
      q().toast("Фрагмент обновлён");
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    }
  });

  document.querySelectorAll(".nav-link[data-panel='knowledge']").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dsId = q().state?.selectedDatasetId;
      if (dsId && $("#knowledgeDatasetId")) $("#knowledgeDatasetId").value = dsId;
      loadKnowledgePanel();
    });
  });

  document.addEventListener("quart:highlight-knowledge-doc", (ev) => {
    const docId = ev.detail?.documentId;
    const filter = $("#knowledgeDocFilter");
    if (docId && filter) {
      filter.value = docId;
      loadChunks();
    }
  });

  document.addEventListener("quart:index-dataset-knowledge", async (ev) => {
    const datasetId = ev.detail?.datasetId;
    if (!datasetId) return;
    if ($("#knowledgeDatasetId")) $("#knowledgeDatasetId").value = String(datasetId);
    try {
      const res = await q().api(`/knowledge/documents/ingest-dataset/${datasetId}`, {
        method: "POST",
        json: {},
        timeoutMs: 600000,
      });
      q().toast(`Датасет #${datasetId}: фрагментов ${res?.data?.chunks_indexed ?? "—"}`);
      await refreshStats();
      await loadDocuments();
      await loadChunks();
    } catch (err) {
      q().toast(err.message, true);
    }
  });
}

function waitForBridge() {
  if (window.__quart?.api) {
    setupKnowledge();
    return;
  }
  setTimeout(waitForBridge, 50);
}

waitForBridge();
