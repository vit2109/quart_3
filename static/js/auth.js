/** Авторизация: сессия, UI drawer (E22+). */

import {
  TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  USER_KEY,
  $,
  $$,
  api,
  state,
  toast,
} from "./quart-core.js";

export function syncAuthUi() {
  const btn = $("#openAuth");
  const session = $("#authSession");
  const forms = $("#authForms");
  const loggedIn = Boolean(state.token && state.token !== "demo-token");

  if (loggedIn && state.user) {
    if (btn) btn.textContent = state.user.email || "Сессия";
    if (session) session.hidden = false;
    if (forms) forms.hidden = true;
    const emailEl = $("#authUserEmail");
    const roleEl = $("#authUserRole");
    if (emailEl) emailEl.textContent = state.user.email || "—";
    if (roleEl) roleEl.textContent = `Роль: ${state.user.role || "—"}`;
  } else {
    if (btn) btn.textContent = "Вход";
    if (session) session.hidden = true;
    if (forms) forms.hidden = false;
  }
}

export function saveAuthSession(data) {
  const payload = data?.data || data;
  const access = payload?.access_token;
  const refresh = payload?.refresh_token;
  const user = payload?.user;
  if (!access) throw new Error("Сервер не вернул access_token");
  state.token = access;
  state.refreshToken = refresh || "";
  state.user = user || null;
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  else localStorage.removeItem(REFRESH_TOKEN_KEY);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
  syncAuthUi();
}

export function clearAuthSession() {
  state.token = "";
  state.refreshToken = "";
  state.user = null;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  syncAuthUi();
}

export function setupAuth() {
  const drawer = $("#authDrawer");
  const openBtn = $("#openAuth");
  const closeBtn = $("#closeAuth");
  if (!openBtn || !drawer) return;

  openBtn.addEventListener("click", () => {
    drawer.hidden = !drawer.hidden;
    openBtn.setAttribute("aria-expanded", String(!drawer.hidden));
    syncAuthUi();
  });
  closeBtn?.addEventListener("click", () => {
    drawer.hidden = true;
    openBtn.setAttribute("aria-expanded", "false");
  });

  $$("[data-auth-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$("[data-auth-tab]").forEach((t) => t.classList.toggle("is-active", t === tab));
      const name = tab.dataset.authTab;
      $$("[data-auth-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.authPanel !== name;
      });
    });
  });

  $("#logoutBtn")?.addEventListener("click", () => {
    clearAuthSession();
    drawer.hidden = true;
    openBtn.setAttribute("aria-expanded", "false");
    toast("Вы вышли из системы");
  });

  $("#loginForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const data = await api("/auth/login", {
        method: "POST",
        json: { email: fd.get("email"), password: fd.get("password") },
      });
      saveAuthSession(data);
      drawer.hidden = true;
      toast(`Вход: ${state.user?.email || "OK"}`);
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#registerForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/auth/register", {
        method: "POST",
        json: {
          email: fd.get("email"),
          username: fd.get("username"),
          password: fd.get("password"),
          full_name: fd.get("full_name") || null,
        },
      });
      const loginData = await api("/auth/login", {
        method: "POST",
        json: { email: fd.get("email"), password: fd.get("password") },
      });
      saveAuthSession(loginData);
      drawer.hidden = true;
      toast("Регистрация и вход выполнены");
    } catch (err) {
      toast(err.message, true);
    }
  });
}
