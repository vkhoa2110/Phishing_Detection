"use strict";
globalThis.PhishLensMail = (() => {
  const origins = ["https://mail.google.com/*", "https://outlook.live.com/*", "https://outlook.office.com/*", "https://outlook.office365.com/*"], scriptID = "phishlens-email";
  const hosts = new Set(origins.map(value => new URL(value).hostname));
  function supported(url) { try { const parsed = new URL(url); return parsed.protocol === "https:" && hosts.has(parsed.hostname); } catch { return false; } }
  const panel = sender => sender.id === chrome.runtime.id && sender.url?.split(/[?#]/)[0] === chrome.runtime.getURL("check.html");
  const page = sender => sender.id === chrome.runtime.id && sender.tab && sender.frameId === 0 && supported(sender.url);
  async function active(tab) {
    const [current] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!supported(tab.url) || tab.incognito || current?.id !== tab.id) throw new Error("Chọn tab Gmail hoặc Outlook có email đang mở.");
  }
  async function read(tab) {
    await active(tab);
    const [{documentId}] = await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["mail-reader.js"]});
    const [result] = await chrome.scripting.executeScript({target: {tabId: tab.id, documentIds: [documentId]}, func: () => {
      try { return globalThis.PhishLensMailReader.read(); } catch (error) { return {error: error.message}; }
    }});
    await chrome.scripting.executeScript({target: {tabId: tab.id, documentIds: [documentId]}, func: () => true});
    await active(await chrome.tabs.get(tab.id));
    if (result.error || result.result?.error) throw new Error(result.error || result.result.error);
    if (!result.result?.text || result.result.text.length > 8000) throw new Error("Nội dung email chưa hợp lệ.");
    return result.result;
  }
  async function sync() {
    const {mailAssistEnabled} = await chrome.storage.local.get("mailAssistEnabled");
    const allowed = await chrome.permissions.contains({origins}), enabled = Boolean(mailAssistEnabled && allowed);
    const existing = await chrome.scripting.getRegisteredContentScripts({ids: [scriptID]});
    if (enabled && !existing.length) await chrome.scripting.registerContentScripts([{id: scriptID, js: ["mail-reader.js"], matches: origins, persistAcrossSessions: true, runAt: "document_idle"}]);
    if (!enabled && existing.length) await chrome.scripting.unregisterContentScripts({ids: [scriptID]});
    if (mailAssistEnabled && !allowed) await chrome.storage.local.set({mailAssistEnabled: false});
    const tabs = await chrome.tabs.query({});
    await Promise.allSettled(tabs.filter(tab => supported(tab.url) && !tab.incognito).map(tab => enabled ? chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["mail-reader.js"]}).then(() => chrome.scripting.executeScript({target: {tabId: tab.id}, func: () => globalThis.PhishLensMailReader.start()})) : chrome.tabs.sendMessage(tab.id, {type: "STOP_MAIL_HELPER"})));
    return {enabled};
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["READ_EMAIL", "SET_MAIL_ASSIST", "GET_MAIL_SETTINGS", "MAIL_READY", "OPEN_EMAIL"].includes(message?.type)) return;
    (async () => {
      if (!panel(sender) && !page(sender)) throw new Error("Thao tác chỉ dành cho PhishLens và trang email được hỗ trợ.");
      const {mailAssistEnabled} = await chrome.storage.local.get("mailAssistEnabled");
      if (message.type === "GET_MAIL_SETTINGS") return {enabled: Boolean(mailAssistEnabled)};
      if (message.type === "READ_EMAIL" && panel(sender)) return read(await chrome.tabs.get(message.tabId));
      if (message.type === "SET_MAIL_ASSIST" && panel(sender)) {
        if (message.enabled && !await chrome.permissions.contains({origins})) throw new Error("Cấp quyền Gmail/Outlook để dùng trợ lý email.");
        await chrome.storage.local.set({mailAssistEnabled: Boolean(message.enabled)}); return sync();
      }
      if (!page(sender) || !mailAssistEnabled) throw new Error("Bật trợ lý email trong PhishLens trước.");
      await active(sender.tab);
      if (message.type === "MAIL_READY") { chrome.runtime.sendMessage({type: "EMAIL_CHANGED", tabId: sender.tab.id}).catch(() => {}); return {ready: true}; }
      if (message.type === "OPEN_EMAIL") {
        const mail = await read(sender.tab);
        await openCheck({mode: "text", text: mail.text, review: true, mail: {provider: mail.provider, subject: mail.subject}});
        return {opened: true};
      }
      throw new Error("Thao tác email không hợp lệ.");
    })().then(respond, error => respond({error: error.message}));
    return true;
  });
  chrome.permissions.onRemoved.addListener(() => sync().catch(() => {}));
  chrome.runtime.onInstalled.addListener(() => sync().catch(() => {}));
  chrome.runtime.onStartup.addListener(() => sync().catch(() => {}));
  return {origins, sync};
})();
