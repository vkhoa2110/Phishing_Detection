"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const risks = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra thêm", LOW: "Chưa thấy dấu hiệu rõ ràng", UNKNOWN: "Chưa đủ thông tin"};
  const state = {connection: null, status: null, pending: null, busy: false, dirty: false, mode: "url", result: null,
    drafts: {url: "", text: "", image: ""}, aiPreferences: {url: false, text: true, image: true}, editRevision: 0, scrolls: {}, mailContext: null, mailMarks: null, aiSendMode: "review"};
  const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
  const icon = name => { const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), use = document.createElementNS(svg.namespaceURI, "use"); use.setAttribute("href", "#i-" + name); svg.append(use); svg.setAttribute("aria-hidden", "true"); return svg; };
  // A URL score is numeric, but has not been calibrated as real-world probability.
  // The LLM contract supplies an ordinal verdict only. Never synthesize its %.
  const validURLScore = url => url?.status === "ok" && typeof url.score === "number" && Number.isFinite(url.score) && url.score >= 0 && url.score <= 1;
  const percent = score => (score * 100).toLocaleString("vi-VN", {minimumFractionDigits: 1, maximumFractionDigits: 1}) + "%";
  function urlScore(url, compact = false) {
    if (!validURLScore(url)) return null;
    const panel = node("div", undefined, "model-score" + (compact ? " compact-score" : ""));
    const line = node("div", undefined, "model-score-heading"); line.append(node("span", "Điểm mô hình URL"), node("b", percent(url.score))); panel.append(line);
    const meter = node("div", undefined, "model-score-track " + url.risk_level), fill = node("span");
    meter.setAttribute("role", "meter"); meter.setAttribute("aria-label", "Điểm mô hình URL, chưa phải xác suất lừa đảo");
    meter.setAttribute("aria-valuemin", "0"); meter.setAttribute("aria-valuemax", "100"); meter.setAttribute("aria-valuenow", String(url.score * 100)); meter.setAttribute("aria-valuetext", percent(url.score));
    fill.style.width = url.score * 100 + "%"; meter.append(fill); panel.append(meter);
    panel.append(node("small", "Chưa phải xác suất lừa đảo đã kiểm chứng.", "score-note"));
    return panel;
  }
  function riskScale(level) {
    const positions = {LOW: 0, WARNING: 1, HIGH: 2}, current = positions[level];
    const scale = node("div", undefined, "risk-scale" + (current === undefined ? " uncertain" : ""));
    scale.setAttribute("role", "img"); scale.setAttribute("aria-label", current === undefined ? "Chưa xác định mức cảnh báo; không phải mức thấp hay 0 phần trăm" : "Mức cảnh báo " + risks[level] + "; thang ba mức, không phải phần trăm");
    for (const [index, label] of ["Thấp", "Cần kiểm tra", "Cao"].entries()) {
      const item = node("span", label, "risk-scale-step" + (index === current ? " selected" : ""));
      item.setAttribute("aria-hidden", "true"); scale.append(item);
    }
    return scale;
  }
  let images, ready = false, assistantState = null, pendingLocal = false, currentTabId = null, pendingReview = false, pendingRegion = false, lastMail = "", mailQueued = false, activeJob = null, hasIncoming = false;
  const mailOrigins = ["https://mail.google.com/*", "https://outlook.live.com/*", "https://outlook.office.com/*", "https://outlook.office365.com/*"];
  function showView(view) {
    const main = document.querySelector("main"), previous = document.body.dataset.view;
    state.scrolls[previous] = main.scrollTop;
    document.body.dataset.view = view;
    $("connection").hidden = view !== "connection"; $("assistant-screen").hidden = view !== "assistant";
    document.querySelectorAll("[data-view-target]").forEach(button => { if (button.dataset.viewTarget === view) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current"); });
    if (view === "assistant" || view === "check") updateAssistant().catch(() => {});
    main.scrollTop = state.scrolls[view] || 0;
  }
  document.querySelectorAll("[data-view-target]").forEach(button => button.addEventListener("click", () => showView(button.dataset.viewTarget)));
  function baseURL(value) {
    let url; try { url = new URL(value); } catch { throw new Error("Nhập địa chỉ ứng dụng, ví dụ http://127.0.0.1:8001."); }
    if (url.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error("Chỉ kết nối PhishLens tại http://127.0.0.1 hoặc http://localhost trên máy.");
    return url.origin;
  }
  function showError(message = "") { $("error").textContent = message; $("error").hidden = !message; if (message) $("error").scrollIntoView({block: "nearest"}); }
  function notify(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => { $("toast").hidden = true; }, 4500); }
  const mode = () => state.mode === "url" ? "url" : "text";
  function controls() {
    const stage = state.pending ? "review" : state.result ? "result" : "edit";
    const direct = state.aiSendMode === "direct";
    document.body.dataset.stage = stage;
    document.body.dataset.busy = String(state.busy);
    $("submit-area").hidden = stage !== "edit";
    $("review-actions").hidden = stage !== "review";
    $("result-navigation").hidden = stage !== "result";
    $("intro").hidden = stage !== "edit";
    $("check-form").hidden = stage !== "edit";
    $("review").hidden = stage !== "review";
    document.querySelectorAll("[data-step]").forEach(el => { if (el.dataset.step === stage) el.setAttribute("aria-current", "step"); else el.removeAttribute("aria-current"); });
    document.querySelector('[data-step="review"]').hidden = direct && !state.pending;
    document.querySelector('[data-step="result"] span').textContent = direct && !state.pending ? "2" : "3";
    document.querySelector("main").setAttribute("aria-busy", String(state.busy));
    for (const el of document.querySelectorAll("#check-form input, #check-form textarea, .input-tabs button, #check-form button, #review textarea")) el.disabled = state.busy;
    document.querySelectorAll(".input-tabs button").forEach(el => { el.disabled = state.busy || Boolean(state.pending); });
    $("analyze").disabled = state.busy || !state.status || !$("input-text").value.trim();
    $("analyze-label").textContent = state.busy ? "Đang xử lý…" : $("use-ai").checked ? direct ? "Phân tích ngay" : "Tiếp tục · Duyệt nội dung" : "Kiểm tra đường dẫn";
    $("include-ml").disabled = state.busy || !$("use-ai").checked;
    $("explain-evidence").disabled = state.busy || !$("use-ai").checked || mode() !== "text" || !state.status?.evidence_explanation_available;
    $("use-rag").disabled = state.busy || !$("use-ai").checked || mode() !== "text" || !state.status?.rag_ready;
    $("save-history").disabled = state.busy || Boolean(state.status?.guest);
    $("save-content").disabled = state.busy || Boolean(state.status?.guest) || !$("save-history").checked;
    $("read-image").disabled = state.busy || !images?.hasImage() || !state.status?.ocr?.ready;
    $("confirm").disabled = state.busy || !direct && !$("consent").checked;
    $("confirm-label").textContent = direct ? "Phân tích ngay" : "Đồng ý và phân tích";
    document.querySelector(".consent-label").hidden = direct;
    $("consent").disabled = state.busy;
    for (const id of ["connect", "disconnect", "settings-toggle", "cancel", "detach", "use-current-tab", "clear-input", "edit-result", "new-analysis", "quick-capture", "quick-viewport", "read-email", "mail-assist-enabled", "floating-enabled", "quick-page", "auto-check-enabled", "pause-assistant", "reset-hidden-sites", "send-review", "send-direct"]) $(id).disabled = state.busy;
    $("clear-input").hidden = !$("input-text").value;
    document.querySelectorAll("[data-view-target]").forEach(button => { button.disabled = state.busy; });
    $("input-count").textContent = $("input-text").value.length;
    $("submit-hint").textContent = $("use-ai").checked ? direct ? "Che thông tin rồi gửi AI" : "Duyệt nội dung ở bước tiếp theo" : "Kiểm tra URL tại máy";
    $("ai-description").textContent = $("use-ai").checked ? direct ? "Gửi khi bạn yêu cầu kiểm tra" : "Duyệt trước khi gửi" : "Phân tích dấu hiệu trong nội dung";
    $("send-provider").textContent = state.status?.model ? "Nội dung được che trước khi gửi tới " + state.status.model + "." : "Nội dung được che trước khi gửi tới dịch vụ AI đã cấu hình.";
    if (pendingLocal && ready && state.status && !state.busy) { pendingLocal = false; $("use-ai").checked = false; queueMicrotask(() => perform(prepareAnalysis, "Đang kiểm tra URL", "Mô hình chạy tại máy, không gọi AI.")); }
  }
  async function request(path, body = {}, credentials = state.connection, timeout = 90000) {
    if (!credentials) throw new Error("Mở PhishLens trên máy rồi bấm Kết nối và dùng ngay.");
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), timeout), binary = body instanceof Blob;
    try {
      const response = await fetch(credentials.base + "/api/extension/" + path, {method: "POST", credentials: "omit", cache: "no-store", signal: abort.signal,
        headers: {"Content-Type": binary ? body.type : "application/json", "X-PhishLens-Extension": chrome.runtime.id, ...(credentials.token ? {Authorization: "Bearer " + credentials.token} : {})}, body: binary ? body : JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401 && path !== "connect") {
          state.status = null; state.connection = null; $("connection").hidden = false; $("connection-status").textContent = "Kết nối tài khoản hết hạn · Dùng chế độ khách"; $("connection-dot").classList.remove("connected"); await clearConnection();
          showView("connection");
        }
        throw new Error(typeof data.detail === "string" ? data.detail : "Yêu cầu chưa hợp lệ.");
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Chưa nhận được phản hồi. Kiểm tra kết nối trước khi thử lại.");
      if (error instanceof TypeError) throw new Error("Chưa kết nối được PhishLens. Mở ứng dụng trên máy và kiểm tra địa chỉ trong Kết nối.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function clearConnection() { await Promise.all([chrome.storage.session.remove("connection"), chrome.storage.local.remove("connection")]); }
  async function perform(action, title = "Đang kiểm tra", description = "PhishLens đang xử lý nội dung bạn đã chọn.") {
    if (state.busy) return; state.busy = true; controls(); showError();
    $("progress-title").textContent = title; $("progress-description").textContent = description; $("progress").hidden = false;
    try { await action(); } catch (error) { showError(error.message); }
    finally { state.busy = false; $("progress").hidden = true; controls(); if (pendingRegion && ready && state.status) queueMicrotask(receiveRegion); else if (mailQueued && ready) { mailQueued = false; queueMicrotask(() => readEmail(true)); } }
  }
  async function session(timeout = 75000) {
    const data = await request("session", {}, state.connection, timeout);
    if (!data.user || typeof data.ml_ready !== "boolean") throw new Error("Địa chỉ này chưa phải dịch vụ PhishLens. Kiểm tra địa chỉ ứng dụng.");
    state.status = data;
    if (state.pending) { $("consent").checked = false; describeProvider(state.pending); }
    updateInputHint();
    const guest = Boolean(data.guest);
    $("history-option").hidden = $("content-option").hidden = guest;
    $("guest-history-note").hidden = !guest;
    $("connection-mode").textContent = guest ? "Khách" : data.user.display_name;
    if (guest) { $("save-history").checked = false; $("save-content").checked = false; }
    $("connection-status").textContent = (state.status.ml_ready ? "Sẵn sàng" : "URL chưa sẵn sàng");
    $("connection-dot").classList.add("connected"); $("connection").hidden = true; $("disconnect").hidden = false;
    showView("check");
    if (!state.status.ocr?.ready) $("ocr-status").textContent = state.status.ocr?.message || "Cần cập nhật backend để dùng đọc ảnh. Khởi động lại PhishLens.";
  }
  function clearMailMarks() {
    const marks = state.mailMarks; state.mailMarks = null;
    if (marks) chrome.runtime.sendMessage({type: "CLEAR_EMAIL_ANNOTATIONS", ...marks}).catch(() => {});
  }
  function forgetMail() { clearMailMarks(); state.mailContext = null; }
  function clearResult() { activeJob = null; clearMailMarks(); state.result = null; $("result").hidden = true; $("result").replaceChildren(); document.body.classList.remove("compact"); document.body.dataset.stage = "edit"; }
  function updateInputHint() {
    const limit = state.status?.limits?.urls;
    $("input-hint").textContent = state.mode === "url" ? "Kiểm tra chuỗi URL, không mở trang đích." :
      state.mode === "image" ? "OCR có thể sai dấu, số và URL. Bạn có thể sửa." :
      Number.isInteger(limit) && limit > 0 ? `Tối đa ${limit} URL khác nhau trong tin nhắn/email.` : "Nội dung bạn chọn · không đọc toàn bộ trang.";
  }
  function setTab(value, save = true, internal = false) {
    if (state.busy && !internal) return;
    if (value === state.mode && !internal) return;
    state.aiPreferences[state.mode] = $("use-ai").checked;
    if (save) state.drafts[state.mode] = $("input-text").value;
    state.editRevision++;
    showView("check");
    state.mode = value; $("input-text").value = state.drafts[value] || "";
    state.dirty = Boolean(state.drafts[value]);
    $("check-form").hidden = false;
    document.querySelectorAll("[data-mode]").forEach(el => { const active = el.dataset.mode === value; el.setAttribute("aria-selected", String(active)); el.tabIndex = active ? 0 : -1; });
    $("input-area").setAttribute("aria-labelledby", "tab-" + value);
    $("image-input").hidden = value !== "image"; $("text-input").hidden = value === "image" && !$("input-text").value;
    $("use-current-tab").hidden = value !== "url"; $("examples").hidden = value !== "text";
    $("input-label").textContent = value === "url" ? "Đường dẫn cần kiểm tra" : value === "image" ? "Chữ nhận dạng · hãy kiểm tra và sửa" : "Tin nhắn hoặc email đáng ngờ";
    updateInputHint();
    $("input-text").placeholder = value === "url" ? "https://duong-dan-ban-muon-kiem-tra…" : "Dán tin nhắn hoặc nội dung email vào đây…";
    $("use-ai").checked = state.aiPreferences[value]; clearResult(); showError(); controls();
  }
  document.querySelectorAll("[data-mode]").forEach(el => {
    el.addEventListener("click", () => setTab(el.dataset.mode));
    el.addEventListener("keydown", event => { const keys = ["url", "text", "image"], index = keys.indexOf(state.mode); if (["ArrowRight", "ArrowLeft"].includes(event.key)) { event.preventDefault(); const value = keys[(index + (event.key === "ArrowRight" ? 1 : 2)) % 3]; setTab(value); $("tab-" + value).focus(); } });
  });
  async function browserTab() {
    const win = await chrome.windows.getCurrent();
    if (win.type === "popup") {
      const identity = state.mailContext?.tabId || currentTabId;
      if (Number.isInteger(identity)) {
        try { const tab = await chrome.tabs.get(identity); if (tab.active && /^https?:\/\//i.test(tab.url || "")) return tab; } catch { /* The source tab was closed. */ }
      }
      const browser = await chrome.windows.getLastFocused({windowTypes: ["normal"]});
      return (await chrome.tabs.query({active: true, windowId: browser.id}))[0];
    }
    return (await chrome.tabs.query({active: true, windowId: win.id}))[0];
  }
  async function currentTab() {
    const tab = await browserTab();
    if (!/^https?:\/\//i.test(tab?.url || "")) throw new Error("Mở trang web rồi bấm biểu tượng PhishLens trên tab đó. Hoặc dán URL cần kiểm tra.");
    return tab.url;
  }
  $("use-current-tab").addEventListener("click", () => { currentTab().then(text => { $("input-text").value = text; state.dirty = true; state.editRevision++; clearResult(); controls(); }).catch(error => showError(error.message)); });
  const toggleSettings = () => showView(document.body.dataset.view === "connection" ? "check" : "connection");
  $("settings-toggle").addEventListener("click", toggleSettings); $("connection-pill").addEventListener("click", toggleSettings);
  $("open-app").addEventListener("click", () => { try { chrome.tabs.create({url: baseURL($("base-url").value) + "/check"}); } catch (error) { showError(error.message); } });
  $("home-link").addEventListener("click", event => { event.preventDefault(); if (state.connection) chrome.tabs.create({url: state.connection.base + "/check"}); else toggleSettings(); });
  $("theme-toggle").addEventListener("click", async () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = theme; await chrome.storage.local.set({theme});
  });
  function applySendMode(value) {
    state.aiSendMode = value === "direct" ? "direct" : "review";
    $("send-review").checked = state.aiSendMode === "review"; $("send-direct").checked = state.aiSendMode === "direct";
    // Changing a preference does not submit a draft already being reviewed.
    $("consent").checked = false; controls();
  }
  for (const id of ["send-review", "send-direct"]) $(id).addEventListener("change", async event => {
    if (!event.target.checked || state.busy) return;
    const previous = state.aiSendMode, next = event.target.value;
    applySendMode(next);
    try { await chrome.storage.local.set({aiSendMode: next}); }
    catch { applySendMode(previous); showError("Chưa lưu được cách gửi. Hãy thử lại."); }
  });
  $("detach").addEventListener("click", () => {
    const input = activeJob ? {job: activeJob} : {mode: mode(), text: $("input-text").value, mail: state.mailContext ? {context: state.mailContext} : null};
    chrome.runtime.sendMessage({type: "DETACH_WORKSPACE", input}).then(result => { if (result?.error) showError(result.error); }).catch(error => showError(error.message));
  });
  async function connectGuest(bases) {
    state.status = null;
    await clearConnection();
    for (const base of [...new Set(bases)]) {
      state.connection = {base, guest: true, expires_at: Date.now() / 1000 + 30 * 86400};
      try {
        // The first status call can load local model assets after a cold start.
        // Refused localhost connections still fail immediately.
        await session(20000);
        await chrome.storage.local.set({base, connection: state.connection, autoConnectDisabled: false});
        return;
      } catch { state.status = null; }
    }
    state.connection = null; $("connection-status").textContent = "Ứng dụng chưa sẵn sàng · Thử kết nối lại";
    showView("connection");
    throw new Error("Chưa kết nối được PhishLens. Mở ứng dụng trên máy rồi bấm Kết nối và dùng ngay; không cần mã hay tài khoản.");
  }
  $("connect-form").addEventListener("submit", event => { event.preventDefault(); perform(async () => {
    const base = baseURL($("base-url").value);
    await connectGuest([base]);
  }, "Đang kết nối ứng dụng", "Không cần mã hoặc tài khoản."); });
  $("disconnect").addEventListener("click", () => perform(async () => {
    const previous = state.connection;
    await chrome.storage.local.set({autoConnectDisabled: true});
    await clearConnection();
    state.connection = null; state.status = null; state.pending = null; images.clear(); forgetMail();
    $("connection").hidden = false; $("disconnect").hidden = true; $("review").hidden = true; $("check-form").hidden = false; clearResult();
    for (const key of Object.keys(state.drafts)) state.drafts[key] = ""; $("input-text").value = ""; $("approved-text").value = "";
    $("connection-status").textContent = "Đã tạm ngừng · Bấm để kết nối lại"; $("connection-dot").classList.remove("connected");
    pendingLocal = false; showView("connection");
    if (previous?.token) { try { await request("disconnect", {}, previous, 2500); } catch { /* Local access is already stopped. Account devices can also be revoked on the web. */ } }
  }));
  $("quick-page").addEventListener("click", async () => {
    try { const url = await currentTab(); setTab("url"); $("input-text").value = url; $("use-ai").checked = false; await perform(prepareAnalysis, "Đang kiểm tra URL", "Mô hình chạy tại máy, không gọi AI."); }
    catch (reason) { showError(reason.message); }
  });
  $("input-text").addEventListener("input", () => { forgetMail(); state.dirty = true; state.editRevision++; clearResult(); showError(); controls(); });
  for (const id of ["use-ai", "include-ml", "use-rag", "explain-evidence", "save-history", "save-content"]) $(id).addEventListener("change", () => { state.aiPreferences[state.mode] = $("use-ai").checked; clearResult(); controls(); });
  $("approved-text").addEventListener("input", () => { state.dirty = true; $("consent").checked = false; controls(); });
  for (const id of ["input-text", "approved-text"]) $(id).addEventListener("paste", event => {
    const pasted = event.clipboardData?.getData("text/plain");
    if (!pasted || event.clipboardData.items.length && [...event.clipboardData.items].some(item => item.kind === "file")) return;
    const input = $(id), length = input.value.length - (input.selectionEnd - input.selectionStart) + pasted.length;
    if (length > input.maxLength) { event.preventDefault(); showError("Nội dung vượt 8.000 ký tự. Hãy chọn phần cần kiểm tra; bản hiện tại được giữ lại."); return; }
    if (id === "input-text" && state.mode === "url" && !state.busy && !state.pending && /\s/.test(pasted.trim())) {
      event.preventDefault();
      if (state.drafts.text && state.drafts.text !== pasted && !confirm("Thay bản tin nhắn đang soạn bằng nội dung vừa dán?")) return;
      forgetMail(); setTab("text"); input.value = pasted; state.dirty = true; state.editRevision++; controls(); input.focus();
    }
  });
  $("consent").addEventListener("change", controls);
  function editInput(fromReview = false, fresh = false) {
    if (state.busy) return;
    if (fromReview) $("input-text").value = $("approved-text").value;
    state.pending = null; $("approved-text").value = ""; $("consent").checked = false;
    if (fresh) { forgetMail(); for (const key of Object.keys(state.drafts)) state.drafts[key] = ""; $("input-text").value = ""; images.clear(); lastMail = ""; }
    state.drafts[state.mode] = $("input-text").value;
    state.dirty = Boolean($("input-text").value); state.editRevision++;
    clearResult(); showError(); controls();
    $("text-input").hidden = state.mode === "image" && !$("input-text").value;
    document.querySelector("main").scrollTop = 0;
    if (!$("text-input").hidden) $("input-text").focus({preventScroll: true});
  }
  $("cancel").addEventListener("click", () => editInput(true));
  $("edit-result").addEventListener("click", () => editInput());
  $("new-analysis").addEventListener("click", () => editInput(false, true));
  $("clear-input").addEventListener("click", () => { forgetMail(); $("input-text").value = ""; state.drafts[state.mode] = ""; state.dirty = false; state.editRevision++; clearResult(); controls(); $("input-text").focus(); });
  document.addEventListener("keydown", event => {
    if (document.body.dataset.view !== "check" || state.busy) return;
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (state.pending) { if (!$("confirm").disabled) $("confirm").click(); else $("consent").focus(); }
      else if (!state.result && !$("analyze").disabled) $("check-form").requestSubmit();
    }
    if (event.key === "Escape" && state.pending) { event.preventDefault(); editInput(true); }
  });
  document.querySelectorAll("[data-example]").forEach(el => el.addEventListener("click", () => {
    forgetMail(); setTab("text"); $("input-text").value = el.dataset.example === "suspicious" ? "Tài khoản sắp bị khóa. Hãy gửi mã OTP cho nhân viên tại https://xac-minh.example/ để xác minh trong 10 phút." : "Nhắc cả nhóm: cuộc họp bắt đầu lúc 14 giờ thứ Sáu ở phòng học cũ. Mọi người chuẩn bị phần trình bày nhé.";
    notify("Đã điền mẫu minh họa tự soạn. Chưa chạy phân tích."); controls();
  }));
  async function prepareAnalysis({allowDirect = false} = {}) {
    const text = $("input-text").value.trim(); if (!text) throw new Error("Bạn chưa nhập nội dung hoặc chưa đọc chữ từ ảnh."); clearResult();
    const payload = {mode: mode(), text, use_llm: $("use-ai").checked, include_ml: $("use-ai").checked && $("include-ml").checked,
      use_rag: $("use-ai").checked && mode() === "text" && Boolean(state.status?.rag_ready) && $("use-rag").checked,
      save_history: !state.status?.guest && $("save-history").checked, save_content: $("save-history").checked && $("save-content").checked, consent: false};
    if (state.status?.evidence_explanation_available) payload.explain_evidence = payload.use_llm && mode() === "text" && $("explain-evidence").checked;
    if (!payload.use_llm) { render(await request("analyze", payload)); return; }
    if (!state.status?.llm_ready) throw new Error("Máy chủ chưa cấu hình AI. Bạn có thể tắt AI để kiểm tra URL tại máy.");
    const preview = await request("preview", {mode: payload.mode, text});
    if (typeof preview.text !== "string" || !preview.text.trim()) throw new Error("Chưa chuẩn bị được nội dung gửi AI. Hãy thử lại.");
    // The saved preference authorizes explicit check actions, not passive mail
    // changes, opening the panel, connection changes, or failed requests.
    if (allowDirect && state.aiSendMode === "direct") {
      $("progress-title").textContent = "Đang phân tích bằng AI";
      $("progress-description").textContent = "Đang phân tích nội dung đã che.";
      await analyzeApproved(payload, preview.text); return;
    }
    state.pending = payload;
    $("approved-text").value = preview.text; $("consent").checked = false;
    describeProvider(payload);
    $("masked-note").textContent = preview.masked_fields.length ? "Đã che một số thông tin riêng tư. Bạn có thể sửa bản bên dưới." : "Kiểm tra và xóa thông tin riêng tư trước khi gửi.";
    $("review").hidden = false; $("check-form").hidden = true; $("intro").hidden = true; $("review").scrollIntoView({block: "start"});
  }
  async function analyzeApproved(payload, text) {
    const job = await chrome.runtime.sendMessage({type: "START_ANALYSIS", payload: {...payload, consent: true, llm_text: text}, context: state.mailContext});
    if (typeof job?.error === "string") throw new Error(job.error);
    activeJob = job.record;
    const data = await waitForJob(job.record, job);
    state.pending = null; $("review").hidden = true; $("check-form").hidden = false; $("approved-text").value = ""; $("consent").checked = false; render(data);
  }
  async function waitForJob(record, initial = null) {
    let job = initial;
    while (true) {
      if (!job) job = await chrome.runtime.sendMessage({type: "ANALYSIS_STATUS", record});
      if (typeof job?.error === "string") throw new Error(job.error);
      if (job.status === "error") throw new Error(job.error?.message || "Chưa hoàn tất lượt kiểm tra.");
      if (job.status === "complete") return job.result;
      await new Promise(resolve => setTimeout(resolve, 900)); job = null;
    }
  }
  async function resumeJob(record) {
    if (state.busy) { if (activeJob?.id === record.id) showView("check"); else notify("Một kết quả đang mở. Đợi hoàn tất rồi bấm Chi tiết lại."); return; }
    forgetMail(); clearResult(); state.pending = null; pendingReview = false; activeJob = record;
    state.mailContext = record.context || null; showView("check");
    await perform(async () => {
      const data = await waitForJob(record);
      setTab(data.mode === "url" ? "url" : "text", true, true);
      activeJob = record;
      $("input-text").value = data.llm.input_used || ""; state.dirty = false;
      render(data);
    }, "Đang lấy kết quả", "Bạn có thể đóng bảng và tiếp tục đọc thư.");
  }
  function describeProvider(payload) {
    $("provider-note").textContent = "Bản chữ dưới đây được gửi tới " + state.status.model + "." + (state.mode === "image" ? " Ảnh gốc không được gửi." : "") + (payload.use_rag ? " Có đối chiếu tài liệu." : "");
  }
  $("check-form").addEventListener("submit", event => { event.preventDefault(); perform(() => prepareAnalysis({allowDirect: true}), "Chuẩn bị bản kiểm tra", "Đang che thông tin riêng tư."); });
  $("confirm").addEventListener("click", () => perform(async () => {
    if (!state.pending || state.aiSendMode !== "direct" && !$("consent").checked) return;
    const edited = $("approved-text").value;
    const checked = await request("preview", {mode: "text", text: edited});
    if (edited !== $("approved-text").value || state.aiSendMode !== "direct" && !$("consent").checked) return;
    if (checked.text !== edited && state.aiSendMode !== "direct") {
      $("approved-text").value = checked.text; $("consent").checked = false;
      throw new Error("Bản vừa sửa đã được che thêm. Hãy xem lại và xác nhận nội dung đang hiển thị.");
    }
    await analyzeApproved(state.pending, checked.text);
  }, "Đang phân tích bằng AI", "Đối chiếu dấu hiệu và tìm căn cứ từ bản bạn đã xác nhận. Có thể mất vài chục giây."));
  function mailResultTools(data, parent) {
    if (state.mode !== "text" || !state.mailContext) return;
    const context = state.mailContext, group = node("div", undefined, "mail-result-tools");
    const view = node("button", "Đang đánh dấu email…", "secondary"), hide = node("button", "Ẩn", "text-button"), note = node("small", "", "muted");
    view.type = hide.type = "button"; view.id = "mail-show-marks"; hide.id = "mail-hide-marks"; hide.hidden = true;
    group.append(view, hide, note); parent.append(group);
    const verdict = data.llm?.status === "ok" ? data.llm.verdict : null;
    const explanation = data.llm?.evidence_explanation?.status === "ok" ? data.llm.evidence_explanation : null;
    const evidence = (verdict?.evidence || []).map((item, index) => ({quote: item.quote, reason: explanation?.evidence?.find(note => note.index === index)?.explanation || item.reason}));
    let marks = null, reread = false;
    const stillCurrent = () => state.result === data && state.mailContext === context && group.isConnected;
    async function show(reveal = false) {
      if (!stillCurrent()) return;
      view.disabled = true; note.textContent = "";
      try {
        let result;
        if (marks) {
          result = await chrome.runtime.sendMessage({type: "FOCUS_EMAIL_ANNOTATION", ...marks});
          if (result?.error) { marks = null; state.mailMarks = null; }
        }
        if (!marks) {
          const attempt = {context, batchId: crypto.randomUUID()};
          state.mailMarks = attempt;
          result = await chrome.runtime.sendMessage({type: "ANNOTATE_EMAIL", ...attempt, evidence, urls: data.urls.map(item => ({url: item.url, risk_level: item.risk_level, status: item.status})), quiet: $("mail-assist-enabled").checked});
          if (!stillCurrent()) { chrome.runtime.sendMessage({type: "CLEAR_EMAIL_ANNOTATIONS", ...attempt}).catch(() => {}); return; }
          if (result?.error) { state.mailMarks = null; throw new Error(result.error); }
          marks = attempt;
          if (reveal) {
            const focused = await chrome.runtime.sendMessage({type: "FOCUS_EMAIL_ANNOTATION", ...marks});
            if (focused?.error) throw new Error(focused.error);
          }
        }
        if (!stillCurrent()) return;
        view.textContent = "Xem dấu hiệu trên thư"; hide.hidden = false;
        note.textContent = `${result.evidence} dấu hiệu · ${result.links} liên kết`;
      } catch (error) {
        if (stillCurrent()) { reread = error.message.includes("thay đổi"); view.textContent = reread ? "Kiểm tra email đang mở" : "Đánh dấu lại email"; hide.hidden = true; note.textContent = reread ? error.message : "Chọn lại tab email đã kiểm tra để xem đánh dấu."; }
      } finally { if (stillCurrent()) view.disabled = false; }
    }
    view.addEventListener("click", () => reread ? readEmail() : show(true));
    hide.addEventListener("click", () => { clearMailMarks(); marks = null; hide.hidden = true; view.textContent = "Đánh dấu lại email"; note.textContent = ""; });
    // This only reuses the completed analysis; it never calls a provider.
    queueMicrotask(show);
  }
  function render(data) {
    state.result = data; document.body.classList.add("compact"); $("intro").hidden = true;
    $("check-form").hidden = true;
    const result = $("result"); result.replaceChildren();
    const toolbar = node("div", undefined, "result-toolbar"), capture = node("button", "Khoanh vùng khác");
    capture.type = "button"; capture.id = "result-capture"; capture.prepend(icon("camera"));
    capture.addEventListener("click", () => startRegion()); toolbar.append(capture); result.append(toolbar);
    mailResultTools(data, result);
    const hero = node("div", undefined, "result-hero " + data.final.risk_level);
    hero.append(node("span", data.mode === "url" ? "KIỂM TRA ĐƯỜNG DẪN" : "PHÂN TÍCH NỘI DUNG", "section-kicker"));
    const heading = node("h2", data.final.label); heading.prepend(icon("shield")); hero.append(heading);
    const llm = data.llm, verdict = llm.status === "ok" ? llm.verdict : null;
    hero.append(riskScale(data.final.risk_level));
    if (data.mode === "url" && data.urls.length === 1) { const score = urlScore(data.urls[0]); if (score) hero.append(score); }
    hero.append(node("p", verdict?.summary || (llm.status === "error" ? llm.message : "Nhận định này dựa trên chuỗi đường dẫn. Bật AI để đánh giá hành vi trong thông điệp."))); result.append(hero);
    const grid = node("div", undefined, "assessment-grid");
    for (const [title, value, level] of [["KIỂM TRA ĐƯỜNG DẪN", data.urls.length ? risks[data.assessments.url.risk_level] || "Chưa chấm được" : "Không có URL", data.assessments.url.risk_level], ["PHÂN TÍCH AI", verdict ? risks[verdict.risk_level] : llm.status === "disabled" ? "Chưa dùng AI" : "Chưa hoàn tất", verdict?.risk_level]]) {
      const card = node("div", undefined, "assessment-card"); card.append(node("small", title), node("strong", value, "risk " + (level || ""))); grid.append(card);
      if (title === "KIỂM TRA ĐƯỜNG DẪN" && data.urls.length === 1 && data.mode !== "url") { const score = urlScore(data.urls[0], true); if (score) card.append(score); }

    }
    result.append(grid);

    if (verdict) {
      const analysis = node("section", undefined, "surface result-section"); analysis.append(node("h3", "Dấu hiệu trong nội dung"));
      const explanation = llm.evidence_explanation?.status === "ok" ? llm.evidence_explanation : null;
      if (explanation) {
        const note = node("div", undefined, "ai-explanation"); note.append(node("strong", "AI giải thích"), node("p", explanation.summary)); analysis.append(note);
      }
      if (!verdict.evidence?.length) analysis.append(node("p", "Chưa có đoạn trích làm căn cứ. Hãy kiểm tra thêm ngữ cảnh và nguồn gửi."));
      for (const [index, evidence] of (verdict.evidence || []).entries()) {
        const reason = explanation?.evidence.find(item => item.index === index)?.explanation || evidence.reason;
        const item = node("div", undefined, "evidence-item"); item.append(node("blockquote", evidence.quote), node("p", reason)); analysis.append(item);
      }
      if (llm.evidence_explanation?.status === "error") analysis.append(node("p", "Chưa có giải thích bổ sung. Kết quả phân loại và trích dẫn được giữ nguyên.", "micro"));
      result.append(analysis);
      if (verdict.recommended_actions?.length) {
        const section = node("section", undefined, "surface result-section"), list = node("ol", undefined, "actions-list"); section.append(node("h3", "Bạn nên làm gì tiếp theo?"));
        verdict.recommended_actions.forEach((text, index) => { const item = node("li"); item.append(node("span", index + 1), document.createTextNode(text)); list.append(item); }); section.append(list); result.append(section);
      }
    }
    if (data.urls.length || data.invalid_urls?.length) {
      const urls = node("details", undefined, "result-details"); urls.id = "url-details"; urls.append(node("summary", "Chi tiết đường dẫn · " + data.urls.length + " URL"));
      const search = node("input"); search.id = "url-search"; search.type = "search"; search.placeholder = "Tìm tên miền hoặc đường dẫn…"; search.setAttribute("aria-label", "Tìm trong URL đã kiểm tra");
      const empty = node("p", "Không có URL khớp tìm kiếm.", "muted"); empty.id = "url-empty"; empty.hidden = true;
      if (data.urls.length > 5) urls.append(search);
      for (const url of data.urls) {
        const row = node("div", url.url, "url-row"); row.append(node("strong", url.status === "ok" ? risks[url.risk_level] : "Chưa chấm được", "risk " + url.risk_level));
        const score = urlScore(url); if (score) row.append(score);
        if (validURLScore(url) && typeof url.high_threshold === "number" && Number.isFinite(url.high_threshold) && url.high_threshold >= 0 && url.high_threshold <= 1) row.append(node("small", "Ngưỡng cảnh báo cao của mô hình: " + percent(url.high_threshold), "score-note"));
        urls.append(row);
      }
      search.addEventListener("input", () => { const value = search.value.trim().toLocaleLowerCase(); let shown = 0;
        urls.querySelectorAll(".url-row").forEach((row, index) => { row.hidden = !data.urls[index].url.toLocaleLowerCase().includes(value); if (!row.hidden) shown++; });
        empty.hidden = shown > 0;
      }); urls.append(empty);
      for (const item of data.invalid_urls || []) urls.append(node("p", "URL chưa hợp lệ: " + (typeof item === "string" ? item : item.url || item.raw || "Xem lại đầu vào"))); result.append(urls);
    }
    const post = data.post_explanation;
    if (post && post.status !== "disabled") {
      const sources = node("details", undefined, "result-details"); sources.append(node("summary", "Đối chiếu nguồn tham khảo"));
      const support = post.status === "ok" ? post.explanation?.support || [] : [];
      for (const claim of support) sources.append(node("p", claim.document_id + ": " + claim.claim), node("blockquote", claim.source_quote), node("p", claim.scope_note));
      sources.append(node("p", support.length ? "Nguồn là tóm lược biên tập. Mức hỗ trợ ngữ nghĩa chưa được đánh giá độc lập; phần này giữ nguyên kết luận nội dung." : post.status === "error" ? "Chưa bổ sung được nguồn; kết luận nội dung được giữ nguyên." : "Chưa có nguồn đủ phù hợp.")); result.append(sources);
    }
    if (verdict) {
      const note = node("details", undefined, "score-explanation"); note.append(node("summary", "Cách đọc kết quả"));
      note.append(node("p", "AI hiện phân loại theo mức cảnh báo. Chưa có điểm số đã được kiểm chứng để quy đổi thành xác suất lừa đảo. Mức cao không tương đương một tỷ lệ % cố định; thiếu căn cứ cũng không có nghĩa là 0%.")); result.append(note);
    }
    const actions = node("div", undefined, "result-actions");
    if (data.history?.status === "saved") {
      const link = node("a", "Lịch sử & phản hồi ↗", "secondary"); link.href = state.connection.base + "/history?id=" + encodeURIComponent(data.history.id); link.target = "_blank"; link.rel = "noreferrer"; actions.append(link);
      result.append(node("p", data.history.content_saved ? "Đã lưu nội dung đã che và kết quả chi tiết." : "Đã lưu thông tin lượt kiểm tra; không lưu nội dung.", "result-meta"));
    }
    else if (data.history?.status === "error") result.append(node("p", data.history.message, "result-meta"));
    const download = node("button", "Tải JSON", "secondary"); download.type = "button"; download.addEventListener("click", () => {
      const uri = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"})), anchor = node("a"); anchor.href = uri; anchor.download = "phishlens_result.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(uri), 1000);
    }); actions.append(download); result.append(actions);
    const copy = node("button", "Sao chép tóm tắt", "new-check"); copy.type = "button";
    copy.addEventListener("click", () => {
      const text = ["PhishLens · " + data.final.label, "URL: " + (data.urls.length ? risks[data.assessments.url.risk_level] || "Chưa kết luận" : "Không có URL"),
        "Nội dung: " + (verdict ? risks[verdict.risk_level] : "Chưa có nhận định AI"), ...(verdict?.recommended_actions || []), "Kết quả hỗ trợ nhận diện, không bảo đảm an toàn."].join("\n");
      navigator.clipboard.writeText(text).then(() => notify("Đã sao chép tóm tắt, không kèm nội dung gốc hoặc URL."), () => showError("Chưa sao chép được. Bạn có thể tải kết quả JSON."));
    }); result.append(copy);
    result.hidden = false; result.scrollIntoView({block: "start"});
  }
  images = window.PhishLensImages({busy: () => state.busy, controls, request, perform, error: error => showError(error.message),
    editVersion: () => state.editRevision,
    canReplace: () => {
      if (document.body.dataset.view !== "check") return false;
      if ((state.pending || state.result || state.mode === "image" && state.dirty && $("input-text").value) && !confirm("Dùng ảnh mới và thay nội dung đang kiểm tra?")) return false;
      state.pending = null; $("approved-text").value = ""; $("consent").checked = false; clearResult(); controls(); return true;
    },
    selectImage: () => setTab("image"), input: () => $("input-text").value,
    clearInput: () => { $("input-text").value = ""; state.drafts.image = ""; state.dirty = false; state.editRevision++; if (state.mode === "image") $("text-input").hidden = true; clearResult(); controls(); },
    setInput: text => { forgetMail(); $("input-text").value = text; state.drafts.image = text; state.dirty = Boolean(text); state.editRevision++; clearResult(); controls(); }});
  async function startRegion(captureMode = "region") {
    if (state.busy) return;
    showError();
    try {
      if (!state.status) throw new Error("Kết nối PhishLens đang chạy trên máy trước khi khoanh vùng để đọc chữ.");
      const tab = await browserTab();
      const result = await chrome.runtime.sendMessage({type: "START_REGION", tabId: tab?.id, captureMode: captureMode === "viewport" ? "viewport" : "region"});
      if (result?.error) throw new Error(result.error);
      notify("Kéo chuột trên trang để khoanh vùng · Esc để hủy.");
    } catch (reason) { showError(reason.message); }
  }
  $("quick-capture").addEventListener("click", () => startRegion()); $("capture-tab").addEventListener("click", () => startRegion());
  $("quick-viewport").addEventListener("click", () => startRegion("viewport"));
  async function readEmail(automatic = false) {
    if (state.busy || !state.status) { if (automatic) mailQueued = Boolean(state.status); return; }
    if (automatic && state.dirty) return;
    await perform(async () => {
      const tab = await browserTab();
      const mail = await chrome.runtime.sendMessage({type: "READ_EMAIL", tabId: tab?.id});
      if (mail?.error) throw new Error(mail.error);
      if (automatic && mail.text === lastMail) return;
      if (state.dirty && !confirm("Thay bản đang chỉnh sửa bằng email đang mở?")) return;
      $("review").hidden = true; state.pending = null; $("consent").checked = false; $("approved-text").value = "";
      forgetMail(); setTab("text", true, true); state.mailContext = mail.context; $("input-text").value = mail.text; state.dirty = false; lastMail = mail.text; $("use-ai").checked = true;
      if (state.status.llm_ready && (!automatic || state.aiSendMode !== "direct")) await prepareAnalysis({allowDirect: !automatic});
      else if (state.status.llm_ready) controls();
      else { controls(); notify("Đã lấy email. Máy chủ chưa cấu hình AI."); }
    }, "Đang lấy email đang mở", "Chỉ lấy nội dung thư và các đường dẫn trong thư.");
  }
  $("read-email").addEventListener("click", () => readEmail());
  $("mail-assist-enabled").addEventListener("change", async () => {
    try {
      const enabled = $("mail-assist-enabled").checked;
      if (enabled && !await chrome.permissions.request({origins: mailOrigins})) throw new Error("Chưa cấp quyền Gmail/Outlook.");
      const result = await chrome.runtime.sendMessage({type: "SET_MAIL_ASSIST", enabled});
      if (result?.error) throw new Error(result.error);
      $("mail-assist-enabled").checked = result.enabled;
      if (result.enabled && !$("mail-actions").hidden) queueMicrotask(() => readEmail(true));
    } catch (reason) { $("mail-assist-enabled").checked = false; showError(reason.message); }
  });
  async function updateAssistant() {
    const tab = await browserTab(); currentTabId = tab?.id;
    const config = await chrome.runtime.sendMessage({type: "GET_ASSISTANT", tabId: tab?.id});
    if (!config || config.error) return;
    assistantState = config;
    const mailSettings = await chrome.runtime.sendMessage({type: "GET_MAIL_SETTINGS"});
    $("mail-assist-enabled").checked = Boolean(mailSettings?.enabled);
    $("mail-actions").hidden = !mailOrigins.some(origin => tab?.url?.startsWith(origin.slice(0, -1)));
    $("floating-enabled").checked = config.floatingEnabled; $("auto-check-enabled").checked = config.autoCheckEnabled;
    $("floating-note").textContent = config.floatingEnabled ? "Nút ở góc trang · Kéo để đổi vị trí; mở menu để ẩn hoặc tạm nghỉ." : "Tùy chọn · Khoanh nhanh bằng Alt + Shift + S";
    $("assistant-status-title").textContent = config.pausedUntil ? "Trợ lý đang tạm nghỉ" : config.autoCheckEnabled ? "Tự kiểm URL đang bật" : config.floatingEnabled ? "Sẵn sàng ngay trên trang" : "Chọn cách dùng PhishLens";
    $("assistant-status-note").textContent = !config.connected ? "Mở ứng dụng PhishLens trên máy để dùng phân tích và OCR." : config.pausedUntil ? "Tự tiếp tục sau " + new Date(config.pausedUntil).toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"}) + ". Bạn có thể bật lại bất kỳ lúc nào." : config.autoCheckEnabled ? "URL được chấm tại máy khi mở trang. Nội dung và ảnh vẫn chờ bạn chọn." : "Nội dung chỉ được đọc khi bạn chủ động chọn kiểm tra.";
    if (mailSettings?.enabled) { $("assistant-status-note").textContent = "Email đang mở được đưa vào bản duyệt. AI chờ bạn xác nhận."; if (!config.autoCheckEnabled && !config.floatingEnabled) $("assistant-status-title").textContent = "Trợ lý email đang bật"; }
    $("pause-assistant").querySelector("span").textContent = config.pausedUntil ? "Bật lại trợ lý" : "Tạm nghỉ 1 giờ";
    $("reset-hidden-sites").textContent = config.hiddenCount ? "Hiện lại trên " + config.hiddenCount + " trang đã ẩn" : "Hiện lại trên các trang đã ẩn";
    let host = "Chọn một tab web"; try { if (/^https?:/.test(tab?.url)) host = new URL(tab.url).hostname; } catch { /* Unsupported tabs remain manual. */ }
    $("current-page").hidden = !/^https?:\/\//.test(tab?.url || "");
    $("page-host").textContent = host;
    const status = config.page || {}, messages = {idle: "Chưa kiểm tra URL trang này.", checking: "Đang kiểm tra URL tại máy…", disconnected: "Cần kết nối PhishLens trên máy.", unavailable: "Chưa kiểm tra được. Bạn có thể thử thủ công."};
    $("page-status").textContent = config.pausedUntil ? "Trợ lý đang tạm nghỉ." : status.status === "ok" ? ({HIGH: "URL có dấu hiệu rủi ro · cần xác minh.", WARNING: "URL cần kiểm tra thêm.", LOW: "Chưa thấy dấu hiệu rõ trong chuỗi URL.", UNKNOWN: "Chưa đủ căn cứ kết luận về URL."}[status.risk] || "Chưa có kết luận.") : messages[status.status] || messages.idle;
    $("page-indicator").className = "page-indicator " + (!config.pausedUntil && status.status === "ok" ? status.risk : "");
  }
  for (const [id, key] of [["floating-enabled", "floatingEnabled"], ["auto-check-enabled", "autoCheckEnabled"]]) $(id).addEventListener("change", async () => {
    const enabled = $(id).checked;
    try {
      // Must request native permissions inside this user's checkbox gesture.
      if (enabled && !await chrome.permissions.request({origins: ["<all_urls>"]})) throw new Error("Chưa cấp quyền trang web. Bạn vẫn có thể kiểm tra thủ công bằng biểu tượng PhishLens.");
      const response = await chrome.runtime.sendMessage({type: "CONFIGURE_ASSISTANT", key, enabled});
      if (response?.error) throw new Error(response.error);
      await updateAssistant(); notify(enabled ? "Đã bật hỗ trợ. Bạn có thể tắt bất kỳ lúc nào." : "Đã tắt tùy chọn.");
    } catch (reason) { $(id).checked = false; showError(reason.message); }
  });
  $("pause-assistant").addEventListener("click", async () => {
    const response = await chrome.runtime.sendMessage({type: "ASSISTANT_PAUSE", paused: !assistantState?.pausedUntil, tabId: currentTabId});
    if (response?.error) showError(response.error); else { await updateAssistant(); notify(assistantState.pausedUntil ? "Đã tạm nghỉ 1 giờ." : "Trợ lý đã sẵn sàng trở lại."); }
  });
  $("reset-hidden-sites").addEventListener("click", async () => {
    const response = await chrome.runtime.sendMessage({type: "RESET_HIDDEN_SITES"});
    if (response?.error) showError(response.error); else { await updateAssistant(); notify("Đã cho phép hiện lại nút trên các trang."); }
  });
  chrome.tabs.onActivated.addListener(() => { updateAssistant().catch(() => {}); });
  chrome.tabs.onUpdated.addListener((id, change) => { if (id === currentTabId && change.status === "complete") updateAssistant().catch(() => {}); });
  async function receiveRegion() {
    if (!ready || state.busy || !state.status) { pendingRegion = true; return; }
    pendingRegion = false;
    if (!["panel", "capture"].some(key => new URLSearchParams(location.search).has(key))) return;
    const windowId = (await chrome.windows.getCurrent()).id;
    const result = await chrome.runtime.sendMessage({type: "TAKE_REGION", windowId});
    if (!result?.dataURL) return;
    if (state.busy) { showError("Một lượt kiểm tra đang chạy. Hãy khoanh lại sau khi hoàn tất."); return; }
    if (!state.status) { showError("Vùng đã chọn chưa được gửi đi. Hãy mở ứng dụng PhishLens trên máy, rồi khoanh lại để đọc chữ."); $("connection").hidden = false; return; }
    if ((state.pending || state.dirty || state.result) && !confirm("Đọc vùng vừa khoanh và thay nội dung hiện tại?")) return;
    state.pending = null; $("review").hidden = true; $("approved-text").value = ""; $("consent").checked = false;
    images.clear(); $("input-text").value = ""; state.dirty = false; clearResult();
    const raw = Uint8Array.from(atob(result.dataURL.split(",")[1]), character => character.charCodeAt(0));
    await images.load(new File([raw], result.captureMode === "viewport" ? "Vung-hien-thi.png" : "Vung-vua-khoanh.png", {type: "image/png"}), result.captureMode === "viewport" ? "Toàn vùng hiển thị" : "Vùng vừa khoanh trên trang");
    await perform(async () => {
      const text = await images.read(false);
      if (text && state.status.llm_ready) await prepareAnalysis({allowDirect: true});
    }, "Đang đọc vùng bạn chọn", "Chỉ vùng vừa khoanh được đọc tại máy. Hãy duyệt chữ trước khi gửi AI.");
  }
  chrome.runtime.onMessage.addListener((message, sender) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message.type === "ASSISTANT_CHANGED" && message.tabId === currentTabId) updateAssistant().catch(() => {});
    if (message.type === "REGION_AVAILABLE") chrome.windows.getCurrent().then(win => { if (win.id === message.windowId) receiveRegion().catch(reason => showError(reason.message)); });
    if (message.type === "EMAIL_CHANGED" && ready && $("mail-assist-enabled").checked && message.tabId === currentTabId) {
      $("consent").checked = false; $("confirm").disabled = true;
      if (state.busy) mailQueued = true; else readEmail(true);
    }
    if (message.type === "CAPTURE_ERROR") chrome.windows.getCurrent().then(win => { if (message.windowId === undefined || win.id === message.windowId) showError(message.message); });
  });
  async function acceptInput(input) {
    if (!input || input.created < Date.now() - 600000) return false;
    if (input.targetWindowId !== undefined && (await chrome.windows.getCurrent()).id !== input.targetWindowId) return null;
    if (input.windowId !== undefined && (await chrome.windows.getCurrent()).id !== input.windowId) return null;
    hasIncoming = true;
    if (input.job) { if (!ready) { incomingJob = input.job; return true; } await resumeJob(input.job); return true; }
    if (state.busy) { notify("Một lượt kiểm tra đang chạy. Hãy chọn lại đoạn sau khi có kết quả."); return false; }
    if ((state.pending || state.dirty && $("input-text").value.trim() !== input.text) && !confirm("Thay nội dung đang kiểm tra bằng phần bạn vừa chọn?")) return false;
    $("review").hidden = true; $("check-form").hidden = false; state.pending = null; $("approved-text").value = ""; $("consent").checked = false;
    activeJob = null; forgetMail(); clearResult(); setTab(input.mode === "url" ? "url" : "text"); state.mailContext = input.mail?.context || null; $("input-text").value = input.text || ""; if (input.warning) showError(input.warning);
    if (input.review && input.mode === "text") pendingReview = true;
    if (input.autoLocal && input.mode === "url") pendingLocal = true;
    controls(); showView("check");
    if (pendingReview && ready && state.status?.llm_ready) { pendingReview = false; await perform(() => prepareAnalysis({allowDirect: true}), "Chuẩn bị email", "Đang che thông tin riêng tư."); }
    return true;
  }
  let incomingJob = null;
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.aiSendMode) applySendMode(changes.aiSendMode.newValue);
    if (area === "session" && changes.panelInput?.newValue && new URLSearchParams(location.search).has("panel")) acceptInput(changes.panelInput.newValue).then(result => { if (result !== null) chrome.storage.session.remove("panelInput"); });
    if (area === "session" && changes.workspaceInput?.newValue) acceptInput(changes.workspaceInput.newValue).then(result => { if (result !== null) chrome.storage.session.remove("workspaceInput"); });
  });
  (async () => {
    await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
    const preferences = await chrome.storage.local.get(["base", "theme", "connection", "floatingEnabled", "autoConnectDisabled", "aiSendMode"]), memory = await chrome.storage.session.get(["connection", "panelInput", "workspaceInput", "analysisCurrent"]);
    applySendMode(preferences.aiSendMode);
    document.documentElement.dataset.theme = preferences.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    if (preferences.base) $("base-url").value = baseURL(preferences.base);
    $("floating-enabled").checked = Boolean(preferences.floatingEnabled && await chrome.permissions.contains({origins: ["<all_urls>"]}));
    if ($("floating-enabled").checked) $("floating-note").textContent = "Nút ở góc trang · Chỉ đọc vùng bạn chủ động chọn";
    const key = location.hash.slice(1); history.replaceState(null, "", location.pathname + location.search);
    if (/^input-[a-f0-9-]{36}$/.test(key)) {
      const stored = await chrome.storage.session.get(key); await chrome.storage.session.remove(key); await acceptInput(stored[key]);
    } else if (memory.workspaceInput?.targetWindowId === (await chrome.windows.getCurrent()).id) {
      if (await acceptInput(memory.workspaceInput) !== null) await chrome.storage.session.remove("workspaceInput");
    } else if (new URLSearchParams(location.search).has("panel")) {
      if (memory.panelInput) { if (await acceptInput(memory.panelInput) !== null) await chrome.storage.session.remove("panelInput"); }
      else { try { $("input-text").value = await currentTab(); } catch { /* Paste input remains available on restricted pages. */ } }
    }
    const connection = preferences.connection || memory.connection;
    if (preferences.autoConnectDisabled) {
      await clearConnection(); showView("connection"); $("connection-status").textContent = "Đã tạm ngừng kết nối";
    } else if (connection && !connection.guest && connection.expires_at * 1000 > Date.now()) {
      try { state.connection = {...connection, base: baseURL(connection.base)}; await session(); }
      catch { await connectGuest([baseURL(preferences.base || $("base-url").value), "http://127.0.0.1:8001", "http://127.0.0.1:8000"]); }
    } else {
      await connectGuest([baseURL(preferences.base || $("base-url").value), "http://127.0.0.1:8001", "http://127.0.0.1:8000"]);
    }
    if (!hasIncoming && memory.analysisCurrent && Date.now() - memory.analysisCurrent.created < 900000) incomingJob = memory.analysisCurrent;
  })().catch(error => { showView("connection"); showError(error.message); }).finally(() => {
    ready = true; controls();
    if (incomingJob && state.status) { const job = incomingJob; incomingJob = null; resumeJob(job); }
    updateAssistant().then(() => { if ($("mail-assist-enabled").checked && !$("mail-actions").hidden && !pendingReview && !activeJob) readEmail(true); }).catch(() => {}); receiveRegion().catch(reason => showError(reason.message));
    if (pendingReview && state.status?.llm_ready) { pendingReview = false; perform(() => prepareAnalysis({allowDirect: true}), "Chuẩn bị email", "Đang che thông tin riêng tư."); }
  });
})();
