"use strict";
(() => {
  const app = window.PhishLensWorkspace, n = app.node, $ = id => document.getElementById(id);
  const root = $("portal-content"), state = {page: 1, selected: null, sequence: 0};
  const risk = value => n("span", "portal-risk " + value, app.risks[value] || "Chưa đủ thông tin");
  const link = (text, href, className = "") => { const el = n("a", className, text); el.href = href; return el; };
  const button = (text, className, callback) => {
    const el = n("button", className, text); el.type = "button";
    if (callback) el.addEventListener("click", () => perform(el, callback));
    return el;
  };
  async function perform(control, action) {
    control.disabled = true;
    try { await action(); } catch (error) { app.notify(error.message, true); }
    finally { control.disabled = false; }
  }
  const panel = title => { const el = n("section", "portal-panel"); if (title) el.append(n("h2", "", title)); return el; };
  function empty(text, hint, action = true) {
    const el = n("section", "empty-state"); el.append(n("h2", "", text), n("p", "", hint));
    if (action) el.append(link("Bắt đầu kiểm tra", "/check", "primary-button"));
    return el;
  }
  async function refresh() {
    if (location.pathname === "/history") await loadHistory();
    else if (location.pathname === "/dashboard") await dashboard();
  }
  function records(items) {
    const list = n("div", "record-list");
    for (const item of items) {
      const card = n("article", "record-card"), body = n("div", "record-main"), side = n("div", "record-side");
      card.dataset.recordId = item.id;
      body.append(button(item.title, "record-title", () => openRecord(item.id)));
      const meta = n("div", "record-meta");
      [app.date(item.created_at), item.mode === "url" ? "Đường dẫn" : "Tin nhắn / email", item.content_saved ? "Có nội dung đã lưu" : "Chỉ lưu thông tin lượt kiểm tra"].forEach(text => meta.append(n("span", "", text)));
      body.append(meta);
      if (item.note) body.append(n("p", "portal-muted", item.note));
      const favorite = button(item.favorite ? "★" : "☆", "record-favorite" + (item.favorite ? " selected" : ""), async () => {
        await app.request("/api/history/" + item.id, {method: "PATCH", body: {favorite: !item.favorite}}); await refresh();
      });
      favorite.setAttribute("aria-label", item.favorite ? "Bỏ đánh dấu kết quả" : "Đánh dấu kết quả");
      favorite.setAttribute("aria-pressed", String(Boolean(item.favorite)));
      side.append(risk(item.risk), favorite); card.append(body, side); list.append(card);
    }
    return list;
  }
  async function dashboard() {
    const data = await app.request("/api/dashboard");
    root.replaceChildren();
    const stats = n("div", "stat-grid");
    for (const [title, value, hint] of [
      ["Lượt kiểm tra đã lưu", data.total, "Trong lịch sử riêng của bạn"],
      ["Lượt cần cảnh giác", (data.risks.HIGH || 0) + (data.risks.WARNING || 0), "Theo nhận định của hệ thống"],
      ["Đã đánh dấu", data.favorites, "Những kết quả muốn xem lại"],
      ["Lượt AI trong 24 giờ", data.ai_used_24h + " / " + data.ai_limit_24h, "Giới hạn theo từng tài khoản"],
    ]) {
      const card = n("div", "stat-card"); card.append(n("span", "", title), n("strong", "", value), n("p", "", hint)); stats.append(card);
    }
    root.append(stats);
    const recent = panel(), heading = n("div", "portal-panel-heading");
    heading.append(n("h2", "", "Lượt kiểm tra gần đây"), link("Xem tất cả →", "/history")); recent.append(heading);
    recent.append(data.recent.length ? records(data.recent) : empty("Mỗi lần kiểm tra, thêm một căn cứ.", "Lịch sử của bạn còn trống. Hãy bắt đầu với một tin nhắn hoặc đường dẫn cần xác minh."));
    root.append(recent);
    const privacy = panel("Bạn quyết định điều được lưu lại.");
    privacy.append(n("p", "portal-muted", "Mặc định lịch sử chỉ có thời điểm, loại kiểm tra và mức nhận định. Muốn xem lại nội dung chi tiết, hãy chọn lưu bản đã che trước khi kiểm tra. Bạn có thể xóa từng kết quả hoặc toàn bộ lịch sử bất cứ lúc nào."));
    root.append(privacy);
  }
  function historyPage() {
    const controls = panel(), form = n("form", "history-filters"); form.id = "history-filters";
    const search = n("div"), label = n("label", "", "Tìm trong tên và ghi chú"); label.htmlFor = "history-search";
    const input = n("input"); input.id = "history-search"; input.type = "search"; input.maxLength = 100; input.placeholder = "Tên lượt kiểm tra…"; search.append(label, input);
    const selectBox = n("div"), selectLabel = n("label", "", "Mức nhận định"); selectLabel.htmlFor = "history-risk";
    const select = n("select"); select.id = "history-risk";
    for (const [value, text] of [["", "Tất cả mức"], ...Object.entries(app.risks)]) { const option = n("option", "", text); option.value = value; select.append(option); }
    selectBox.append(selectLabel, select);
    const favorite = n("label", "favorite-filter"), check = n("input"); check.type = "checkbox"; check.id = "history-favorite";
    favorite.append(check, document.createTextNode("Chỉ đã đánh dấu"));
    const submit = n("button", "primary-button", "Tìm kiếm"); submit.type = "submit";
    form.append(search, selectBox, favorite, submit); controls.append(form);
    const toolbar = n("div", "history-toolbar"), count = n("span"); count.id = "history-count";
    toolbar.append(count, button("Xóa toàn bộ lịch sử", "danger-button", async () => {
      if (!confirm("Xóa toàn bộ lịch sử cùng phản hồi và nội dung đã chia sẻ kèm theo? Thao tác này không thể khôi phục.")) return;
      await app.request("/api/history", {method: "DELETE"}); state.page = 1; await loadHistory(); app.notify("Đã xóa lịch sử của bạn.");
    }));
    const content = n("div"); content.id = "history-records";
    const pagination = n("div", "pagination"); pagination.id = "history-pagination";
    root.replaceChildren(controls, toolbar, content, pagination);
    form.addEventListener("submit", event => { event.preventDefault(); state.page = 1; perform(submit, loadHistory); });
    select.addEventListener("change", () => form.requestSubmit()); check.addEventListener("change", () => form.requestSubmit());
    return loadHistory();
  }
  async function loadHistory() {
    const sequence = ++state.sequence;
    const params = new URLSearchParams({q: $("history-search").value.trim(), risk: $("history-risk").value, favorite: $("history-favorite").checked, page: state.page});
    const data = await app.request("/api/history?" + params);
    if (sequence !== state.sequence) return;
    $("history-count").textContent = data.total + " kết quả";
    $("history-records").replaceChildren(data.items.length ? records(data.items) : empty("Không có kết quả phù hợp", "Thử bỏ bộ lọc, thay từ khóa hoặc thực hiện một lượt kiểm tra mới."));
    const pagination = $("history-pagination"); pagination.replaceChildren();
    if (data.total > 20) {
      const previous = button("← Trang trước", "secondary-button", async () => { state.page--; await loadHistory(); }); previous.disabled = state.page === 1;
      const next = button("Trang sau →", "secondary-button", async () => { state.page++; await loadHistory(); }); next.disabled = state.page * 20 >= data.total;
      pagination.append(previous, n("span", "", `Trang ${state.page} / ${Math.ceil(data.total / 20)}`), next);
    }
  }
  function displayRecord(item) {
    state.selected = item;
    $("record-title").value = item.title; $("record-note").value = item.note;
    $("favorite-record").textContent = item.favorite ? "★ Bỏ đánh dấu" : "☆ Đánh dấu";
    const content = $("record-content"); content.replaceChildren(risk(item.risk), n("p", "portal-muted", app.date(item.created_at)));
    const facts = n("p", "portal-muted", (item.mode === "url" ? "Kiểm tra đường dẫn" : "Kiểm tra tin nhắn / email") + ` · ${item.url_count} URL · AI: ` + ({ok: "có kết quả", disabled: "đã tắt", error: "chưa hoàn tất"}[item.llm_status] || "chưa hoàn tất"));
    content.append(facts);
    content.append(window.PhishLensProduct.feedbackForm(item.id, Boolean(item.snapshot)));
    if (!item.snapshot) {
      content.append(n("p", "inline-notice", "Lượt này chỉ lưu thông tin tổng quát. Nội dung và kết quả chi tiết không được lưu nên không thể khôi phục để xem lại.")); return;
    }
    const llm = item.snapshot.llm;
    if (llm?.status === "ok" && llm.verdict) {
      content.append(n("h3", "", "Phân tích AI đã lưu"), n("p", "portal-muted", llm.verdict.summary));
      for (const evidence of llm.verdict.evidence || []) content.append(n("blockquote", "", evidence.quote), n("p", "portal-muted", evidence.reason));
    }
    if (item.snapshot.approved_text || llm?.input_used) {
      const sent = n("details"); sent.append(n("summary", "", "Xem bản nội dung đã che được lưu"), n("pre", "", item.snapshot.approved_text || llm.input_used)); content.append(sent);
    }
    for (const url of item.snapshot.urls || []) content.append(n("p", "portal-muted", "URL: " + url.url + " · " + (app.risks[url.risk_level] || "Chưa có kết quả")));
  }
  async function openRecord(id) {
    const item = await app.request("/api/history/" + encodeURIComponent(id)); displayRecord(item);
    if (!$("record-dialog").open) $("record-dialog").showModal();
  }
  $("close-record").addEventListener("click", () => $("record-dialog").close());
  $("record-form").addEventListener("submit", event => {
    event.preventDefault(); if (!state.selected) return;
    perform($("record-form").querySelector("button[type=submit]"), async () => {
      const item = await app.request("/api/history/" + state.selected.id, {method: "PATCH", body: {title: $("record-title").value.trim(), note: $("record-note").value}});
      displayRecord(item); await refresh(); app.notify("Đã cập nhật kết quả.");
    });
  });
  $("favorite-record").addEventListener("click", () => perform($("favorite-record"), async () => {
    const item = await app.request("/api/history/" + state.selected.id, {method: "PATCH", body: {favorite: !state.selected.favorite}});
    displayRecord(item); await refresh();
  }));
  $("export-record").addEventListener("click", () => { if (state.selected) app.download(state.selected, "phishlens_" + state.selected.id + ".json"); });
  $("delete-record").addEventListener("click", () => perform($("delete-record"), async () => {
    if (!state.selected || !confirm("Xóa kết quả này khỏi lịch sử cùng phản hồi và nội dung đã chia sẻ kèm theo?")) return;
    await app.request("/api/history/" + state.selected.id, {method: "DELETE"}); state.selected = null; $("record-dialog").close(); await refresh(); app.notify("Đã xóa kết quả.");
  }));
  function field(form, title, id, type, value = "", readonly = false) {
    const label = n("label", "", title); label.htmlFor = id;
    const input = n("input"); input.id = id; input.type = type; input.value = value; input.required = true; input.readOnly = readonly;
    if (type === "password") { input.maxLength = 128; input.autocomplete = id === "current-password" ? "current-password" : "new-password"; }
    else input.maxLength = 80;
    form.append(label, input); return input;
  }
  async function accountPage() {
    const grid = n("div", "account-grid"), profile = panel("Thông tin cá nhân"), password = panel("Đổi mật khẩu");
    profile.append(n("p", "portal-muted", "Đã tham gia: " + app.date(app.user.created_at) + " · " + (app.user.role === "admin" ? "Quản trị viên" : "Thành viên")));
    const profileForm = n("form", "portal-form");
    field(profileForm, "Tên hiển thị", "profile-name", "text", app.user.display_name).autocomplete = "name";
    field(profileForm, "Email đăng nhập", "profile-email", "email", app.user.email, true);
    const save = n("button", "primary-button", "Lưu thông tin"); save.type = "submit"; profileForm.append(save); profile.append(profileForm);
    profileForm.addEventListener("submit", event => { event.preventDefault(); perform(save, async () => {
      const data = await app.request("/api/auth/profile", {method: "PATCH", body: {display_name: $("profile-name").value.trim()}}); app.user = data.user;
      document.querySelectorAll("[data-account-name]").forEach(el => { el.textContent = app.user.display_name; }); app.notify("Đã cập nhật thông tin.");
    }); });
    password.append(n("p", "portal-muted", "Mật khẩu mới từ 12 đến 128 ký tự. Sau khi đổi, các phiên đăng nhập cũ sẽ hết hiệu lực."));
    const passwordForm = n("form", "portal-form");
    field(passwordForm, "Mật khẩu hiện tại", "current-password", "password"); field(passwordForm, "Mật khẩu mới", "new-password", "password").minLength = 12;
    field(passwordForm, "Nhập lại mật khẩu mới", "repeat-password", "password").minLength = 12;
    const change = n("button", "primary-button", "Đổi mật khẩu"); change.type = "submit"; passwordForm.append(change); password.append(passwordForm);
    passwordForm.addEventListener("submit", event => { event.preventDefault(); perform(change, async () => {
      if ($("new-password").value !== $("repeat-password").value) throw new Error("Hai mật khẩu mới chưa trùng nhau.");
      await app.request("/api/auth/password", {method: "POST", body: {current_password: $("current-password").value, new_password: $("new-password").value}});
      passwordForm.reset(); app.notify("Đã đổi mật khẩu và kết thúc các phiên cũ.");
    }); });
    grid.append(profile, password); root.replaceChildren(grid);
    root.append(await window.PhishLensProduct.connectionsPanel());
  }
  async function adminPage() {
    const data = await app.request("/api/admin/users");
    const container = panel("Quản lý tài khoản");
    container.append(n("p", "portal-muted", `${data.items.length} tài khoản · Quản trị viên quản lý quyền truy cập, không xem lịch sử riêng của người dùng khác.`));
    for (const user of data.items) {
      const row = n("article", "admin-user"), info = n("div"), controls = n("div", "admin-controls"); row.dataset.userId = user.id;
      info.append(n("strong", "", user.display_name), n("p", "", user.email), n("p", "", "Tạo: " + app.date(user.created_at) + " · " + (user.active ? "Đang hoạt động" : "Đã khóa")));
      const role = n("select"); role.setAttribute("aria-label", "Quyền của " + user.email);
      for (const [value, text] of [["user", "Thành viên"], ["admin", "Quản trị viên"]]) { const option = n("option", "", text); option.value = value; role.append(option); }
      role.value = user.role; role.disabled = user.id === app.user.id;
      role.addEventListener("change", () => perform(role, async () => {
        if (!confirm("Thay đổi quyền của tài khoản " + user.email + "?")) { role.value = user.role; return; }
        await app.request("/api/admin/users/" + user.id, {method: "PATCH", body: {role: role.value}}); await adminPage(); app.notify("Đã cập nhật quyền.");
      }));
      const active = button(user.active ? "Khóa tài khoản" : "Mở khóa", user.active ? "danger-button" : "secondary-button", async () => {
        if (!confirm((user.active ? "Khóa" : "Mở khóa") + " tài khoản " + user.email + "?")) return;
        await app.request("/api/admin/users/" + user.id, {method: "PATCH", body: {active: !user.active}}); await adminPage(); app.notify("Đã cập nhật tài khoản.");
      }); active.disabled = user.id === app.user.id;
      controls.append(role, active); row.append(info, controls); container.append(row);
    }
    root.replaceChildren(container);
    await window.PhishLensProduct.feedbackPage(root, true);
  }
  app.ready.then(async () => {
    if (!app.user) return;
    const pages = {
      "/dashboard": ["Chào " + app.user.display_name + ".", "Một nơi để bắt đầu kiểm tra và xem lại những kết quả của bạn.", dashboard],
      "/history": ["Lịch sử kiểm tra", "Tìm, đánh dấu và quản lý các lượt kiểm tra của riêng bạn.", historyPage],
      "/account": ["Tài khoản của bạn", "Cập nhật thông tin cá nhân và bảo vệ quyền truy cập.", accountPage],
      "/feedback": ["Phản hồi của bạn", "Theo dõi góp ý và trả lời từ người quản lý ứng dụng.", () => { root.replaceChildren(); return window.PhishLensProduct.feedbackPage(root); }],
      "/admin": ["Quản trị ứng dụng", "Quản lý tài khoản trên máy chủ PhishLens này.", adminPage],
    };
    const [title, description, load] = pages[location.pathname] || pages["/dashboard"];
    $("portal-title").textContent = title; $("portal-description").textContent = description; document.title = title + " · PhishLens";
    await load(); root.setAttribute("aria-busy", "false");
    const id = new URLSearchParams(location.search).get("id"); if (id && location.pathname === "/history") await openRecord(id);
  }).catch(error => { $("portal-error").textContent = error.message; $("portal-error").hidden = false; root.setAttribute("aria-busy", "false"); });
})();
