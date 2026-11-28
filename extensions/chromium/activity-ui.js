"use strict";
window.PhishLensActivityUI = options => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  const kinds = {mail: "Email", conversation: "Hội thoại", url: "Đường dẫn", text: "Nội dung", image: "Hình ảnh"};
  const risks = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra thêm", LOW: "Chưa thấy dấu hiệu rõ", UNKNOWN: "Chưa đủ thông tin"};
  let revision = 0, timer, items = [], filter = "all", refreshing = false;
  const visible = () => document.body.dataset.view === "activity" && document.visibilityState === "visible";
  async function message(type, extra = {}) { const value = await chrome.runtime.sendMessage({type, ...extra}); if (typeof value?.error === "string") throw new Error(value.error); return value; }
  function matches(item) { return filter === "all" || (filter === "running" ? item.status === "running" : filter === "attention" ? ["error", "expired"].includes(item.status) || ["HIGH", "WARNING", "UNKNOWN"].includes(item.risk) || ["HIGH", "WARNING"].includes(item.urlRisk) || item.partial || item.technicalError : item.status === "complete" && !item.technicalError); }
  function label(item) { return item.unavailable ? "Chưa lấy được trạng thái" : item.cancelled ? "Đã hủy" : item.status === "running" ? item.queued ? "Đang chờ xử lý" : item.progress?.total ? `${item.progress.completed}/${item.progress.total} phần${item.progress.stopping ? " · Đang dừng" : ""}` : "Đang kiểm tra" : item.status === "expired" ? "Kết quả đã hết hạn" : item.status === "error" ? "Chưa hoàn tất" : item.technicalError ? "AI chưa hoàn tất" : risks[item.risk] || "Đã hoàn tất"; }
  function paint() {
    const list = $("activity-list"), focus = list.querySelector(":focus"), focusId = focus?.closest("[data-id]")?.dataset.id, focusAction = focus?.dataset.action;
    list.replaceChildren();
    const shown = items.filter(matches), running = items.filter(item => item.status === "running").length;
    $("activity-count").textContent = items.length ? `${items.length} lượt · ${running} đang xử lý` : "Các lượt kiểm tra trong phiên này";
    $("activity-empty").hidden = shown.length > 0;
    $("activity-empty-title").textContent = items.length ? "Chưa có lượt phù hợp" : "Các kết quả sẽ ở đây";
    $("activity-clear").disabled = !items.some(item => ["complete", "error", "expired"].includes(item.status));
    for (const item of shown) {
      const card = node("article", undefined, "activity-card surface"); card.dataset.id = item.id; card.dataset.status = item.status;
      const top = node("div", undefined, "activity-card-top"), title = node("strong", (kinds[item.kind] || "Nội dung") + (item.platform ? " · " + item.platform : "")), time = node("time", new Date(item.created).toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"}));
      time.dateTime = new Date(item.created).toISOString(); top.append(title, time); card.append(top);
      const state = node("p", label(item), "activity-state " + (item.unavailable ? "UNKNOWN" : item.cancelled ? "UNKNOWN" : item.status === "complete" ? item.risk : item.status)); card.append(state);
      if (item.status === "complete" && item.kind !== "url" && ["HIGH", "WARNING"].includes(item.urlRisk)) card.append(node("small", "Có liên kết cần kiểm tra riêng", "activity-url-warning"));
      if (item.partial) card.append(node("small", "Kết quả áp dụng cho phần đã xử lý.", "muted"));
      const actions = node("div", undefined, "activity-card-actions");
      if (!["error", "expired"].includes(item.status)) {
        const open = node("button", item.status === "running" ? "Xem tiến trình" : "Mở kết quả", "secondary"); open.type = "button"; open.dataset.action = "open";
        open.addEventListener("click", async () => {
          if (options.busy()) { options.notify("Lượt đang mở vẫn chạy. Bạn có thể xem kết quả khác sau khi hoàn tất."); return; }
          if (options.hasDraft() && !confirm("Mở kết quả này và thay bản nội dung chưa gửi?")) return;
          open.disabled = true;
          try { const value = await message("ACTIVITY_OPEN", {id: item.id}); await options.open(value.record); }
          catch (error) { options.error(error.message); } finally { open.disabled = false; }
        }); actions.append(open);
      }
      if (item.hasSource) {
        const source = node("button", "Về tab nguồn", "text-button"); source.type = "button"; source.dataset.action = "source";
        source.addEventListener("click", () => message("ACTIVITY_SOURCE", {id: item.id}).catch(error => options.error(error.message))); actions.append(source);
      }
      if (item.queued && !item.unavailable) {
        const cancel = node("button", "Hủy lượt chờ", "text-button"); cancel.type = "button"; cancel.dataset.action = "cancel";
        cancel.addEventListener("click", async () => {
          cancel.disabled = true;
          try { const value = await message("ACTIVITY_OPEN", {id: item.id}); await message("CANCEL_QUEUED_JOB", {record: value.record}); await load(); }
          catch (error) { options.error(error.message); cancel.disabled = false; }
        }); actions.append(cancel);
      }
      if (item.status !== "running") {
        const remove = node("button", "Xóa", "text-button"); remove.type = "button"; remove.dataset.action = "remove"; remove.setAttribute("aria-label", "Xóa lượt " + (kinds[item.kind] || "kiểm tra") + " khỏi danh sách");
        remove.addEventListener("click", async () => { try { await message("ACTIVITY_REMOVE", {id: item.id}); await load(); } catch (error) { options.error(error.message); } }); actions.append(remove);
      }
      card.append(actions); list.append(card);
    }
    if (focusId) list.querySelector(`[data-id="${CSS.escape(focusId)}"] [data-action="${CSS.escape(focusAction || "")}"]`)?.focus({preventScroll: true});
  }
  async function refresh(token = revision, all = false) {
    if (refreshing || !visible()) return;
    refreshing = true; $("activity-refresh").disabled = true;
    try {
      let cursor = 0;
      const snapshot = items.filter(item => item.status !== "expired" && (all || item.status === "running" || item.unavailable));
      await Promise.all(Array.from({length: Math.min(3, snapshot.length)}, async () => {
        while (cursor < snapshot.length && token === revision && visible()) {
          const item = snapshot[cursor++];
          try {
            const value = await message("ACTIVITY_STATUS", {id: item.id});
            if (token !== revision) return;
            items = items.map(row => row.id === item.id ? value.item : row); paint();
          } catch (error) { if (token === revision) { $("activity-message").textContent = error.message; $("activity-message").hidden = false; } }
        }
      }));
    } finally {
      refreshing = false; $("activity-refresh").disabled = false;
      clearTimeout(timer);
      if (token === revision && visible() && items.some(item => item.status === "running" && !item.unavailable)) timer = setTimeout(() => refresh(token), 1800);
    }
  }
  async function load(all = true) {
    clearTimeout(timer); const token = ++revision;
    $("activity-message").hidden = true; $("activity-list").setAttribute("aria-busy", "true");
    try { const value = await message("ACTIVITY_LIST"); if (token !== revision) return; items = value.items; paint(); refresh(token, all); }
    catch (error) { if (token === revision) { $("activity-message").textContent = error.message; $("activity-message").hidden = false; } }
    finally { if (token === revision) $("activity-list").setAttribute("aria-busy", "false"); }
  }
  $("activity-refresh").addEventListener("click", load);
  $("activity-clear").addEventListener("click", async () => { try { await message("ACTIVITY_CLEAR"); await load(); } catch (error) { options.error(error.message); } });
  document.querySelectorAll("[data-activity-filter]").forEach(button => button.addEventListener("click", () => { filter = button.dataset.activityFilter; document.querySelectorAll("[data-activity-filter]").forEach(el => el.setAttribute("aria-pressed", String(el === button))); paint(); }));
  chrome.storage.onChanged.addListener((changes, area) => { if (area === "session" && changes.analysisActivity && visible() && !refreshing) load(false); });
  document.addEventListener("visibilitychange", () => { if (visible()) load(); else { revision++; clearTimeout(timer); } });
  return {enter: load, leave: () => { revision++; clearTimeout(timer); }};
};
