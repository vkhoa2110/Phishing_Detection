"use strict";
(() => {
  const workspace = {enabled: false, user: null, csrf: ""};
  window.PhishLensWorkspace = workspace;
  workspace.node = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  workspace.date = value => new Date(value).toLocaleString("vi-VN", {dateStyle: "short", timeStyle: "short"});
  workspace.risks = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra", LOW: "Chưa thấy dấu hiệu", UNKNOWN: "Chưa đủ thông tin"};
  workspace.notify = (message, failed = false) => {
    document.getElementById("workspace-toast")?.remove();
    const el = workspace.node("div", "app-toast" + (failed ? " failed" : ""), message);
    el.id = "workspace-toast"; el.setAttribute("role", "status"); document.body.append(el);
    setTimeout(() => el.remove(), 6000);
  };
  workspace.request = async (path, options = {}) => {
    const method = options.method || "GET";
    const headers = {"Content-Type": "application/json"};
    if (method !== "GET") headers["X-CSRF-Token"] = workspace.csrf;
    const response = await fetch(path, {method, headers, cache: "no-store", credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body)});
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 && !location.pathname.match(/^\/(login|register)$/)) location.assign("/login?next=" + encodeURIComponent(location.pathname));
      throw new Error(data.detail || "Chưa thực hiện được thao tác. Vui lòng thử lại.");
    }
    if (data.csrf_token) workspace.csrf = data.csrf_token;
    return data;
  };
  workspace.download = (data, filename) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
    const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  workspace.logout = async () => {
    try { await workspace.request("/api/auth/logout", {method: "POST", body: {}}); location.assign("/login"); }
    catch (error) { workspace.notify(error.message, true); }
  };
  workspace.ready = (async () => {
    const response = await fetch("/api/auth/session", {cache: "no-store", credentials: "same-origin"});
    // Direct research factories retain their existing account-free contract.
    if (response.status === 404) return workspace;
    if (!response.ok) throw new Error("Chưa kiểm tra được phiên đăng nhập. Tải lại trang để thử lại.");
    const data = await response.json();
    workspace.enabled = data.enabled === true; workspace.user = data.user; workspace.csrf = data.csrf_token;
    workspace.guest = workspace.enabled && !workspace.user && data.guest_access === true;
    workspace.firstAccount = data.first_account;
    if (workspace.enabled && !workspace.user && !location.pathname.match(/^\/(login|register)$/) && !(workspace.guest && ["/", "/check"].includes(location.pathname))) {
      location.replace("/login?next=" + encodeURIComponent(location.pathname)); return workspace;
    }
    document.querySelectorAll("[data-guest]").forEach(el => { el.hidden = !workspace.guest; });
    if (workspace.guest && document.getElementById("reload-model")) document.getElementById("reload-model").hidden = true;
    if (workspace.user) {
      document.querySelectorAll("[data-workspace]").forEach(el => { el.hidden = false; });
      document.querySelectorAll("[data-account-name]").forEach(el => { el.textContent = workspace.user.display_name; });
      document.querySelectorAll("[data-admin]").forEach(el => { el.hidden = workspace.user.role !== "admin"; });
      document.querySelectorAll("[data-logout]").forEach(el => el.addEventListener("click", workspace.logout));
      document.querySelectorAll("[data-nav]").forEach(el => {
        el.classList.toggle("nav-current", el.getAttribute("href") === location.pathname);
        if (el.getAttribute("href") === location.pathname) el.setAttribute("aria-current", "page");
        else el.removeAttribute("aria-current");
      });
      const checkLink = document.querySelector(".header-nav a[href='#analysis-form']");
      if (checkLink) checkLink.href = "/check";
      if (workspace.user.role !== "admin" && document.getElementById("reload-model")) document.getElementById("reload-model").hidden = true;
    }
    return workspace;
  })();
  window.addEventListener("pageshow", event => { if (event.persisted && workspace.enabled) location.reload(); });
})();
