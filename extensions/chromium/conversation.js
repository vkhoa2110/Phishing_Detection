"use strict";
globalThis.PhishLensConversation = (() => {
  const platforms = PhishLensChatPlatforms, supported = url => Boolean(platforms.detect(url));
  const panel = sender => sender.id === chrome.runtime.id && sender.url?.split(/[?#]/)[0] === chrome.runtime.getURL("check.html");
  const page = sender => sender.id === chrome.runtime.id && sender.frameId === 0 && sender.tab && supported(sender.url);
  async function active(tab) {
    const [selected] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!supported(tab.url) || tab.incognito || selected?.id !== tab.id) throw new Error("Chọn tab Zalo, Messenger hoặc Telegram Web có cuộc trò chuyện cần kiểm tra.");
  }
  async function inject(tabId) {
    const tab = await chrome.tabs.get(tabId); await active(tab);
    const [{documentId}] = await chrome.scripting.executeScript({target: {tabId}, files: ["conversation-platforms.js", "conversation-reader.js", "conversation-history.js"]});
    await chrome.scripting.executeScript({target: {tabId, documentIds: [documentId]}, func: async () => {
      // A newly opened thread can render its main pane before its message list.
      // Wait briefly for the list rather than immediately reporting no chat.
      for (let attempt = 0; attempt < 8; attempt++) {
        try { PhishLensConversationReader.history.root(); return; } catch { await new Promise(resolve => setTimeout(resolve, 250)); }
      }
    }});
    await active(await chrome.tabs.get(tabId));
    return {tab, documentId};
  }
  async function read(tabId) {
    const {tab, documentId} = await inject(tabId);
    const [value] = await chrome.scripting.executeScript({target: {tabId, documentIds: [documentId]}, func: () => {
      try { return PhishLensConversationReader.read(); } catch (error) { return {error: error.message}; }
    }});
    if (value.result?.error || !value.result?.messages) throw new Error(value.result?.error || "Chưa đọc được đoạn hội thoại.");
    await active(await chrome.tabs.get(tabId));
    return {...value.result, context: {tabId, documentId, id: value.result.id, platform: platforms.detect(tab.url).id}};
  }
  async function scan(message) {
    let tab, documentId;
    if (message.action === "start") ({tab, documentId} = await inject(message.tabId));
    else { tab = await chrome.tabs.get(message.tabId); documentId = message.documentId; await active(tab); }
    if (!["start", "status", "cancel"].includes(message.action) || typeof documentId !== "string") throw new Error("Chọn lại phạm vi hội thoại.");
    const [value] = await chrome.scripting.executeScript({target: {tabId: tab.id, documentIds: [documentId]}, func: (action, options, id) => {
      try { return PhishLensConversationHistory[action](action === "start" ? options : id); } catch (error) { return {error: error.message}; }
    }, args: [message.action, message.options || null, message.scanId || null]});
    if (!value.result || value.result.error) throw new Error(value.result?.error || "Chưa tải được hội thoại.");
    const result = value.result;
    if (result.result) result.result.context = {tabId: tab.id, documentId, id: result.result.id, platform: platforms.detect(tab.url).id, scope: result.result.scope, history: true};
    return {...result, tabId: tab.id, documentId};
  }
  async function invoke(context, method, quote) {
    if (!Number.isInteger(context?.tabId) || typeof context.documentId !== "string" || !/^[a-f0-9-]{36}$/.test(context.id || "") ||
        !Array.isArray(context.messageIds) || !context.messageIds.length || context.messageIds.length > (context.history ? 2000 : 30) || context.messageIds.some(id => !/^[a-f0-9-]{36}$/.test(id))) throw new Error("Đọc lại và chọn các tin nhắn cần kiểm tra.");
    const tab = await chrome.tabs.get(context.tabId); await active(tab);
    if (context.platform && context.platform !== platforms.detect(tab.url).id) throw new Error("Nền tảng đã thay đổi. Hãy chọn lại tin nhắn.");
    const [value] = await chrome.scripting.executeScript({target: {tabId: tab.id, documentIds: [context.documentId]}, func: (context, method, quote) => {
      try { const reader = globalThis.PhishLensConversationReader; if (!reader) throw new Error("Trang đã tải lại. Hãy đọc lại hội thoại."); return reader[method](context.id, context.messageIds, quote); }
      catch (error) { return {error: error.message}; }
    }, args: [context, method, quote || ""]});
    if (value.result?.error || !value.result) throw new Error(value.result?.error || "Đoạn hội thoại đã thay đổi.");
    return value.result;
  }
  async function settings() {
    const {chatAssistSites, chatAssistEnabled} = await chrome.storage.local.get(["chatAssistSites", "chatAssistEnabled"]);
    return Object.fromEntries(platforms.all.map(site => [site.id, Boolean(chatAssistSites?.[site.id] ?? (site.id === "zalo" && chatAssistEnabled))]));
  }
  let syncing = Promise.resolve();
  function queued(action) {
    syncing = syncing.catch(() => {}).then(action); return syncing;
  }
  async function applySettings() {
    const sites = await settings(), tabs = (await chrome.tabs.query({})).filter(tab => !tab.incognito);
    for (const site of platforms.all) {
      sites[site.id] = Boolean(sites[site.id] && await chrome.permissions.contains({origins: site.origins}));
      const id = "phishlens-" + site.id, existing = await chrome.scripting.getRegisteredContentScripts({ids: [id]});
      if (sites[site.id] && (!existing.length || !existing[0].js.includes("conversation-platforms.js"))) {
        if (existing.length) await chrome.scripting.unregisterContentScripts({ids: [id]});
        await chrome.scripting.registerContentScripts([{id, js: ["conversation-platforms.js", "conversation-helper.js"], matches: site.matches, persistAcrossSessions: true, runAt: "document_idle"}]);
      }
      if (!sites[site.id] && existing.length) await chrome.scripting.unregisterContentScripts({ids: [id]});
    }
    await chrome.storage.local.set({chatAssistSites: sites, chatAssistEnabled: sites.zalo});
    await Promise.allSettled(tabs.filter(tab => supported(tab.url)).map(tab => sites[platforms.detect(tab.url).id] ?
      chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["conversation-platforms.js", "conversation-helper.js"]}) :
      chrome.tabs.sendMessage(tab.id, {type: "STOP_CHAT_HELPER"})));
    return {enabled: sites.zalo, sites};
  }
  const sync = () => queued(applySettings);
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["READ_CONVERSATION", "SCAN_CONVERSATION", "VALIDATE_CONVERSATION", "FOCUS_CONVERSATION", "OPEN_CONVERSATION", "SET_CHAT_ASSIST", "GET_CHAT_SETTINGS", "CHAT_CONTENT_CHANGED"].includes(message?.type)) return;
    const prepared = message.type === "OPEN_CONVERSATION" && page(sender) ? PhishLensWorkspace.preparePanel(sender.tab.windowId) : null;
    (async () => {
      if (!panel(sender) && !page(sender)) throw new Error("Thao tác chỉ dành cho PhishLens và các trang hội thoại được hỗ trợ.");
      if (message.type === "GET_CHAT_SETTINGS") { const sites = await settings(); return {enabled: sites.zalo, sites}; }
      if (message.type === "CHAT_CONTENT_CHANGED" && page(sender)) { chrome.runtime.sendMessage({type: "CONVERSATION_CHANGED", tabId: sender.tab.id, contextId: message.contextId}).catch(() => {}); return {ok: true}; }
      if (message.type === "OPEN_CONVERSATION" && page(sender)) {
        await active(sender.tab);
        await PhishLensWorkspace.open({conversationRequest: true, sourceTab: sender.tab.id}, sender.tab.windowId, true, prepared);
        return {opened: true};
      }
      if (!panel(sender)) throw new Error("Mở bảng PhishLens để chọn và duyệt nội dung.");
      if (message.type === "SET_CHAT_ASSIST") {
        const site = platforms.get(message.platform || "zalo");
        if (!site) throw new Error("Nền tảng chưa được hỗ trợ.");
        if (message.enabled && !await chrome.permissions.contains({origins: site.origins})) throw new Error("Cấp quyền " + site.label + " trước khi bật trợ lý.");
        return queued(async () => {
          const sites = await settings(); sites[site.id] = Boolean(message.enabled);
          await chrome.storage.local.set({chatAssistSites: sites, chatAssistEnabled: sites.zalo}); return applySettings();
        });
      }
      if (message.type === "READ_CONVERSATION") return read(message.tabId);
      if (message.type === "SCAN_CONVERSATION") return scan(message);
      if (message.type === "VALIDATE_CONVERSATION") return invoke(message.context, "validate");
      if (message.type === "FOCUS_CONVERSATION") return invoke(message.context, "focus", message.quote);
      throw new Error("Thao tác hội thoại chưa hợp lệ.");
    })().then(respond, error => respond({error: error.message}));
    return true;
  });
  chrome.permissions.onRemoved.addListener(() => sync().catch(() => {}));
  chrome.tabs.onUpdated.addListener((id, change, tab) => {
    if (!change.url || tab.incognito) return;
    if (supported(change.url)) sync().catch(() => {});
    else chrome.tabs.sendMessage(id, {type: "STOP_CHAT_HELPER"}).catch(() => {});
  });
  chrome.runtime.onInstalled.addListener(() => sync().catch(() => {}));
  chrome.runtime.onStartup.addListener(() => sync().catch(() => {}));
  return {origins: platforms.all.flatMap(site => site.origins), read, validate: context => invoke(context, "validate"), sync};
})();
