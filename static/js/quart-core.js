/** Общие утилиты SPA: API, state, DOM-хелперы. */

export const API = "/api/v1";
export const TOKEN_KEY = "quart_access_token";
export const REFRESH_TOKEN_KEY = "quart_refresh_token";
export const USER_KEY = "quart_user";
export const ACTIVE_DATASET_KEY = "quart_active_dataset_id";
export const FILTERS_STORAGE_PREFIX = "quart_filters";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const state = {
  token: localStorage.getItem(TOKEN_KEY) || "",
  refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY) || "",
  user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
  selectedDatasetId: Number(localStorage.getItem(ACTIVE_DATASET_KEY)) || null,
  datasetsCache: [],
  columns: [],
  columnsDatasetId: null,
  currentReportId: null,
  exportOffset: 0,
  exportLimit: 100,
  exportTotal: 0,
  filterValueSuggestCache: new Map(),
};

export function toast(message, isError = false) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  el.classList.toggle("is-error", isError);
  el.classList.add("is-visible");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.classList.remove("is-visible");
  }, 2800);
}

export function pretty(data) {
  return typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
    delete options.json;
  }
  const timeoutMs = options.timeoutMs ?? 120000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
    let data = null;
    const text = await res.text();
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) {
      let detail =
        (data && (data.detail || data.message)) ||
        res.statusText ||
        "Request failed";
      if (res.status === 404 && typeof detail === "string" && /not found/i.test(detail)) {
        detail +=
          ". Если маршрут недавно добавлен — перезапустите сервер (UVICORN_RELOAD=false требует ручной restart).";
      }
      let extraDetails = data?.details;
      if (detail && typeof detail === "object") {
        extraDetails = detail.details ?? extraDetails;
        detail = detail.message ?? detail;
      }
      const errMsg = typeof detail === "string" ? detail : pretty(detail);
      const err = new Error(errMsg);
      if (extraDetails) err.details = extraDetails;
      throw err;
    }
    return data;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        options.timeoutMs >= 600000
          ? "AI-анализ занял слишком много времени. Первая загрузка модели может занять несколько минут — попробуйте ещё раз или увеличьте LLM_TIMEOUT в .env"
          : "Превышено время ожидания ответа сервера"
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function formatSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatCell(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/\.?0+$/, "");
  }
  if (typeof value === "object") return pretty(value);
  return String(value);
}

export function isNumericLike(value) {
  return typeof value === "number" && Number.isFinite(value);
}

export function ensureActiveDataset() {
  if (!state.selectedDatasetId) {
    throw new Error("Выберите активный набор данных в шапке или загрузите файл на вкладке «Данные»");
  }
  return state.selectedDatasetId;
}

export function renderResultWarningBanner(data) {
  if (!data?.result_warning) return "";
  return `<div class="result-warning" role="status">${escapeHtml(data.result_warning)}</div>`;
}

export async function checkHealth() {
  const el = $("#apiStatus");
  if (!el) return;
  try {
    const res = await fetch("/health", { signal: AbortSignal.timeout(8000) });
    const data = res.ok ? await res.json().catch(() => ({})) : null;
    const ok = res.ok;
    el.classList.toggle("is-online", ok);
    el.classList.toggle("is-offline", !ok);
    const ver = data?.version ? ` v${data.version}` : "";
    const commit = data?.git_commit ? ` · ${data.git_commit}` : "";
    el.title = ok ? `API online${ver}${commit}` : "API offline";
    el.textContent = ok && data?.version ? `API ${data.version}${commit}` : "API";
  } catch {
    el.classList.add("is-offline");
    el.classList.remove("is-online");
    el.title = "API offline";
    el.textContent = "API";
  }
}
