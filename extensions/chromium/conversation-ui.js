"use strict";
window.PhishLensConversationUI = options => {
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  const message = async values => { const result = await chrome.runtime.sendMessage(values); if (result?.error) throw new Error(result.error); return result; };
  const reasons = {requested_count: "Đã đủ số tin yêu cầu", date_boundary: "Đã tới ngày bắt đầu", no_more_loaded: "Trang không tải thêm tin cũ", no_scroll_container: "Đã lấy phần lịch sử trang đang tải", message_limit: "Đã tới giới hạn số tin", safety_limit: "Đã tới giới hạn dung lượng", time_limit: "Đã tới giới hạn thời gian tải", user_cancelled: "Đã dừng theo yêu cầu", source_hidden: "Đã dừng khi rời tab chat"};
  let data = null, context = null, stale = false, revision = 0, previous = null, sourceTab = null, scanPointer = null, collecting = false, cancelPending = false, diagnostics = null;
  function closePicker() { $("conversation-picker").hidden = true; delete document.body.dataset.selectingConversation; }
  function stop() { cancelPending = true; if (scanPointer) return message({type: "SCAN_CONVERSATION", action: "cancel", ...scanPointer}).catch(() => {}); return Promise.resolve(); }
  function forget() { revision++; stop(); scanPointer = null; collecting = false; context = null; data = null; previous = null; stale = false; closePicker(); $("conversation-messages").replaceChildren(); $("conversation-scope").hidden = true; }
  function selected() { return [...$("conversation-messages").querySelectorAll(".conversation-message")].filter(el => el.querySelector("input").checked); }
  function transcript(rows) {
    const scope = data.context.history ? "Các tin trong phạm vi đã tải; ngày/người nói do trang cung cấp và người dùng duyệt." : "Chỉ các tin đang hiển thị đã chọn; chưa đọc toàn bộ lịch sử. Nhãn người nói do người dùng duyệt.";
    return ["ĐOẠN HỘI THOẠI ĐÃ CHỌN · " + PhishLensChatPlatforms.label(data.context.platform).toLocaleUpperCase("vi-VN"), scope, "",
      ...rows.map((el, index) => { const item = data.messages.find(item => item.id === el.dataset.id); return `[Tin ${String(index + 1).padStart(2, "0")} | ${el.querySelector("select").value}${item.date ? " | " + item.date : ""}]\n${item.text}\n`; })].join("\n");
  }
  function count() {
    const rows = selected(), length = rows.length && data ? transcript(rows).length : 0, max = data?.context.history ? 200000 : 8000, maxMessages = data?.context.history ? 2000 : 30;
    $("conversation-count").textContent = data ? `${rows.length}/${data.messages.length} tin · ${length.toLocaleString("vi-VN")} ký tự` : "";
    $("conversation-continue").disabled = !rows.length || rows.length > maxMessages || length > max || stale || collecting;
    $("conversation-limit").textContent = rows.length > maxMessages ? `Chọn tối đa ${maxMessages.toLocaleString("vi-VN")} tin.` : length > max ? `Nội dung vượt ${max.toLocaleString("vi-VN")} ký tự. Thu hẹp phạm vi hoặc bỏ chọn một số tin.` : "";
  }
  function rangeControls() {
    const mode = $("conversation-mode").value;
    $("conversation-dates").hidden = mode !== "dates"; $("conversation-max").hidden = mode === "visible"; $("conversation-limit-label").hidden = mode === "visible";
    $("conversation-presets").hidden = mode !== "latest";
    for (const button of $("conversation-presets").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.count === $("conversation-max").value));
    $("conversation-limit-label").textContent = mode === "latest" ? "Số tin gần nhất" : "Giới hạn số tin mỗi lần";
    $("conversation-range-note").textContent = mode === "visible" ? "Lấy các tin đang có trong vùng nhìn thấy để chọn thủ công." : mode === "all" ? "Tự cuộn tải lịch sử tới khi trang không tải thêm, tối đa 2.000 tin mỗi lần." : mode === "dates" ? "Chỉ lấy tin đọc được ngày. Có thể để trống ngày kết thúc." : "Tự cuộn để lấy đủ số tin gần nhất, tối đa 2.000 tin.";
  }
  function configure() {
    data = null; $("conversation-messages").replaceChildren(); $("conversation-count").textContent = ""; $("conversation-limit").textContent = "";
    $("conversation-range").hidden = false; $("conversation-loading").hidden = true; $("conversation-continue").hidden = true; $("conversation-selection-tools").hidden = true; $("conversation-coverage").hidden = true; $("conversation-stale").hidden = true;
    $("conversation-read-error").hidden = true; rangeControls();
    $("conversation-diagnostics").hidden = true;
  }
  async function open(tabId) {
    if (options.busy() || collecting) throw new Error("Chờ lượt hiện tại hoàn tất hoặc dừng tải trước.");
    if (!options.ready()) throw new Error("Kết nối ứng dụng PhishLens trước khi đọc hội thoại.");
    options.clearError?.();
    if ($("conversation-picker").hidden && options.hasDraft() && !confirm("Chọn phạm vi mới và thay nội dung đang kiểm tra?")) return;
    revision++; sourceTab = tabId || (await options.browserTab())?.id;
    const tab = await chrome.tabs.get(sourceTab);
    if (!PhishLensChatPlatforms.detect(tab.url)) throw new Error("Mở cuộc trò chuyện trên Zalo, Messenger hoặc Telegram Web.");
    previous = {context, stale}; context = null; stale = false;
    const platform = PhishLensChatPlatforms.detect(tab.url);
    const {conversationRange = {}} = await chrome.storage.local.get("conversationRange");
    const saved = conversationRange[platform.id];
    if (saved && ["latest", "all", "dates", "visible"].includes(saved.mode) && Number.isInteger(saved.limit) && saved.limit >= 1 && saved.limit <= 2000) {
      $("conversation-mode").value = saved.mode; $("conversation-max").value = String(saved.limit);
    }
    $("conversation-source").textContent = platform.label;
    $("conversation-scope").hidden = true; configure(); $("conversation-picker").hidden = false; document.body.dataset.selectingConversation = "true";
    $("conversation-picker").scrollIntoView({block: "start"});
  }
  function display(result) {
    data = result; stale = false; $("conversation-messages").replaceChildren();
    $("conversation-source").textContent = `${result.platform} · ${result.messages.length} tin đã tải`;
    $("conversation-range").hidden = true; $("conversation-selection-tools").hidden = false; $("conversation-continue").hidden = false;
    const scope = result.context.scope;
    $("conversation-coverage").hidden = !scope;
    if (scope) $("conversation-coverage").textContent = (result.requested_count_missing ? `Chỉ tải được ${result.messages.length}/${scope.requested_limit} tin. ` : "") + (scope.stop_reason === "no_scroll_container" ? "Chưa điều khiển được vùng cuộn của trang; đây chỉ là phần đã lấy." : reasons[scope.stop_reason] || "Đã tải phạm vi") + (scope.from_date ? ` · ${scope.from_date}${scope.to_date ? " → " + scope.to_date : " trở đi"}` : "") + (scope.mode === "dates" && scope.unknown_dates ? ` · ${scope.unknown_dates} tin chưa đọc được ngày, chưa đưa vào phạm vi` : "") + (result.dedup_uncertain ? " · Trang thiếu ID tin ổn định; số tin giống nhau có thể chưa chính xác." : "") + (result.updated_messages ? ` · Đã lấy bản mới nhất của ${result.updated_messages} tin cập nhật trong lúc tải.` : "");
    showDiagnostics(Boolean(result.requested_count_missing));
    const speakers = [...new Set(["Bạn", ...result.messages.map(row => row.speaker), "Người khác", "Chưa rõ người gửi"])];
    for (const [index, item] of result.messages.entries()) {
      const row = make("article", undefined, "conversation-message"); row.dataset.id = item.id;
      const heading = make("div", undefined, "conversation-message-heading"), check = make("input"), label = make("label"), name = make("select");
      check.type = "checkbox"; check.checked = Boolean(result.context.history) || result.messages.length <= 30; check.id = "chat-select-" + index;
      check.setAttribute("aria-label", "Chọn tin " + (index + 1)); label.htmlFor = check.id; label.append(check, document.createTextNode("Tin " + String(index + 1).padStart(2, "0")));
      name.setAttribute("aria-label", "Người nói ở tin " + (index + 1));
      for (const value of speakers) { const option = make("option", value); option.value = value; name.append(option); }
      name.value = item.speaker; heading.append(label, name); row.append(heading, make("p", item.text));
      if (item.date) row.append(make("time", item.date));
      if (item.attachment) row.append(make("small", "Ảnh/tệp chưa được đọc. Có thể dùng khoanh vùng để kiểm tra riêng."));
      check.addEventListener("change", count); name.addEventListener("change", count); $("conversation-messages").append(row);
    }
    $("conversation-stale").hidden = true; count();
  }
  $("conversation-mode").addEventListener("change", () => { if (["all", "dates"].includes($("conversation-mode").value) && $("conversation-max").value === "100") $("conversation-max").value = "500"; rangeControls(); });
  $("conversation-max").addEventListener("input", rangeControls);
  for (const button of $("conversation-presets").querySelectorAll("button")) button.addEventListener("click", () => { $("conversation-max").value = button.dataset.count; rangeControls(); });
  $("conversation-load").addEventListener("click", async () => {
    if (collecting) return;
    options.clearError?.(); diagnostics = null;
    const token = ++revision, mode = $("conversation-mode").value, limit = Number($("conversation-max").value);
    previous = null; collecting = true; cancelPending = false; $("conversation-load").disabled = true; $("conversation-range").hidden = true; $("conversation-loading").hidden = false; $("conversation-stop").disabled = false; $("conversation-load-count").textContent = "Đang tải tin nhắn…";
    try {
      let result;
      if (mode === "visible") result = await message({type: "READ_CONVERSATION", tabId: sourceTab});
      else {
        let progress = await message({type: "SCAN_CONVERSATION", action: "start", tabId: sourceTab, options: {mode, limit, from: $("conversation-from").value, to: $("conversation-to").value}});
        if (token !== revision) { message({type: "SCAN_CONVERSATION", action: "cancel", tabId: progress.tabId, documentId: progress.documentId, scanId: progress.id}).catch(() => {}); return; }
        scanPointer = {tabId: progress.tabId, documentId: progress.documentId, scanId: progress.id}; diagnostics = progress.diagnostics;
        if (cancelPending) await stop();
        while (token === revision && progress.state === "running") {
          $("conversation-load-count").textContent = `Đã lấy ${progress.count.toLocaleString("vi-VN")} tin · ` + (progress.phase === "manual" ? "Cuộn lên trong khung chat để lấy thêm tin…" : progress.phase === "positioning" ? "Đang tới các tin mới nhất…" : "Đang tải thêm…");
          await new Promise(resolve => setTimeout(resolve, 500));
          progress = await message({type: "SCAN_CONVERSATION", action: "status", ...scanPointer}); diagnostics = progress.diagnostics;
        }
        if (progress.state === "error") throw new Error(progress.error || "Chưa tải được hội thoại.");
        result = progress.result;
      }
      if (token !== revision) return;
      const site = result.platformId, {conversationRange = {}} = await chrome.storage.local.get("conversationRange");
      if (site) await chrome.storage.local.set({conversationRange: {...conversationRange, [site]: {mode, limit}}});
      if (token !== revision) return;
      collecting = false; scanPointer = null; $("conversation-loading").hidden = true; display(result);
    } catch (error) { if (token === revision) { collecting = false; scanPointer = null; configure(); $("conversation-read-error").textContent = error.message; $("conversation-read-error").hidden = false; showDiagnostics(true); } }
    finally { $("conversation-load").disabled = false; }
  });
  function showDiagnostics(show) {
    $("conversation-diagnostics").hidden = !show || !diagnostics;
    $("conversation-diagnostics-note").textContent = "Thông số vùng cuộn và số tin; không chứa nội dung, tên người gửi hoặc địa chỉ cuộc trò chuyện.";
    $("conversation-copy-diagnostics").textContent = "Sao chép thông tin lỗi";
  }
  $("conversation-copy-diagnostics").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2)); $("conversation-copy-diagnostics").textContent = "Đã sao chép"; }
    catch { $("conversation-copy-diagnostics").textContent = "Chưa sao chép được · thử lại"; }
  });
  $("conversation-stop").addEventListener("click", () => { $("conversation-stop").disabled = true; $("conversation-load-count").textContent = "Đang dừng tải…"; stop(); });
  $("conversation-all").addEventListener("click", () => { const boxes = [...$("conversation-messages").querySelectorAll('input[type="checkbox"]')], next = !boxes.every(el => el.checked); boxes.forEach(el => { el.checked = next; }); count(); });
  $("conversation-cancel").addEventListener("click", () => { revision++; stop(); scanPointer = null; collecting = false; context = previous?.context || null; stale = Boolean(previous?.stale); previous = null; data = null; closePicker(); $("conversation-scope").hidden = !context; });
  $("conversation-refresh").addEventListener("click", () => { revision++; context = null; configure(); });
  $("conversation-continue").addEventListener("click", async () => {
    const button = $("conversation-continue"), token = ++revision; button.disabled = true;
    try {
      const rows = selected(), text = transcript(rows), target = {...data.context, messageIds: rows.map(el => el.dataset.id)};
      if (!rows.length || text.length > (target.history ? 200000 : 8000) || rows.length > (target.history ? 2000 : 30) || stale) throw new Error("Chọn lại phạm vi hội thoại hợp lệ.");
      if (target.scope) target.scope = {...target.scope, collected_count: rows.length};
      await message({type: "VALIDATE_CONVERSATION", context: target});
      if (token !== revision) return;
      options.apply(text); context = target; closePicker(); data = null; previous = null; $("conversation-messages").replaceChildren();
      $("conversation-scope").hidden = false; $("conversation-scope-text").textContent = `${rows.length} tin đã chọn · ${PhishLensChatPlatforms.label(context.platform)}`;
      options.controls(); await options.prepare();
    } catch (error) { options.error(error); count(); }
  });
  async function validate() { if (context) { if (stale) throw new Error("Hội thoại đã thay đổi. Tải lại phạm vi trước khi gửi."); await message({type: "VALIDATE_CONVERSATION", context}); } }
  function changed(tabId, id) {
    const active = context || data?.context; if (active?.tabId !== tabId || active.id !== id) return;
    stale = true; $("consent").checked = false; $("confirm").disabled = true; $("conversation-stale").hidden = false;
    if (context) options.error(new Error("Hội thoại đã thay đổi. Tải lại phạm vi trước khi gửi hoặc đối chiếu.")); else count();
  }
  async function restore(value, resultOnly = false) {
    context = value; data = null; stale = false; closePicker();
    if (context) {
      try { await validate(); } catch (error) { if (!resultOnly) throw error; stale = true; }
      $("conversation-scope").hidden = false; $("conversation-scope-text").textContent = `${context.messageIds.length} tin đã chọn · ${PhishLensChatPlatforms.label(context.platform || "zalo")}${stale ? " · Bản kết quả trước đó" : ""}`;
    }
  }
  function render(result, parent) {
    if (result.analysis_target !== "conversation") return;
    const batch = result.conversation_batch;
    parent.append(make("p", batch ? `${batch.scope.collected_count} tin trong phạm vi đã chọn · Đã xử lý ${batch.completed_parts}/${batch.total_parts} phần. ${batch.stopped ? "Lượt kiểm tra đã dừng; kết quả chỉ áp dụng cho phần hoàn tất." : ""} ${batch.limitation}` : "Nhận định áp dụng cho đoạn hội thoại đã chọn.", "conversation-result-scope"));
    if (batch) {
      const details = make("details", undefined, "result-details"); details.append(make("summary", "Kết quả từng phần · " + batch.completed_parts));
      for (const part of batch.parts) {
        const row = make("section", undefined, "conversation-part"); row.append(make("strong", `Phần ${part.part} · ${part.risk_level}`), make("p", part.result.llm.verdict?.summary || "Chưa phân tích được phần này.")); details.append(row);
      }
      parent.append(details);
    }
    if (!context) return; const bound = context;
    for (const item of parent.querySelectorAll(".evidence-item")) {
      const quote = item.querySelector("blockquote")?.textContent; if (!quote) continue;
      const button = make("button", "Xem tin gốc ↗", "inline-link conversation-evidence"); button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try { if (context !== bound || stale) throw new Error("Tải lại hội thoại để đối chiếu."); await message({type: "FOCUS_CONVERSATION", context: bound, quote}); }
        catch (error) { options.error(error); } finally { button.disabled = false; }
      }); item.append(button);
    }
  }
  window.addEventListener("pagehide", stop);
  return {open, forget, validate, changed, restore, render, context: () => context, pickerOpen: () => !$("conversation-picker").hidden};
};
