"use strict";
// Event driven: no polling/keep-alive, and no screenshot persisted to storage.
globalThis.PhishLensCapture = (() => {
  const buffers = new Map(), captures = new Set(), helperID = "phishlens-floating", origins = ["<all_urls>"], jobKey = id => "region-job-" + id;
  const panelSender = sender => sender.id === chrome.runtime.id && sender.url?.split(/[?#]/)[0] === chrome.runtime.getURL("check.html");
  const pageSender = sender => sender.id === chrome.runtime.id && sender.tab && sender.frameId === 0 && /^https?:\/\//.test(sender.url || "");
  function signal(message) { chrome.runtime.sendMessage(message).catch(() => {}); }
  function error(windowId, message) {
    signal({type: "CAPTURE_ERROR", windowId, message});
    chrome.action.setBadgeText({text: "!"}); chrome.action.setBadgeBackgroundColor({color: "#ae3e4c"});
  }
  async function start(tab, reviewInWindow = true, captureMode = "region") {
    if (!tab?.id || !/^https?:\/\//i.test(tab.url || "")) throw new Error("Mở trang web cần kiểm tra, rồi bấm PhishLens trên tab đó. Không khoanh được trang chrome:// hoặc trang extension.");
    // Select on the page first. Opening a panel here resizes the page and adds
    // an unnecessary UI step before the user can draw their rectangle.
    try {
      const [{documentId}] = await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["region.js"]});
      const nonce = crypto.randomUUID();
      await chrome.storage.session.set({[jobKey(tab.id)]: {nonce, documentId, windowId: tab.windowId, reviewInWindow, created: Date.now()}});
      await chrome.scripting.executeScript({target: {tabId: tab.id, documentIds: [documentId]}, func: (value, mode) => globalThis.PhishLensRegion.start(value, mode), args: [nonce, captureMode]});
      await chrome.action.setBadgeText({text: ""});
      return {started: true};
    } catch (reason) {
      await chrome.storage.session.remove(jobKey(tab.id));
      if (/permission|access|cannot|missing/i.test(reason.message)) throw new Error("Bấm biểu tượng PhishLens trên tab này để cấp quyền tạm thời. Hoặc bật Nút nổi trong extension để khoanh vùng trên các trang web.");
      throw reason;
    }
  }
  function validate(rect, viewport) {
    const numbers = [rect?.x, rect?.y, rect?.width, rect?.height, viewport?.width, viewport?.height, viewport?.scrollX, viewport?.scrollY];
    if (numbers.some(value => typeof value !== "number" || !Number.isFinite(value)) || rect.x < 0 || rect.y < 0 || rect.width < 20 || rect.height < 20 || viewport.width < 20 || viewport.height < 20 || rect.x + rect.width > viewport.width + 1 || rect.y + rect.height > viewport.height + 1) throw new Error("Vùng chọn không hợp lệ. Hãy khoanh lại trên trang.");
  }
  async function checkPage(tabId, windowId, documentId, viewport) {
    const [active] = await chrome.tabs.query({active: true, windowId});
    if (active?.id !== tabId) throw new Error("Tab đã thay đổi. Hãy chọn lại vùng trên tab đang xem.");
    const [current] = await chrome.scripting.executeScript({target: {tabId, documentIds: [documentId]}, func: () => ({width: innerWidth, height: innerHeight, scrollX, scrollY, visible: document.visibilityState === "visible"})});
    if (current.documentId !== documentId || !current.result.visible || ["width", "height", "scrollX", "scrollY"].some(key => Math.abs(current.result[key] - viewport[key]) > 1)) throw new Error("Trang đã cuộn hoặc đổi kích thước. Hãy khoanh lại để tránh chụp nhầm vùng.");
  }
  async function selected(message, sender) {
    if (!pageSender(sender)) throw new Error("Vùng chọn không thuộc trang đang kiểm tra.");
    if (captures.has(sender.tab.id)) throw new Error("Vùng chọn đang được xử lý. Hãy chờ hoàn tất.");
    captures.add(sender.tab.id);
    try {
    const key = jobKey(sender.tab.id), stored = (await chrome.storage.session.get(key))[key];
    if (!stored || stored.nonce !== message.nonce || stored.documentId !== sender.documentId || Date.now() - stored.created > 120000) throw new Error("Vùng chọn đã hết hạn. Hãy khoanh lại.");
    await chrome.storage.session.remove(key); // One use, including failures.
    validate(message.rect, message.viewport);
    await checkPage(sender.tab.id, stored.windowId, stored.documentId, message.viewport);
    const uri = await chrome.tabs.captureVisibleTab(stored.windowId, {format: "png"});
    await checkPage(sender.tab.id, stored.windowId, stored.documentId, message.viewport);
    const bytes = Uint8Array.from(atob(uri.split(",")[1]), character => character.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], {type: "image/png"}));
    let cropped;
    try {
      const scaleX = bitmap.width / message.viewport.width, scaleY = bitmap.height / message.viewport.height, rect = message.rect;
      if (Math.abs(scaleX - scaleY) > Math.max(scaleX, scaleY) * .05) throw new Error("Kích thước hiển thị và ảnh chụp chưa khớp. Thoát chế độ giả lập thiết bị nếu đang bật, rồi khoanh lại.");
      const x = Math.floor(rect.x * scaleX), y = Math.floor(rect.y * scaleY);
      const width = Math.min(bitmap.width - x, Math.round(rect.width * scaleX)), height = Math.min(bitmap.height - y, Math.round(rect.height * scaleY));
      if (Math.min(width, height) < 20 || width * height > 12000000) throw new Error("Chọn vùng ít nhất 20 px mỗi chiều và dưới 12 triệu điểm ảnh.");
      const canvas = new OffscreenCanvas(width, height);
      canvas.getContext("2d").drawImage(bitmap, x, y, width, height, 0, 0, width, height);
      cropped = await canvas.convertToBlob({type: "image/png"});
    } finally { bitmap.close(); }
    if (cropped.size > 5 * 1024 * 1024) throw new Error("Vùng ảnh lớn hơn 5 MB. Hãy khoanh sát phần cần đọc.");
    const output = new Uint8Array(await cropped.arrayBuffer()); let binary = "";
    for (let offset = 0; offset < output.length; offset += 32768) binary += String.fromCharCode(...output.subarray(offset, offset + 32768));
    const result = {dataURL: "data:image/png;base64," + btoa(binary), created: Date.now(), captureMode: message.rect.x === 0 && message.rect.y === 0 && message.rect.width === message.viewport.width && message.rect.height === message.viewport.height ? "viewport" : "region"};
    let destination = stored.windowId;
    if (stored.reviewInWindow) {
      // Opening a review window after capture avoids sidePanel's transient
      // user-gesture requirement and preserves the original viewport.
      const win = await PhishLensWorkspace.popup(null);
      destination = win.id;
    }
    buffers.set(destination, result);
    setTimeout(() => { if (buffers.get(destination) === result) buffers.delete(destination); }, 30000);
    signal({type: "REGION_AVAILABLE", windowId: destination});
    return {captured: true};
    } finally { captures.delete(sender.tab.id); }
  }
  async function syncDock() {
    const {dockPinned, autoCheckEnabled} = await chrome.storage.local.get(["dockPinned", "autoCheckEnabled"]);
    const allowed = await chrome.permissions.contains({origins});
    const enabled = Boolean((dockPinned || autoCheckEnabled) && allowed);
    const existing = await chrome.scripting.getRegisteredContentScripts({ids: [helperID]});
    if (enabled && !existing.length) await chrome.scripting.registerContentScripts([{id: helperID, js: ["floating.js"], matches: ["http://*/*", "https://*/*"], persistAcrossSessions: true, runAt: "document_idle"}]);
    if (!enabled && existing.length) await chrome.scripting.unregisterContentScripts({ids: [helperID]});
    const tabs = await chrome.tabs.query({});
    await Promise.allSettled(tabs.filter(tab => !enabled || /^https?:\/\//.test(tab.url || "")).map(tab => enabled ? chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["floating.js"]}) : chrome.tabs.sendMessage(tab.id, {type: "HIDE_FLOATING"})));
    if (!allowed && dockPinned) await chrome.storage.local.set({floatingEnabled: false, dockPinned: false});
    return {enabled};
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["START_REGION", "REGION_SELECTED", "REGION_CANCEL", "TAKE_REGION", "SET_FLOATING"].includes(message?.type)) return;
    (async () => {
      if (message.type === "START_REGION") {
        if (panelSender(sender)) {
          const tab = await chrome.tabs.get(message.tabId);
          const source = await chrome.windows.get(sender.tab?.windowId || tab.windowId);
          if (tab.windowId !== source.id && source.type !== "popup" || !tab.active) throw new Error("Chọn tab web đang xem để khoanh vùng.");
          if (source.type === "popup") await chrome.windows.update(tab.windowId, {focused: true});
          return start(tab, source.type === "popup", message.captureMode === "viewport" ? "viewport" : "region");
        }
        if (pageSender(sender)) return start(sender.tab, true, message.captureMode === "viewport" ? "viewport" : "region");
        throw new Error("Hãy mở PhishLens để chọn vùng.");
      }
      if (message.type === "REGION_SELECTED") return selected(message, sender);
      if (message.type === "REGION_CANCEL") {
        if (pageSender(sender)) {
          const key = jobKey(sender.tab.id), job = (await chrome.storage.session.get(key))[key];
          if (job?.nonce === message.nonce && job.documentId === sender.documentId) {
            await chrome.storage.session.remove(key);
            if (["scroll", "resize", "viewport", "pointercancel", "timeout"].includes(message.reason)) signal({type: "CAPTURE_ERROR", windowId: job.windowId,
              message: message.reason === "timeout" ? "Vùng chọn đã hết thời gian. Bấm Khoanh vùng để thử lại." : "Đã hủy vùng chọn vì trang thay đổi trong lúc khoanh. Hãy khoanh lại khi trang ổn định."});
          }
        }
        return {cancelled: true};
      }
      if (!panelSender(sender)) throw new Error("Thao tác chỉ dùng trong bảng PhishLens.");
      if (message.type === "TAKE_REGION") {
        const result = buffers.get(message.windowId); buffers.delete(message.windowId);
        return result && Date.now() - result.created < 30000 ? result : {};
      }
      if (message.type === "SET_FLOATING") {
        if (message.enabled && !await chrome.permissions.contains({origins})) throw new Error("Cấp quyền trang web để bật nút nổi.");
        await chrome.storage.local.set({floatingEnabled: Boolean(message.enabled), dockPinned: Boolean(message.enabled)});
        return syncDock();
      }
    })().then(respond, reason => { error(sender.tab?.windowId, reason.message); respond({error: reason.message}); });
    return true;
  });
  chrome.tabs.onRemoved.addListener(tabId => { chrome.storage.session.remove(jobKey(tabId)); });
  chrome.tabs.onUpdated.addListener((tabId, change) => { if (change.status === "loading") chrome.storage.session.remove(jobKey(tabId)); });
  chrome.permissions.onRemoved.addListener(() => { syncDock().catch(() => {}); });
  chrome.runtime.onStartup.addListener(() => { syncDock().catch(() => {}); });
  chrome.runtime.onInstalled.addListener(() => { syncDock().catch(() => {}); });
  return {start, error, syncDock};
})();
