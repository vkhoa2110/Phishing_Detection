"use strict";
const $ = (id) => document.getElementById(id);
const state = {mode: "text", busy: false, pending: null, result: null, hasKey: false};
const labels = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra thêm", LOW: "Chưa thấy dấu hiệu rõ ràng", UNKNOWN: "Chưa đủ thông tin"};
const samples = {
  suspicious: "Tài khoản của bạn sắp bị khóa. Hãy trả lời ngay tin nhắn này với mật khẩu và mã OTP để xác minh. Nếu không hoàn tất trong 10 phút, chúng tôi sẽ ngừng dịch vụ.",
  normal: "Chào bạn, buổi họp nhóm tuần này bắt đầu lúc 14 giờ thứ Sáu tại phòng học cũ. Bạn vui lòng chuẩn bị phần công việc đã thực hiện để cùng trao đổi nhé.",
};

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function errorBox(id, message = "") { $(id).textContent = message; $(id).hidden = !message; }
function updateCount() { $("char-count").textContent = $("input-text").value.length.toLocaleString("vi-VN"); }
function keyStatus() {
  $("key-status").textContent = $("api-key").value.trim() ? "Key cho phiên hiện tại" : state.hasKey ? "Đã có key trong .env" : "Chưa nhập API key";
}
function updateOptions() {
  $("include-ml").disabled = !$("use-llm").checked || state.busy;
  ["endpoint", "llm-model", "api-key", "show-key"].forEach(id => { $(id).disabled = !$("use-llm").checked || state.busy; });
  document.querySelector(".privacy-note").hidden = !$("use-llm").checked;
}
function busy(value) {
  state.busy = value;
  $("analysis-form").querySelectorAll("input,textarea,button").forEach(el => { el.disabled = value; });
  $("reload-model").disabled = value;
  $("button-label").textContent = value ? "Đang xử lý…" : "Phân tích nội dung";
  updateOptions();
}
async function api(path, data, timeoutMs = 65000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {method: data === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data), signal: controller.signal, cache: "no-store"});
    let body;
    try { body = await response.json(); } catch { throw new Error("Ứng dụng trả phản hồi chưa hợp lệ. Kiểm tra cửa sổ chạy Python."); }
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Chưa xử lý được yêu cầu.");
    return body;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Đã hết thời gian chờ ứng dụng. Kiểm tra kết nối và thử lại sau.");
    if (err instanceof TypeError) throw new Error("Mất kết nối tới ứng dụng. Kiểm tra run.py có còn chạy không.");
    throw err;
  } finally { clearTimeout(timer); }
}
function modelStatus(ml) {
  $("model-status").textContent = ml.ready ? `${ml.run_id || ml.kind} · ${ml.feature_count} đặc trưng` : ml.message;
  $("model-status").title = ml.message;
}
async function init() {
  try {
    const status = await api("/api/status", undefined, 30000);
    modelStatus(status.ml);
    $("endpoint").value = status.llm.endpoint;
    $("llm-model").value = status.llm.model;
    $("llm-name").textContent = status.llm.model;
    state.hasKey = status.llm.has_api_key;
    $("api-status").textContent = state.hasKey ? "Đã cấu hình key · Chưa dùng RAG" : "Nhập API key để dùng · Chưa dùng RAG";
    $("api-dot").classList.toggle("ready", state.hasKey);
    keyStatus();
    errorBox("connection-error");
  } catch (err) { errorBox("connection-error", err.message); }
}
function setMode(mode) {
  state.mode = mode;
  $("tab-url").classList.toggle("active", mode === "url");
  $("tab-text").classList.toggle("active", mode === "text");
  $("tab-url").setAttribute("aria-pressed", String(mode === "url"));
  $("tab-text").setAttribute("aria-pressed", String(mode === "text"));
  $("input-label").textContent = mode === "url" ? "Đường dẫn cần kiểm tra" : "Nội dung email hoặc tin nhắn";
  $("input-hint").textContent = mode === "url" ? "Phân tích chuỗi URL, không mở trang đích" : "Tối đa 5 URL trong một nội dung";
  $("input-text").placeholder = mode === "url" ? "https://example.org/" : "Dán nội dung tại đây. Có thể chứa hoặc không chứa đường dẫn…";
  $("input-text").value = "";
  resetResult(); updateCount(); errorBox("form-error");
}
function resetResult() {
  state.result = null;
  $("empty-state").hidden = false;
  $("result-content").hidden = true;
  $("loading-state").hidden = true;
  $("download-result").hidden = true;
}
function section(title, count) {
  const el = node("section", "result-section");
  const h = node("h4", "", title);
  if (count !== undefined) h.append(node("span", "count-badge", String(count)));
  el.append(h);
  return el;
}
function component(name, title, detail) {
  const el = node("div", "component");
  el.append(node("div", "component-name", name), node("h4", "", title), node("p", "", detail));
  return el;
}
function render(data) {
  state.result = data;
  const target = $("result-content"); target.replaceChildren();
  const banner = node("div", `verdict ${data.final.risk_level}`);
  const meta = node("div", "verdict-eyebrow");
  meta.append(node("span", "", "KẾT QUẢ TỔNG HỢP"), node("span", "", `${(data.timing.total_ms / 1000).toFixed(2)} giây`));
  banner.append(meta, node("h3", "", data.final.label), node("p", "", data.final.basis));
  target.append(banner);
  if (data.final.conflict) target.append(node("p", "conflict-note", "ML và LLM đưa ra nhận định khác nhau. Ứng dụng giữ cảnh báo cần thiết và hiển thị riêng hai kết quả bên dưới."));
  const parts = node("div", "components");
  const count = data.urls.filter(u => u.status === "ok").length;
  parts.append(component("MÔ HÌNH ML", count ? `${count} / ${data.urls.length} URL đã phân tích` : data.urls.length ? "Chưa nạp được mô hình" : "Không có URL", count ? `${data.ml.run_id} · ${data.ml.feature_count} đặc trưng` : data.urls.length ? data.ml.message : "Phần ML được bỏ qua cho đầu vào này."));
  const llm = data.llm;
  parts.append(component("MÔ HÌNH LLM", llm.status === "ok" ? labels[llm.verdict.risk_level] : llm.status === "disabled" ? "Chưa bật LLM" : "Chưa có kết quả", llm.status === "ok" ? `${llm.model} · ${llm.included_ml ? "Có" : "Không kèm"} kết quả ML · Không RAG` : llm.message));
  target.append(parts);
  if (data.urls.length) {
    const urls = section("Đường dẫn được phát hiện", data.urls.length);
    for (const item of data.urls) {
      const card = node("div", "url-item"), head = node("div", "url-heading");
      head.append(node("span", "", item.id), node("span", `risk-badge ${item.risk_level || "UNKNOWN"}`, item.status === "ok" ? labels[item.risk_level] : "Chưa đánh giá"));
      card.append(head, node("code", "url-text", item.url));
      if (item.status === "ok") {
        const row = node("div", "score-row"); row.append(node("span", "", "Điểm phân loại ML"), node("strong", "", item.score.toFixed(4)));
        const bar = node("progress"); bar.max = 1; bar.value = item.score; bar.setAttribute("aria-label", `Điểm phân loại ${item.score.toFixed(4)}`);
        card.append(row, bar, node("p", "threshold-note", `Ngưỡng cảnh báo ${Number(item.warning_threshold).toFixed(4)} · Ngưỡng cao ${item.high_threshold === null ? "chưa thiết lập" : Number(item.high_threshold).toFixed(4)}`));
      } else card.append(node("p", "inline-warning", item.message));
      urls.append(card);
    }
    urls.append(node("p", "result-subtle", "Điểm mô hình không phải xác suất lừa đảo đã hiệu chỉnh.")); target.append(urls);
  }
  if (data.invalid_urls.length) {
    const invalid = section("Đường dẫn chưa xử lý", data.invalid_urls.length);
    for (const url of data.invalid_urls) invalid.append(node("code", "url-text", url));
    target.append(invalid);
  }
  if (llm.status === "ok") {
    const analysis = section("Nhận định từ nội dung"); analysis.append(node("p", "analysis-summary", llm.verdict.summary));
    llm.warnings.forEach(w => analysis.append(node("p", "inline-warning", w))); target.append(analysis);
    const evidence = section("Dấu hiệu làm căn cứ", llm.verdict.evidence.length);
    if (!llm.verdict.evidence.length) evidence.append(node("p", "result-subtle", "Không có dấu hiệu cụ thể được trích ra từ bản nội dung đã gửi."));
    for (const item of llm.verdict.evidence) {
      const el = node("div", "evidence-item"); el.append(node("blockquote", "", `“${item.quote}”`), node("p", "", item.reason)); evidence.append(el);
    }
    target.append(evidence);
    if (llm.verdict.recommended_actions.length) {
      const actions = section("Bạn có thể làm gì?"); const list = node("ol", "actions-list");
      llm.verdict.recommended_actions.forEach(action => list.append(node("li", "", action))); actions.append(list); target.append(actions);
    }
    const details = node("details", "payload-details"); details.append(node("summary", "", "Xem bản nội dung đã gửi tới LLM"), node("pre", "", llm.input_used)); target.append(details);
  } else if (llm.status === "error") target.append(node("p", "inline-warning", llm.message));
  const note = node("div", "result-note", data.notice);
  if (llm.status === "ok" && llm.usage.total_tokens) note.append(node("div", "", `${llm.usage.total_tokens.toLocaleString("vi-VN")} token · ${llm.prompt_version} · Không lưu lịch sử nội dung`));
  target.append(note);
  $("loading-state").hidden = true; $("empty-state").hidden = true; target.hidden = false; $("download-result").hidden = false;
}
async function analyze(payload) {
  busy(true); errorBox("form-error");
  $("empty-state").hidden = true; $("result-content").hidden = true; $("download-result").hidden = true; $("loading-state").hidden = false;
  $("loading-message").textContent = payload.use_llm ? "Đang phân tích và chờ phản hồi từ API FPT…" : "Đang trích xuất đặc trưng và phân loại URL tại máy chạy ứng dụng…";
  try { render(await api("/api/analyze", payload)); }
  catch (err) { resetResult(); errorBox("form-error", err.message); }
  finally { busy(false); }
}
$("analysis-form").addEventListener("submit", async event => {
  event.preventDefault(); if (state.busy) return;
  const text = $("input-text").value.trim(); errorBox("form-error");
  if (!text) { errorBox("form-error", "Bạn chưa nhập nội dung cần kiểm tra."); return; }
  const payload = {mode: state.mode, text, use_llm: $("use-llm").checked, include_ml: $("include-ml").checked, endpoint: $("endpoint").value.trim(), model: $("llm-model").value.trim(), api_key: $("api-key").value.trim(), consent: false};
  if (!payload.use_llm) { await analyze(payload); return; }
  if (!payload.api_key && !state.hasKey) { document.querySelector(".api-settings").open = true; errorBox("form-error", "Nhập API key trong Kết nối LLM hoặc tắt LLM để chỉ kiểm tra URL."); $("api-key").focus(); return; }
  busy(true);
  try {
    const preview = await api("/api/preview", {mode: state.mode, text}, 15000);
    state.pending = payload;
    $("preview-text").value = preview.text;
    $("masked-fields").textContent = preview.masked_fields.length ? "Đã che theo quy tắc: " + preview.masked_fields.join(" · ") : "Chưa phát hiện trường cần che bằng các quy tắc hiện tại. Bạn vẫn cần kiểm tra bản gửi.";
    $("preview-ml-note").textContent = payload.include_ml ? "Nếu có URL, kết quả ML và URL đã che cũng được gửi. Bản gốc chỉ dùng để phân loại URL tại máy chạy ứng dụng." : "Chỉ gửi bản nội dung ở trên. Không cung cấp điểm hoặc kết luận ML cho LLM.";
    $("consent").checked = false; $("confirm-send").disabled = true; errorBox("preview-error");
    $("privacy-dialog").showModal();
  } catch (err) { errorBox("form-error", err.message); }
  finally { busy(false); }
});
$("confirm-send").addEventListener("click", async () => {
  if (!state.pending || !$("consent").checked || state.busy) return;
  if (!$("preview-text").value.trim()) { errorBox("preview-error", "Bản gửi không được để trống."); return; }
  const payload = {...state.pending, consent: true, llm_text: $("preview-text").value};
  state.pending = null; $("privacy-dialog").close(); await analyze(payload);
});
$("consent").addEventListener("change", () => { $("confirm-send").disabled = !$("consent").checked; });
$("privacy-dialog").addEventListener("close", () => { state.pending = null; });
$("cancel-preview").addEventListener("click", () => $("privacy-dialog").close());
$("tab-text").addEventListener("click", () => setMode("text"));
$("tab-url").addEventListener("click", () => setMode("url"));
$("input-text").addEventListener("input", () => { updateCount(); resetResult(); });
$("input-text").addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); $("analysis-form").requestSubmit(); } });
$("clear-button").addEventListener("click", () => { $("input-text").value = ""; updateCount(); resetResult(); errorBox("form-error"); $("input-text").focus(); });
$("use-llm").addEventListener("change", updateOptions);
$("api-key").addEventListener("input", keyStatus);
$("show-key").addEventListener("click", () => { const hidden = $("api-key").type === "password"; $("api-key").type = hidden ? "text" : "password"; $("show-key").textContent = hidden ? "Ẩn" : "Hiện"; $("show-key").setAttribute("aria-label", hidden ? "Ẩn API key" : "Hiện API key"); });
document.querySelectorAll("[data-sample]").forEach(button => button.addEventListener("click", () => { if (state.mode !== "text") setMode("text"); $("input-text").value = samples[button.dataset.sample]; updateCount(); resetResult(); $("input-text").focus(); }));
$("reload-model").addEventListener("click", async () => { $("reload-model").disabled = true; try { modelStatus(await api("/api/model/reload", {}, 30000)); errorBox("connection-error"); } catch (err) { errorBox("connection-error", err.message); } finally { $("reload-model").disabled = false; } });
$("how-button").addEventListener("click", () => $("how-dialog").showModal());
$("close-how").addEventListener("click", () => $("how-dialog").close());
$("download-result").addEventListener("click", () => {
  if (!state.result) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.result, null, 2)], {type: "application/json"}));
  const link = node("a"); link.href = url; link.download = `phishlens_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
updateCount(); updateOptions(); init();
