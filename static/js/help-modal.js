/** Модальное окно справки с простым рендером Markdown. */

import { $ } from "./quart-core.js";
import { HELP_TOPICS } from "./help-content.js";

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Минимальный Markdown → HTML (заголовки, списки, таблицы, код, жирный). */
export function renderMarkdown(md) {
  const lines = String(md || "").split("\n");
  const out = [];
  let inUl = false;
  let inOl = false;
  let inCode = false;
  let codeBuf = [];
  let tableRows = [];

  const flushList = () => {
    if (inUl) {
      out.push("</ul>");
      inUl = false;
    }
    if (inOl) {
      out.push("</ol>");
      inOl = false;
    }
  };

  const flushTable = () => {
    if (!tableRows.length) return;
    const [head, ...body] = tableRows;
    const cells = (row) => row.split("|").slice(1, -1).map((c) => c.trim());
    out.push("<table><thead><tr>");
    cells(head).forEach((c) => out.push(`<th>${inlineFormat(c)}</th>`));
    out.push("</tr></thead><tbody>");
    body.forEach((row) => {
      if (/^[\s|:-]+$/.test(row)) return;
      out.push("<tr>");
      cells(row).forEach((c) => out.push(`<td>${inlineFormat(c)}</td>`));
      out.push("</tr>");
    });
    out.push("</tbody></table>");
    tableRows = [];
  };

  const inlineFormat = (text) => {
    let s = escapeHtml(text);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    return s;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    if (line.startsWith("```")) {
      if (inCode) {
        out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
        codeBuf = [];
        inCode = false;
      } else {
        flushList();
        flushTable();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeBuf.push(raw);
      continue;
    }

    if (line.startsWith("|")) {
      flushList();
      tableRows.push(line);
      continue;
    }
    flushTable();

    if (line.startsWith("## ")) {
      flushList();
      out.push(`<h3>${inlineFormat(line.slice(3))}</h3>`);
      continue;
    }
    if (line.startsWith("### ")) {
      flushList();
      out.push(`<h4>${inlineFormat(line.slice(4))}</h4>`);
      continue;
    }
    if (line.startsWith("> ")) {
      flushList();
      out.push(`<blockquote>${inlineFormat(line.slice(2))}</blockquote>`);
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inUl) {
        flushList();
        out.push("<ul>");
        inUl = true;
      }
      out.push(`<li>${inlineFormat(line.slice(2))}</li>`);
      continue;
    }
    if (/^\d+\.\s/.test(line)) {
      if (!inOl) {
        flushList();
        out.push("<ol>");
        inOl = true;
      }
      out.push(`<li>${inlineFormat(line.replace(/^\d+\.\s/, ""))}</li>`);
      continue;
    }

    flushList();
    if (line.trim()) {
      out.push(`<p>${inlineFormat(line)}</p>`);
    }
  }

  flushList();
  flushTable();
  if (inCode && codeBuf.length) {
    out.push(`<pre><code>${escapeHtml(codeBuf.join("\n"))}</code></pre>`);
  }
  return out.join("\n");
}

export function openHelp(topicId) {
  const topic = HELP_TOPICS[topicId];
  const dialog = $("#helpModal");
  const titleEl = $("#helpModalTitle");
  const bodyEl = $("#helpModalBody");
  if (!topic || !dialog || !titleEl || !bodyEl) return;
  titleEl.textContent = topic.title;
  bodyEl.innerHTML = renderMarkdown(topic.body);
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.removeAttribute("hidden");
  }
}

export function initHelpModal() {
  const dialog = $("#helpModal");
  if (!dialog) return;

  $("#helpModalClose")?.addEventListener("click", () => dialog.close?.());
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close?.();
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-help]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    openHelp(btn.dataset.help);
  });
}
