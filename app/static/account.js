"use strict";
(() => {
  const $ = id => document.getElementById(id), workspace = window.PhishLensWorkspace;
  const register = location.pathname === "/register";
  document.title = (register ? "Tạo tài khoản" : "Đăng nhập") + " · PhishLens";
  $(register ? "register-tab" : "login-tab").classList.add("active");
  $(register ? "register-tab" : "login-tab").setAttribute("aria-current", "page");
  $("auth-title").textContent = register ? "Bắt đầu với PhishLens." : "Chào mừng bạn trở lại.";
  $("auth-description").textContent = register ? "Tạo tài khoản để quản lý các lượt kiểm tra của riêng bạn." : "Đăng nhập để mở không gian PhishLens của bạn.";
  ["name-field", "confirm-field", "password-hint"].forEach(id => { $(id).hidden = !register; });
  $("display-name").required = register; $("confirm-password").required = register;
  $("password").minLength = register ? 12 : 1;
  $("password").autocomplete = register ? "new-password" : "current-password";
  $("auth-submit").textContent = register ? "Tạo tài khoản" : "Đăng nhập";
  $("toggle-password").addEventListener("click", () => {
    const reveal = $("password").type === "password";
    $("password").type = reveal ? "text" : "password"; $("toggle-password").textContent = reveal ? "Ẩn" : "Hiện";
    $("toggle-password").setAttribute("aria-label", reveal ? "Ẩn mật khẩu" : "Hiện mật khẩu");
  });
  const destination = () => {
    const next = new URLSearchParams(location.search).get("next") || "/dashboard";
    return ["/dashboard", "/check", "/history", "/account", "/admin", "/feedback"].includes(next.split("?")[0]) ? next : "/dashboard";
  };
  workspace.ready.then(() => {
    if (workspace.user) location.replace(destination());
    $("first-account").hidden = !workspace.firstAccount;
    if (workspace.firstAccount && !register) $("auth-description").textContent = "Chưa có tài khoản trên máy này. Chọn Tạo tài khoản để bắt đầu.";
  }).catch(error => { $("auth-error").textContent = error.message; $("auth-error").hidden = false; });
  $("auth-form").addEventListener("submit", async event => {
    event.preventDefault(); $("auth-error").hidden = true;
    if (register && $("password").value !== $("confirm-password").value) {
      $("auth-error").textContent = "Hai mật khẩu chưa trùng nhau."; $("auth-error").hidden = false; return;
    }
    $("auth-submit").disabled = true; $("auth-submit").textContent = "Đang xử lý…";
    try {
      await workspace.ready;
      const body = {email: $("email").value.trim(), password: $("password").value};
      if (register) body.display_name = $("display-name").value.trim();
      await workspace.request("/api/auth/" + (register ? "register" : "login"), {method: "POST", body});
      $("password").value = ""; $("confirm-password").value = ""; location.assign(destination());
    } catch (error) { $("auth-error").textContent = error.message; $("auth-error").hidden = false; }
    finally { $("auth-submit").disabled = false; $("auth-submit").textContent = register ? "Tạo tài khoản" : "Đăng nhập"; }
  });
})();
