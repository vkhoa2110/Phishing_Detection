"use strict";
const $ = (id) => document.getElementById(id);
const state = {mode: "text", busy: false, pending: null, result: null, hasKey: false, mlReady: false, ragReady: false, drafts: {text: "", url: ""}};
const labels = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra thêm", LOW: "Chưa thấy dấu hiệu rõ ràng", UNKNOWN: "Chưa đủ thông tin"};
// These are examples of input, never precomputed model results or clickable links.
const samples = {
  text: {
    suspicious: "Tài khoản của bạn sắp bị khóa. Hãy truy cập https://xac-minh-tai-khoan.example/verify và nhập mật khẩu, mã OTP để xác minh. Nếu không hoàn tất trong 10 phút, chúng tôi sẽ ngừng dịch vụ.",
    normal: "Chào bạn, buổi họp nhóm tuần này bắt đầu lúc 14 giờ thứ Sáu tại phòng học cũ. Bạn vui lòng chuẩn bị phần công việc đã thực hiện để cùng trao đổi nhé.",
  },
  url: {suspicious: "https://xac-minh-tai-khoan.example/login?verify=urgent", normal: "https://example.org/"},
};

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function errorBox(id, message = "") { $(id).textContent = message; $(id).hidden = !message; }
function updateCount() {
  $("char-count").textContent = $("input-text").value.length.toLocaleString("vi-VN");
  $("clear-button").disabled = state.busy || !$("input-text").value;
}
function keyStatus() {
  $("key-status").textContent = $("api-key").value.trim() ? "Dùng key cho phiên hiện tại" : state.hasKey ? "Máy chủ đã cấu hình" : "Cần bổ sung API key để dùng AI";
}
function updateOptions() {
  const ai = $("use-llm").checked;
  $("use-rag").disabled = !ai || !state.ragReady || state.mode === "url" || state.busy;
  $("include-ml").disabled = !ai || state.busy;
  ["endpoint", "llm-model", "api-key", "show-key"].forEach(id => { $(id).disabled = !ai || state.busy; });
  document.querySelector(".privacy-note").hidden = !ai;
  $("local-only-note").hidden = ai || state.mode === "url";
  $("ai-label").textContent = state.mode === "url" ? "Nhờ AI giải thích thêm" : "Giải thích và gợi ý bằng AI";
  $("ai-description").textContent = state.mode === "url" ? "Thêm nhận xét từ chuỗi đường dẫn. Không truy cập trang đích." : "Hiểu dấu hiệu đáng ngờ, kể cả khi tin nhắn không có đường dẫn.";
  updateCount();
}
function busy(value) {
  state.busy = value;
  $("analysis-form").querySelectorAll("input,textarea,button").forEach(el => { el.disabled = value; });
  ["reload-model", "settings-button", "new-check"].forEach(id => { $(id).disabled = value; });
  $("button-label").textContent = value ? "Đang kiểm tra…" : "Kiểm tra ngay";
  $("results-panel").setAttribute("aria-busy", String(value));
  updateOptions();
}
async function api(path, data, timeoutMs = 65000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {method: data === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data), signal: controller.signal, cache: "no-store"});
    let body;
    try { body = await response.json(); } catch { throw new Error("Chưa đọc được phản hồi từ ứng dụng. Vui lòng thử lại."); }
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Chưa xử lý được yêu cầu. Vui lòng thử lại.");
    return body;
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Đã hết thời gian chờ. Bạn có thể thử lại hoặc tắt AI để chỉ kiểm tra đường dẫn.");
    if (err instanceof TypeError) throw new Error("Không kết nối được ứng dụng. Kiểm tra kết nối rồi tải lại trang.");
    throw err;
  } finally { clearTimeout(timer); }
}
function modelStatus(ml) {
  state.mlReady = Boolean(ml.ready);
  $("model-status").textContent = ml.ready ? `${ml.run_id || ml.kind} · ${ml.feature_count} đặc trưng` : ml.message;
  $("model-status").title = ml.message || "";
  $("service-status").textContent = state.mlReady ? "Sẵn sàng kiểm tra đường dẫn" : "Kiểm tra đường dẫn chưa sẵn sàng";
  $("service-dot").classList.toggle("ready", state.mlReady);
  $("service-dot").classList.toggle("warning", !state.mlReady);
}
async function init() {
  try {
    const status = await api("/api/status", undefined, 30000);
    modelStatus(status.ml);
    $("endpoint").value = status.llm.endpoint;
    $("llm-model").value = status.llm.model;
    $("llm-name").textContent = status.llm.model;
    state.hasKey = status.llm.has_api_key;
    $("api-status").textContent = state.hasKey ? "Máy chủ đã cấu hình key · Chưa kiểm tra kết nối nhà cung cấp" : "Cần nhập API key để dùng AI";
    $("api-dot").classList.toggle("ready", state.hasKey);
    state.ragReady = Boolean(status.rag && status.rag.ready);
    $("use-rag").checked = state.ragReady;
    $("rag-status").textContent = state.ragReady ? `${status.rag.documents} nguồn · Dùng cho tin nhắn / email, không xác minh tên miền.` : "Kho tài liệu chưa sẵn sàng. Bạn vẫn có thể phân tích bằng AI.";
    updateOptions(); keyStatus(); errorBox("connection-error");
  } catch (err) {
    errorBox("connection-error", err.message);
    $("service-status").textContent = "Chưa kết nối được ứng dụng";
    $("service-dot").classList.add("warning");
    $("rag-status").textContent = "Chưa kiểm tra được kho tài liệu.";
    $("model-status").textContent = "Chưa lấy được trạng thái.";
    $("api-status").textContent = "Chưa lấy được trạng thái.";
    keyStatus();
  }
}
function setMode(mode) {
  if (mode === state.mode || state.busy) return;
  state.drafts[state.mode] = $("input-text").value;
  state.mode = mode;
  for (const kind of ["text", "url"]) {
    $("tab-" + kind).classList.toggle("active", mode === kind);
    $("tab-" + kind).setAttribute("aria-pressed", String(mode === kind));
  }
  $("input-label").textContent = mode === "url" ? "Đường dẫn cần kiểm tra" : "Nội dung email hoặc tin nhắn";
  $("input-hint").textContent = mode === "url" ? "Dán một đường dẫn đầy đủ, bắt đầu bằng http:// hoặc https://" : "Có thể kiểm tra cả tin nhắn không có đường dẫn";
  $("input-text").placeholder = mode === "url" ? "https://example.org/\n\nChỉ dán đường dẫn. Bạn không cần mở trang đó." : "Ví dụ: “Tài khoản của bạn sắp bị khóa. Hãy xác minh ngay…”\n\nDán toàn bộ nội dung để có thêm ngữ cảnh kiểm tra.";
  $("input-text").value = state.drafts[mode];
  document.querySelectorAll("[data-sample]").forEach(button => {
    const name = mode === "url" ? button.dataset.sample === "suspicious" ? "URL minh họa có dấu hiệu lạ" : "URL minh họa đơn giản" : button.dataset.sample === "suspicious" ? "Tin nhắn đáng ngờ" : "Tin nhắn thông thường";
    button.replaceChildren(document.createTextNode(name + " "), node("span", "", "↗"));
    button.lastChild.setAttribute("aria-hidden", "true");
  });
  resetResult(); errorBox("form-error"); updateOptions();
}
function resetResult() {
  state.result = null;
  $("results-panel").hidden = true;
  $("result-content").hidden = true;
  $("result-content").replaceChildren();
  $("loading-state").hidden = true;
  $("result-announcement").textContent = "";
}
function revealResult() {
  $("results-panel").hidden = false;
  $("results-panel").scrollIntoView({behavior: "instant", block: "start"});
  $("results-panel").focus({preventScroll: true});
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
  const grid = node("div", "result-grid"), main = node("div", "result-main"), aside = node("div", "result-aside");
  grid.append(main, aside); target.append(grid);
  const llm = data.llm, urlAssessment = data.assessments.url;
  const urlAlarm = ["HIGH", "WARNING"].includes(urlAssessment.risk_level);
  // Show a URL alarm before a LOW/UNKNOWN message conclusion so it cannot be mistaken for an all-clear.
  const urlBanner = data.mode === "text" && urlAssessment.status !== "not_present" ? node("div", `url-assessment ${urlAssessment.risk_level}`) : null;
  if (urlBanner) {
    urlBanner.append(node("strong", "", `Đường dẫn trong nội dung: ${labels[urlAssessment.risk_level]}`), node("p", "", "Đường dẫn được đánh giá riêng với tin nhắn. Chưa kiểm tra trang đích hoặc chủ sở hữu."));
    if (urlAlarm) urlBanner.append(node("p", "", "Không mở hoặc điền thông tin qua đường dẫn này trước khi xác minh."));
    if (urlAlarm) main.append(urlBanner);
  }
  const banner = node("div", `verdict ${data.final.risk_level}`);
  const symbol = node("span", "verdict-icon", {HIGH: "!", WARNING: "!", LOW: "−", UNKNOWN: "?"}[data.final.risk_level]);
  symbol.setAttribute("aria-hidden", "true");
  const meta = node("div", "verdict-eyebrow");
  meta.append(node("span", "", data.final.scope === "url" ? "ĐÁNH GIÁ ĐƯỜNG DẪN" : "HÀNH VI TRONG NỘI DUNG"), node("span", "", `${(data.timing.total_ms / 1000).toFixed(1)} giây`));
  const explanations = {
    HIGH: "Nội dung có dấu hiệu yêu cầu thực hiện hành vi nguy hiểm. Xem dấu hiệu cụ thể và đối chiếu riêng các đường dẫn.",
    WARNING: "Nội dung có điểm cần xác minh thêm trước khi làm theo. Hãy đọc các dấu hiệu bên dưới.",
    LOW: "Chưa thấy hành vi lừa đảo rõ trong bản nội dung bạn đã xác nhận. Hãy đối chiếu riêng các đường dẫn.",
    UNKNOWN: "Chưa đủ căn cứ đánh giá hành vi trong tin nhắn. Cảnh báo đường dẫn vẫn được kiểm tra riêng.",
  };
  const explanation = data.final.scope === "url" ? "Kết quả chỉ dựa trên chuỗi đường dẫn. Chưa kiểm tra trang đích hoặc danh tính chủ sở hữu." : explanations[data.final.risk_level];
  banner.append(symbol, meta, node("h3", "", data.final.label), node("p", "", explanation));
  main.append(banner);
  if (urlBanner && !urlAlarm) main.append(urlBanner);
  if (data.final.review_reason) main.append(node("p", "conflict-note", data.final.review_reason));
  if (llm.status === "ok" && llm.input_modified) main.append(node("p", "inline-warning", "Bạn đã sửa bản gửi AI. Nhận định nội dung chỉ áp dụng cho bản đã sửa; đường dẫn từ bản gốc vẫn được kiểm tra riêng."));
  if (llm.status === "error") main.append(node("p", "inline-warning", "Chưa nhận được giải thích từ AI. " + llm.message));
  if (llm.status === "disabled" && data.mode === "text") main.append(node("p", "inline-warning", "AI đang tắt nên hành vi trong tin nhắn chưa được đánh giá. Bạn có thể bật AI rồi kiểm tra lại."));
  const actions = section("Bạn nên làm gì tiếp theo?"); actions.classList.add("actions-section");
  const list = node("ol", "actions-list");
  const recommendations = llm.status === "ok" ? [...llm.verdict.recommended_actions] : [];
  if (urlAlarm) recommendations.unshift("Tạm dừng thao tác với đường dẫn. Tự mở ứng dụng hoặc website chính thức để kiểm tra lại.");
  if (!recommendations.length) recommendations.push(data.final.risk_level === "LOW" ? "Nếu có yêu cầu chuyển tiền hay cung cấp thông tin, hãy xác minh qua một kênh chính thức trước khi làm theo." : "Chưa đủ căn cứ kết luận. Xác minh với người gửi qua một kênh liên hệ bạn đã biết.");
  [...new Set(recommendations)].forEach(action => list.append(node("li", "", action)));
  actions.append(list); main.append(actions);
  if (llm.status === "ok") {
    const analysis = section("Vì sao có kết quả này?");
    analysis.append(node("p", "analysis-summary", llm.verdict.summary));
    llm.warnings.forEach(w => analysis.append(node("p", "inline-warning", w))); main.append(analysis);
    const evidence = section("Dấu hiệu trong nội dung", llm.verdict.evidence.length);
    if (!llm.verdict.evidence.length) evidence.append(node("p", "result-subtle", "Không có dấu hiệu cụ thể được trích từ bản nội dung đã gửi. Điều này không bảo đảm nội dung an toàn."));
    for (const item of llm.verdict.evidence) {
      const el = node("div", "evidence-item"); el.append(node("blockquote", "", `“${item.quote}”`), node("p", "", item.reason)); evidence.append(el);
    }
    main.append(evidence);
  }
  if (data.urls.length) {
    const urls = section("Đường dẫn được phát hiện", data.urls.length);
    for (const item of data.urls) {
      const card = node("div", "url-item"), head = node("div", "url-heading");
      head.append(node("span", "", item.id), node("span", `risk-badge ${item.risk_level || "UNKNOWN"}`, item.status === "ok" ? labels[item.risk_level] : "Chưa đánh giá"));
      // Detected URLs stay plain text; checking them must never require visiting them.
      card.append(head, node("code", "url-text", item.url));
      if (item.status === "ok") {
        card.append(node("p", "url-guidance", item.risk_level === "LOW" ? "Điểm dưới ngưỡng cảnh báo. Chưa kiểm tra trang đích hoặc chủ sở hữu." : "Chuỗi đường dẫn có điểm vượt ngưỡng cảnh báo; cần xác minh trước khi sử dụng."));
        const details = node("details", "url-score"); details.append(node("summary", "", "Xem điểm kiểm tra đường dẫn"));
        const row = node("div", "score-row"); row.append(node("span", "", "Điểm phân loại mô hình"), node("strong", "", Number(item.score).toFixed(4)));
        details.append(row, node("p", "threshold-note", `Ngưỡng cảnh báo ${Number(item.warning_threshold).toFixed(4)} · Ngưỡng cao ${item.high_threshold == null ? "chưa thiết lập" : Number(item.high_threshold).toFixed(4)}`), node("p", "threshold-note", "Điểm này không phải xác suất lừa đảo đã hiệu chỉnh.")); card.append(details);
      } else card.append(node("p", "inline-warning", item.message));
      urls.append(card);
    }
    aside.append(urls);
  } else {
    const noUrls = section("Kiểm tra đường dẫn");
    noUrls.append(node("p", "result-subtle", data.invalid_urls.length ? "Không có đường dẫn hợp lệ để phân loại." : "Không phát hiện đường dẫn trong nội dung. Kết quả nội dung phụ thuộc vào phần phân tích AI."));
    aside.append(noUrls);
  }
  if (data.invalid_urls.length) {
    const invalid = section("Đường dẫn chưa xử lý", data.invalid_urls.length);
    for (const url of data.invalid_urls) invalid.append(node("code", "url-text", url));
    aside.append(invalid);
  }
  const retrieval = data.retrieval;
  if (retrieval && retrieval.status !== "disabled") {
    const sources = section("Nguồn tham khảo", retrieval.sources.length);
    sources.append(node("p", "result-subtle", retrieval.reason));
    const support = llm.status === "ok" ? (llm.verdict.knowledge_support || []) : [];
    for (const source of retrieval.sources) {
      const card = node("div", "source-card"), cited = support.find(item => item.document_id === source.document_id);
      card.append(node("strong", "", source.title), node("p", "source-meta", `${source.publisher} · ${source.published_at || "Chưa xác minh ngày công bố"}`));
      try {
        const url = new URL(source.source_url);
        if (url.protocol === "https:" && !url.username && !url.password) {
          const link = node("a", "source-link", "Đọc bài gốc tại " + url.hostname + " ↗");
          link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; card.append(link);
        }
      } catch { /* Invalid source metadata is never turned into a clickable link. */ }
      const details = node("details", "source-details"); details.append(node("summary", "", "Xem nội dung tham khảo"), node("p", "", "Tóm lược từ nguồn: " + source.text));
      if (cited) details.append(node("p", "", "Kiến thức AI sử dụng: " + cited.claim), node("blockquote", "", "Đoạn trong tóm lược: “" + cited.source_quote + "”"));
      else details.append(node("p", "result-subtle", "Tài liệu được tìm thấy; AI chưa dẫn nguồn này."));
      details.append(node("p", "source-meta", "Mã tài liệu: " + source.document_id)); card.append(details); sources.append(card);
    }
    if (retrieval.sources.length) sources.append(node("p", "result-subtle", "Tài liệu hỗ trợ giải thích dấu hiệu, không xác nhận tên miền an toàn. Các đoạn trên là bản tóm lược, không phải trích nguyên văn bài gốc."));
    aside.append(sources);
  }
  const technical = node("details", "technical-details"); technical.append(node("summary", "", "Chi tiết phân tích và tải kết quả"));
  const parts = node("div", "components"), count = data.urls.filter(u => u.status === "ok").length;
  parts.append(component("KIỂM TRA ĐƯỜNG DẪN", count ? `${labels[urlAssessment.risk_level]} · ${count} / ${urlAssessment.total} URL` : data.urls.length ? "Chưa có kết quả" : "Không có URL hợp lệ", count ? `${data.ml.run_id} · ${data.ml.feature_count} đặc trưng` : data.urls.length ? data.ml.message : "Không chạy mô hình URL cho đầu vào này."));
  parts.append(component("PHÂN TÍCH AI", llm.status === "ok" ? labels[llm.verdict.risk_level] : llm.status === "disabled" ? "Đang tắt" : "Chưa có kết quả", llm.status === "ok" ? `${llm.model} · ${llm.included_ml ? "Có" : "Không kèm"} điểm URL · ${llm.rag ? "Có" : "Không"} tài liệu tham khảo` : llm.message)); technical.append(parts);
  if (llm.status === "ok") {
    const sent = node("details", "payload-details"); sent.append(node("summary", "", "Xem bản nội dung đã gửi tới AI"), node("pre", "", llm.input_used)); technical.append(sent);
    if (llm.usage && llm.usage.total_tokens) technical.append(node("p", "result-subtle", `${llm.usage.total_tokens.toLocaleString("vi-VN")} token · ${llm.prompt_version}`));
  }
  const download = node("button", "text-button", "Tải dữ liệu kết quả (.json) ↓"); download.type = "button"; download.id = "download-result";
  download.addEventListener("click", downloadResult); technical.append(download); target.append(technical);
  target.append(node("div", "result-note", data.notice));
  $("loading-state").hidden = true; target.hidden = false;
  $("result-announcement").textContent = `Đã kiểm tra. ${data.final.label}.${urlAlarm ? " Đường dẫn: " + labels[urlAssessment.risk_level] + "." : ""}`;
}
async function analyze(payload) {
  busy(true); errorBox("form-error"); state.result = null;
  $("result-content").hidden = true; $("result-content").replaceChildren(); $("loading-state").hidden = false;
  $("result-announcement").textContent = "";
  $("loading-message").textContent = payload.use_llm ? "Đang kiểm tra đường dẫn và chờ giải thích từ dịch vụ AI…" : "Đang kiểm tra chuỗi đường dẫn tại máy chạy ứng dụng…";
  revealResult();
  try { render(await api("/api/analyze", payload)); }
  catch (err) { resetResult(); errorBox("form-error", err.message); $("form-error").scrollIntoView({block: "center"}); }
  finally { busy(false); if (!$("form-error").hidden) $("input-text").focus({preventScroll: true}); }
}
$("analysis-form").addEventListener("submit", async event => {
  event.preventDefault(); if (state.busy) return;
  const text = $("input-text").value.trim(); errorBox("form-error");
  if (!text) { errorBox("form-error", "Bạn chưa nhập nội dung cần kiểm tra."); $("input-text").focus(); return; }
  const payload = {mode: state.mode, text, use_llm: $("use-llm").checked, include_ml: $("include-ml").checked, use_rag: $("use-rag").checked && !$("use-rag").disabled, endpoint: $("endpoint").value.trim(), model: $("llm-model").value.trim(), api_key: $("api-key").value.trim(), consent: false};
  if (!payload.use_llm) { await analyze(payload); return; }
  if (!payload.api_key && !state.hasKey) {
    $("settings-dialog").showModal(); document.querySelector(".api-settings").open = true;
    errorBox("form-error", "Chưa có kết nối AI. Bổ sung API key trong Thiết lập, hoặc tắt AI để chỉ kiểm tra đường dẫn."); $("api-key").focus(); return;
  }
  busy(true);
  try {
    const preview = await api("/api/preview", {mode: state.mode, text}, 15000);
    state.pending = payload;
    $("preview-text").value = preview.text;
    let destination = "dịch vụ AI bên ngoài";
    try { destination = new URL(payload.endpoint).hostname; } catch { /* The API validates the endpoint on submission. */ }
    $("preview-provider").textContent = `Bản bên dưới sẽ được gửi tới ${destination}. Ứng dụng đã che một số thông tin theo quy tắc; bạn cần kiểm tra và sửa thêm trước khi gửi.`;
    $("masked-fields").textContent = preview.masked_fields.length ? "Đã che theo quy tắc: " + preview.masked_fields.join(" · ") : "Quy tắc hiện tại chưa phát hiện thông tin cần che. Hãy tự kiểm tra để bỏ dữ liệu riêng tư trước khi gửi.";
    $("preview-ml-note").textContent = payload.include_ml ? "AI chỉ được xem điểm của các đường dẫn còn trong bản bạn xác nhận. Đường dẫn từ bản gốc vẫn được kiểm tra riêng tại máy." : "Không gửi điểm hoặc kết luận mô hình đường dẫn cho AI.";
    if (payload.use_rag) $("preview-ml-note").textContent += " Tối đa 3 tóm lược công khai có nguồn sẽ được tìm theo bản đã sửa và gửi kèm để tham khảo.";
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
// Editing the approved text requires confirming consent again.
$("preview-text").addEventListener("input", () => { $("consent").checked = false; $("confirm-send").disabled = true; });
$("privacy-dialog").addEventListener("close", () => { state.pending = null; });
$("cancel-preview").addEventListener("click", () => $("privacy-dialog").close());
$("tab-text").addEventListener("click", () => setMode("text"));
$("tab-url").addEventListener("click", () => setMode("url"));
$("input-text").addEventListener("input", () => { updateCount(); resetResult(); errorBox("form-error"); });
$("input-text").addEventListener("keydown", event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); $("analysis-form").requestSubmit(); } });
$("clear-button").addEventListener("click", () => { $("input-text").value = ""; updateCount(); resetResult(); errorBox("form-error"); $("input-text").focus(); });
$("new-check").addEventListener("click", () => { $("input-text").focus(); $("input-text").select(); $("analysis-form").scrollIntoView({block: "start"}); });
$("use-llm").addEventListener("change", () => { updateOptions(); resetResult(); });
["use-rag", "include-ml"].forEach(id => $(id).addEventListener("change", resetResult));
$("api-key").addEventListener("input", keyStatus);
$("show-key").addEventListener("click", () => { const hidden = $("api-key").type === "password"; $("api-key").type = hidden ? "text" : "password"; $("show-key").textContent = hidden ? "Ẩn" : "Hiện"; $("show-key").setAttribute("aria-label", hidden ? "Ẩn API key" : "Hiện API key"); });
document.querySelectorAll("[data-sample]").forEach(button => button.addEventListener("click", () => { $("input-text").value = samples[state.mode][button.dataset.sample]; updateCount(); resetResult(); errorBox("form-error"); $("input-text").focus(); }));
$("reload-model").addEventListener("click", async () => { $("reload-model").disabled = true; try { modelStatus(await api("/api/model/reload", {}, 30000)); errorBox("connection-error"); } catch (err) { errorBox("connection-error", err.message); } finally { $("reload-model").disabled = false; } });
$("settings-button").addEventListener("click", () => $("settings-dialog").showModal());
function closeSettings() {
  $("api-key").type = "password"; $("show-key").textContent = "Hiện"; $("show-key").setAttribute("aria-label", "Hiện API key");
}
$("settings-dialog").addEventListener("close", closeSettings);
["close-settings", "done-settings"].forEach(id => $(id).addEventListener("click", () => $("settings-dialog").close()));
$("how-button").addEventListener("click", () => $("how-dialog").showModal());
$("close-how").addEventListener("click", () => $("how-dialog").close());
function downloadResult() {
  if (!state.result) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.result, null, 2)], {type: "application/json"}));
  const link = node("a"); link.href = url; link.download = `phishlens_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
updateCount(); updateOptions(); init();
