"use strict";
// Optional background URL assistance. Only localhost is contacted; no page DOM,
// OCR, AI or history writes. Event-driven, bounded and independent of panel life.
globalThis.PhishLensAssistant = (() => {
  const running = new Map(), prefix = "assistant-tab-", alarm = "phishlens-resume", preferences = ["floatingEnabled", "autoCheckEnabled", "assistantPausedUntil", "hiddenSites", "dockPosition"];
  const panel = sender => sender.id === chrome.runtime.id && sender.url?.split(/[?#]/)[0] === chrome.runtime.getURL("check.html");
  const page = sender => sender.id === chrome.runtime.id && sender.frameId === 0 && sender.tab && /^https?:\/\//.test(sender.url || "");
  const digest = async text => [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
  async function settings(tab) {
    const local = await chrome.storage.local.get(preferences);
    const allowed = await chrome.permissions.contains({origins: ["<all_urls>"]});
    const hidden = tab?.url && (local.hiddenSites || []).includes(await digest(new URL(tab.url).hostname));
    return {floatingEnabled: Boolean(local.floatingEnabled && allowed), autoCheckEnabled: Boolean(local.autoCheckEnabled && allowed),
      pausedUntil: local.assistantPausedUntil > Date.now() ? local.assistantPausedUntil : 0, visible: !hidden, hiddenCount: (local.hiddenSites || []).length,
      position: local.dockPosition || {edge: "right", ratio: .88}};
  }
  async function credentials() {
    const [local, session] = await Promise.all([chrome.storage.local.get("connection"), chrome.storage.session.get("connection")]);
    const connection = local.connection || session.connection;
    if (!connection || connection.expires_at * 1000 <= Date.now()) return null;
    try {
      const base = new URL(connection.base);
      if (base.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(base.hostname) || base.username || base.password || base.pathname !== "/" || base.search || base.hash) return null;
      return {...connection, base: base.origin};
    } catch { return null; }
  }
  async function state(tab) {
    const config = await settings(tab);
    const record = tab?.url ? (await chrome.storage.session.get(prefix + tab.id))[prefix + tab.id] : null;
    const valid = record && Date.now() - record.created < 300000 && record.digest === await digest(tab.url);
    return {...config, page: valid ? record : {status: "idle"}, connected: Boolean(await credentials())};
  }
  function broadcast(tabId, payload) {
    chrome.tabs.sendMessage(tabId, {type: "ASSISTANT_UPDATE", state: payload}, {frameId: 0}).catch(() => {});
    chrome.runtime.sendMessage({type: "ASSISTANT_CHANGED", tabId}).catch(() => {});
  }
  async function publish(tab, record) {
    const current = await chrome.tabs.get(tab.id).catch(() => null);
    if (!current || current.url !== tab.url) return;
    await chrome.storage.session.set({[prefix + tab.id]: record});
    const text = record.status === "ok" ? ({HIGH: "!", WARNING: "!", UNKNOWN: "?"}[record.risk] || "") : "";
    await chrome.action.setBadgeText({tabId: tab.id, text});
    if (text) await chrome.action.setBadgeBackgroundColor({tabId: tab.id, color: record.risk === "HIGH" ? "#c14451" : "#b77a23"});
    broadcast(tab.id, await state(current));
  }
  async function check(tab, manual = false) {
    if (!tab?.id || !/^https?:\/\//.test(tab.url || "") || tab.url.length > 8000 || tab.incognito) return {status: "unsupported"};
    const config = await settings(tab);
    if (!manual && (!config.autoCheckEnabled || config.pausedUntil || !config.visible)) return {status: "paused"};
    const hash = await digest(tab.url), saved = (await chrome.storage.session.get(prefix + tab.id))[prefix + tab.id];
    if (!manual && saved?.digest === hash && saved.status !== "checking" && Date.now() - saved.created < (saved.status === "ok" ? 300000 : 15000)) { await publish(tab, saved); return saved; }
    const connection = await credentials();
    if (!connection) { const record = {digest: hash, created: Date.now(), status: "disconnected"}; await publish(tab, record); return record; }
    if (!manual && new URL(tab.url).origin === connection.base) return {status: "own_application"};
    // Reserve synchronously after the last await: concurrent navigation, focus
    // and settings events must not launch duplicate requests for the same tab.
    if (running.has(tab.id) || running.size >= 2) return {status: "busy"};
    const controller = new AbortController(); running.set(tab.id, controller);
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      await publish(tab, {digest: hash, created: Date.now(), status: "checking"});
      const response = await fetch(connection.base + "/api/extension/analyze", {method: "POST", credentials: "omit", cache: "no-store", signal: controller.signal,
        headers: {"Content-Type": "application/json", "X-PhishLens-Extension": chrome.runtime.id, ...(connection.token ? {Authorization: "Bearer " + connection.token} : {})},
        body: JSON.stringify({mode: "url", text: tab.url, use_llm: false, use_rag: false, include_ml: false, consent: false, save_history: false, save_content: false})});
      if (!response.ok) throw new Error(response.status === 401 ? "disconnected" : "unavailable");
      const data = await response.json(), url = data.urls?.[0];
      if (url?.status !== "ok" || !["HIGH", "WARNING", "LOW", "UNKNOWN"].includes(url.risk_level) || typeof url.score !== "number" || !Number.isFinite(url.score) || url.score < 0 || url.score > 1) throw new Error("unavailable");
      const record = {digest: hash, created: Date.now(), status: "ok", risk: url.risk_level, score: url.score};
      // Recheck opt-in after awaiting the network: pausing/revoking must win.
      const latest = await settings(tab);
      if (!manual && (!latest.autoCheckEnabled || latest.pausedUntil || !latest.visible)) return {status: "paused"};
      const activeConnection = await credentials();
      if (activeConnection?.token !== connection.token || activeConnection?.base !== connection.base) return {status: "stale"};
      await publish(tab, record); return record;
    } catch (reason) {
      if (controller.signal.aborted) return {status: "cancelled"};
      const latest = await settings(tab);
      if (!manual && (!latest.autoCheckEnabled || latest.pausedUntil || !latest.visible)) return {status: "paused"};
      const record = {digest: hash, created: Date.now(), status: reason.message === "disconnected" ? "disconnected" : "unavailable"};
      await publish(tab, record); return record;
    } finally { clearTimeout(timer); if (running.get(tab.id) === controller) running.delete(tab.id); }
  }
  async function refresh() {
    const tabs = await chrome.tabs.query({});
    await Promise.allSettled(tabs.map(async tab => {
      const config = await state(tab); broadcast(tab.id, config);
      if (!config.autoCheckEnabled || config.pausedUntil || !config.visible) {
        running.get(tab.id)?.abort(); await chrome.action.setBadgeText({tabId: tab.id, text: ""});
      }
    }));
    if (globalThis.PhishLensCapture) await PhishLensCapture.syncDock();
  }
  function open(tab, autoLocal = false) {
    // Do not await anything before opening: preserve Chrome's user gesture.
    return PhishLensWorkspace.open({mode: "url", text: tab.url || "", autoLocal}, tab.windowId);
  }
  async function scheduleResume() {
    const {assistantPausedUntil} = await chrome.storage.local.get("assistantPausedUntil");
    if (assistantPausedUntil > Date.now()) await chrome.alarms.create(alarm, {when: assistantPausedUntil});
    else { await chrome.alarms.clear(alarm); if (assistantPausedUntil) await chrome.storage.local.remove("assistantPausedUntil"); }
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["GET_ASSISTANT", "CONFIGURE_ASSISTANT", "ASSISTANT_PAUSE", "DOCK_POSITION", "HIDE_SITE", "RESET_HIDDEN_SITES", "OPEN_ASSISTANT", "CHECK_PAGE"].includes(message?.type)) return;
    const trustedPanel = panel(sender), trustedPage = page(sender);
    if (!trustedPanel && !trustedPage) { respond({error: "Nguồn yêu cầu không hợp lệ."}); return; }
    if (message.type === "OPEN_ASSISTANT" && trustedPage) {
      open(sender.tab, Boolean(message.check)).then(() => respond({opened: true}), () => respond({error: "Bấm biểu tượng PhishLens trên thanh trình duyệt để mở bảng."})); return true;
    }
    (async () => {
      const tab = trustedPage ? sender.tab : Number.isInteger(message.tabId) ? await chrome.tabs.get(message.tabId).catch(() => null) : null;
      if (message.type === "GET_ASSISTANT") return state(tab);
      if (message.type === "CONFIGURE_ASSISTANT") {
        if (!trustedPanel || !["autoCheckEnabled", "floatingEnabled"].includes(message.key) || typeof message.enabled !== "boolean") throw new Error("Tùy chọn không hợp lệ.");
        if (message.enabled && !await chrome.permissions.contains({origins: ["<all_urls>"]})) throw new Error("Cần cấp quyền trang web để bật hỗ trợ này.");
        await chrome.storage.local.set({[message.key]: message.enabled}); await refresh();
        if (message.enabled && message.key === "autoCheckEnabled") (await chrome.tabs.query({active: true})).forEach(item => { check(item).catch(() => {}); });
      } else if (message.type === "ASSISTANT_PAUSE") {
        if (!trustedPanel && !trustedPage) throw new Error("Nguồn yêu cầu không hợp lệ.");
        if (typeof message.paused !== "boolean") throw new Error("Tùy chọn không hợp lệ.");
        if (message.paused) await chrome.storage.local.set({assistantPausedUntil: Date.now() + 3600000});
        else await chrome.storage.local.remove("assistantPausedUntil");
        await scheduleResume(); await refresh();
        if (!message.paused && tab) check(tab).catch(() => {});
      } else if (message.type === "DOCK_POSITION") {
        if (!trustedPage || !["left", "right"].includes(message.edge) || typeof message.ratio !== "number" || !Number.isFinite(message.ratio)) throw new Error("Vị trí không hợp lệ.");
        await chrome.storage.local.set({dockPosition: {edge: message.edge, ratio: Math.min(.96, Math.max(.04, message.ratio))}});
      } else if (message.type === "HIDE_SITE") {
        if (!trustedPage) throw new Error("Chọn thao tác từ nút nổi trên trang.");
        const hash = await digest(new URL(tab.url).hostname), {hiddenSites = []} = await chrome.storage.local.get("hiddenSites");
        await chrome.storage.local.set({hiddenSites: [...new Set([...hiddenSites, hash])].slice(-100)}); await refresh();
      } else if (message.type === "RESET_HIDDEN_SITES") {
        if (!trustedPanel) throw new Error("Mở cài đặt để hiện lại nút.");
        await chrome.storage.local.remove("hiddenSites"); await refresh();
      } else if (message.type === "CHECK_PAGE") {
        if (!tab || trustedPage && !tab.active) throw new Error("Hãy kiểm tra tab đang xem.");
        return check(tab, true);
      }
      return state(tab);
    })().then(respond, reason => respond({error: reason.message}));
    return true;
  });
  chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
    if (change.status === "loading" || change.url) { running.get(tabId)?.abort(); running.delete(tabId); chrome.action.setBadgeText({tabId, text: ""}).catch(() => {}); chrome.storage.session.remove(prefix + tabId); }
    if (change.status === "complete" || change.url && change.status !== "loading") check(tab).catch(() => {});
  });
  chrome.tabs.onActivated.addListener(({tabId}) => { chrome.tabs.get(tabId).then(tab => check(tab)).catch(() => {}); });
  chrome.tabs.onRemoved.addListener(tabId => { running.get(tabId)?.abort(); chrome.storage.session.remove(prefix + tabId); });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (!["local", "session"].includes(area) || !changes.connection) return;
    (async () => {
      running.forEach(controller => controller.abort());
      running.clear();
      const memory = await chrome.storage.session.get(null);
      await chrome.storage.session.remove(Object.keys(memory).filter(key => key.startsWith(prefix)));
      await refresh();
      (await chrome.tabs.query({active: true})).forEach(tab => { check(tab).catch(() => {}); });
    })().catch(() => {});
  });
  chrome.permissions.onRemoved.addListener(() => {
    (async () => {
      if (!await chrome.permissions.contains({origins: ["<all_urls>"]})) {
        await chrome.storage.local.set({autoCheckEnabled: false}); await refresh();
      }
    })().catch(() => {});
  });
  chrome.alarms.onAlarm.addListener(info => {
    if (info.name === alarm) scheduleResume().then(refresh).then(async () => {
      (await chrome.tabs.query({active: true})).forEach(tab => { check(tab).catch(() => {}); });
    }).catch(() => {});
  });
  chrome.runtime.onStartup.addListener(() => { scheduleResume().then(refresh).catch(() => {}); });
  chrome.runtime.onInstalled.addListener(() => { scheduleResume().catch(() => {}); });
  return {settings, state, refresh, check};
})();
