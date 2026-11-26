"use strict";
globalThis.PhishLensMail = (() => {
  const origins = ["https://mail.google.com/*", "https://outlook.live.com/*", "https://outlook.office.com/*", "https://outlook.office365.com/*"], scriptID = "phishlens-email";
  const hosts = new Set(origins.map(value => new URL(value).hostname));
  function supported(url) { try { const parsed = new URL(url); return parsed.protocol === "https:" && hosts.has(parsed.hostname); } catch { return false; } }
  const panel = sender => sender.id === chrome.runtime.id && sender.url?.split(/[?#]/)[0] === chrome.runtime.getURL("check.html");
  const page = sender => sender.id === chrome.runtime.id && sender.tab && sender.frameId === 0 && supported(sender.url);
  const starts = new Map();
  class InactiveMail extends Error {}
  async function active(tab) {
    const [current] = await chrome.tabs.query({active: true, windowId: tab.windowId});
    if (!supported(tab.url) || tab.incognito) throw new Error("Chọn tab Gmail hoặc Outlook có email đang mở.");
    if (current?.id !== tab.id) throw new InactiveMail("Chọn tab Gmail hoặc Outlook có email đang mở.");
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
    const {contextId, ...mail} = result.result;
    return {...mail, context: {tabId: tab.id, documentId, id: contextId}};
  }
  async function annotate(message) {
    const context = message.context;
    if (!Number.isInteger(context?.tabId) || typeof context.documentId !== "string" || typeof context.id !== "string" || !/^[a-f0-9-]{36}$/.test(context.id)) throw new Error("Đọc lại email trước khi đánh dấu.");
    if (typeof message.batchId !== "string" || !/^[a-f0-9-]{36}$/.test(message.batchId)) throw new Error("Kết quả đánh dấu chưa hợp lệ.");
    const tab = await chrome.tabs.get(context.tabId);
    if (!supported(tab.url) || tab.incognito) throw new Error("Mở lại email đã kiểm tra để xem dấu hiệu.");
    if (message.type === "ANNOTATE_EMAIL") await active(tab);
    const target = {tabId: context.tabId, documentIds: [context.documentId]};
    if (message.type === "ANNOTATE_EMAIL") {
      if (!Array.isArray(message.evidence) || message.evidence.length > 6 || !Array.isArray(message.urls) || message.urls.length > 50) throw new Error("Kết quả đánh dấu chưa hợp lệ.");
      await chrome.scripting.executeScript({target, files: ["mail-annotations.js"]});
    }
    const [result] = await chrome.scripting.executeScript({target, func: (type, payload) => {
      try {
        const annotations = globalThis.PhishLensMailAnnotations;
        if (type === "CLEAR_EMAIL_ANNOTATIONS") return annotations?.clear(payload.id, payload.batchId) || {active: false};
        if (!annotations) throw new Error("Đánh dấu lại email để xem dấu hiệu.");
        if (type === "FOCUS_EMAIL_ANNOTATION") {
          globalThis.PhishLensMailReader.current(payload.id);
          if (!annotations.status().active) throw new Error("Đánh dấu lại email để xem dấu hiệu.");
          return annotations.focus({batchId: payload.batchId});
        }
        return annotations.apply(payload);
      } catch (error) { return {error: error.message}; }
    }, args: [message.type, {id: context.id, batchId: message.batchId, evidence: message.evidence, urls: message.urls, quiet: Boolean(message.quiet)}]});
    if (result.error || result.result?.error) throw new Error(result.error || result.result.error);
    if (message.type === "FOCUS_EMAIL_ANNOTATION") { await chrome.tabs.update(tab.id, {active: true}); await chrome.windows.update(tab.windowId, {focused: true}); }
    return result.result;
  }
  async function fingerprint(mail, tab) {
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(tab.url + "\n" + mail.text));
    return Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, "0")).join("");
  }
  async function recordFor(mail, tab) {
    const stored = await chrome.storage.session.get(["mail-jobs-" + tab.id, "mail-job-" + tab.id]);
    const digest = await fingerprint(mail, tab);
    const cached = (stored["mail-jobs-" + tab.id] || []).find(item => item.fingerprint === digest && Date.now() - item.created < 900000);
    const current = stored["mail-job-" + tab.id];
    const bound = current?.context?.id === mail.context.id && Date.now() - current.created < 900000 ? current : null;
    const record = bound && (!cached || bound.created >= cached.created) ? bound : cached;
    return record ? {...record, context: mail.context} : null;
  }
  async function remember(record, mail, tab) {
    const key = "mail-jobs-" + tab.id, stored = await chrome.storage.session.get(key);
    record = {...record, fingerprint: await fingerprint(mail, tab)};
    const recent = (stored[key] || []).filter(item => item.fingerprint !== record.fingerprint && Date.now() - item.created < 900000).slice(-9);
    await chrome.storage.session.set({[key]: [...recent, record]});
    return record;
  }
  async function compact(record) {
    const job = await PhishLensJobs.status(record);
    if (job.status !== "complete") return {status: job.status, message: job.error?.message};
    const data = job.result, verdict = data.llm.status === "ok" ? data.llm.verdict : null;
    const explanation = data.llm.evidence_explanation?.status === "ok" ? data.llm.evidence_explanation : null;
    const evidence = (verdict?.evidence || []).map((item, index) => ({quote: item.quote,
      reason: explanation?.evidence.find(value => value.index === index)?.explanation || item.reason}));
    // Reuse completed evidence. Exact snapshot checks prevent late-result bleed.
    const batchId = record.id;
    const target = {tabId: record.context.tabId, documentIds: [record.context.documentId]};
    const [existing] = await chrome.scripting.executeScript({target, func: id => {
      globalThis.PhishLensMailReader.current(id);
      return globalThis.PhishLensMailAnnotations?.status();
    }, args: [record.context.id]});
    if (!existing.result?.active || existing.result.batchId !== batchId) await annotate({type: "ANNOTATE_EMAIL", context: record.context, batchId, evidence,
      urls: data.urls.map(item => ({url: item.url, risk_level: item.risk_level, status: item.status})), quiet: true});
    return {status: "complete", risk: data.final.risk_level, label: data.final.label, evidence: evidence.length, links: data.urls.length};
  }
  async function checkEmail(tab, recheck) {
    const mail = await read(tab), record = await recordFor(mail, tab);
    if (record) {
      let result;
      try { result = await compact(record); }
      catch (error) { if (!recheck) throw error; }
      // Repeated clicks while running always join the existing job.
      if (result && (!recheck || result.status === "running")) return result;
    }
    const {aiSendMode} = await chrome.storage.local.get("aiSendMode");
    const input = {mode: "text", text: mail.text, review: true, mail: {context: mail.context}};
    if (aiSendMode !== "direct") { await PhishLensWorkspace.open(input, tab.windowId); return {status: "review"}; }
    const settings = await PhishLensJobs.request("session", {});
    if (!settings.llm_ready) throw new Error("Mở PhishLens để thiết lập kết nối AI.");
    const preview = await PhishLensJobs.request("preview", {mode: "text", text: mail.text});
    if (typeof preview.text !== "string" || !preview.text.trim()) throw new Error("Chưa chuẩn bị được nội dung gửi AI.");
    const latest = await read(await chrome.tabs.get(tab.id));
    if (latest.context.id !== mail.context.id) throw new Error("Email đã thay đổi. Hãy kiểm tra thư đang mở.");
    if ((await chrome.storage.local.get("aiSendMode")).aiSendMode !== "direct") {
      await PhishLensWorkspace.open(input, tab.windowId); return {status: "review"};
    }
    const job = await PhishLensJobs.start({mode: "text", text: mail.text, use_llm: true, include_ml: false, use_rag: false,
      explain_evidence: Boolean(settings.evidence_explanation_available), consent: true, llm_text: preview.text, save_history: true, save_content: false}, {context: mail.context});
    await remember(job.record, mail, tab);
    return {status: job.status === "error" ? "error" : "running", message: job.error?.message};
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
    if (!["READ_EMAIL", "SET_MAIL_ASSIST", "GET_MAIL_SETTINGS", "MAIL_READY", "OPEN_EMAIL", "MAIL_JOB_STATUS", "MAIL_DETAILS", "ANNOTATE_EMAIL", "CLEAR_EMAIL_ANNOTATIONS", "FOCUS_EMAIL_ANNOTATION"].includes(message?.type)) return;
    // Preserve the trusted click across async mail/context validation.
    const detailsPanel = message.type === "MAIL_DETAILS" && page(sender) ? PhishLensWorkspace.preparePanel(sender.tab.windowId) : null;
    (async () => {
      if (!panel(sender) && !page(sender)) throw new Error("Thao tác chỉ dành cho PhishLens và trang email được hỗ trợ.");
      if (["ANNOTATE_EMAIL", "CLEAR_EMAIL_ANNOTATIONS", "FOCUS_EMAIL_ANNOTATION"].includes(message.type)) {
        if (!panel(sender)) throw new Error("Chỉ bảng PhishLens được đánh dấu kết quả đã kiểm tra.");
        return annotate(message);
      }
      const {mailAssistEnabled} = await chrome.storage.local.get("mailAssistEnabled");
      if (message.type === "GET_MAIL_SETTINGS") return {enabled: Boolean(mailAssistEnabled)};
      if (message.type === "READ_EMAIL" && panel(sender)) return read(await chrome.tabs.get(message.tabId));
      if (message.type === "SET_MAIL_ASSIST" && panel(sender)) {
        if (message.enabled && !await chrome.permissions.contains({origins})) throw new Error("Cấp quyền Gmail/Outlook để dùng trợ lý email.");
        await chrome.storage.local.set({mailAssistEnabled: Boolean(message.enabled)}); return sync();
      }
      if (!page(sender) || !mailAssistEnabled) throw new Error("Bật trợ lý email trong PhishLens trước.");
      if (message.type === "MAIL_JOB_STATUS") {
        const [selected] = await chrome.tabs.query({active: true, windowId: sender.tab.windowId});
        // A hidden mail tab may poll during a tab switch. Resume later instead
        // of replacing a valid running state with an active-tab error.
        if (selected?.id !== sender.tab.id) return {status: "paused"};
      }
      await active(sender.tab);
      if (message.type === "MAIL_READY") { chrome.runtime.sendMessage({type: "EMAIL_CHANGED", tabId: sender.tab.id}).catch(() => {}); return {ready: true}; }
      if (message.type === "OPEN_EMAIL") {
        if (!starts.has(sender.tab.id)) {
          const operation = checkEmail(sender.tab, Boolean(message.recheck));
          starts.set(sender.tab.id, operation);
          operation.finally(() => starts.delete(sender.tab.id)).catch(() => {});
        }
        return starts.get(sender.tab.id);
      }
      if (message.type === "MAIL_JOB_STATUS" || message.type === "MAIL_DETAILS") {
        const mail = await read(sender.tab);
        if (message.contextId !== mail.context.id) throw new Error("Email đã thay đổi.");
        const record = await recordFor(mail, sender.tab);
        if (!record) return {status: "idle"};
        if (message.type === "MAIL_DETAILS") {
          await PhishLensWorkspace.open({job: record}, sender.tab.windowId, true, detailsPanel);
          return {status: "opened"};
        }
        return compact(record);
      }
      throw new Error("Thao tác email không hợp lệ.");
    })().then(respond, error => respond(message.type === "MAIL_JOB_STATUS" && error instanceof InactiveMail ? {status: "paused"} : {error: error.message}));
    return true;
  });
  chrome.permissions.onRemoved.addListener(() => sync().catch(() => {}));
  chrome.runtime.onInstalled.addListener(() => sync().catch(() => {}));
  chrome.runtime.onStartup.addListener(() => sync().catch(() => {}));
  chrome.tabs.onRemoved.addListener(tabId => chrome.storage.session.remove(["mail-jobs-" + tabId, "mail-job-" + tabId]));
  return {origins, sync};
})();
