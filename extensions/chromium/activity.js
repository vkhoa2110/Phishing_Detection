"use strict";
// The session index contains pointers and bounded status enums, never inputs,
// mail subjects, page URLs, provider messages, quotes or complete results.
globalThis.PhishLensActivity = (() => {
  const storageKey = "analysisActivity", limit = 40;
  const terminal = new Set(["complete", "error", "expired"]), levels = new Set(["LOW", "WARNING", "HIGH", "UNKNOWN"]);
  const kinds = new Set(["url", "text", "image", "mail", "conversation"]);
  let writing = Promise.resolve();
  const digest = async value => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), n => n.toString(16).padStart(2, "0")).join("");
  const owner = access => digest(access.base + "|" + (access.token || "guest"));
  const expired = item => Date.now() - item.created > 60 * 60000;
  function change(action) {
    const operation = writing.catch(() => {}).then(async () => {
      const saved = await chrome.storage.session.get(storageKey), before = JSON.stringify(saved[storageKey] || []), rows = (saved[storageKey] || []).filter(item => !expired(item));
      const result = await action(rows);
      // Evict oldest finished entries first, retaining running work if possible.
      while (rows.length > limit) { const index = rows.findIndex(item => terminal.has(item.status)); rows.splice(index < 0 ? 0 : index, 1); }
      if (JSON.stringify(rows) !== before) await chrome.storage.session.set({[storageKey]: rows});
      return result;
    });
    writing = operation; return operation;
  }
  async function remember(record, access, metadata = {}) {
    const account = await owner(access), kind = record.conversation ? "conversation" : record.context ? "mail" : kinds.has(metadata.kind) ? metadata.kind : "text";
    const tabId = record.context?.tabId ?? record.conversation?.tabId ?? metadata.sourceTab;
    let source = null, platform = "";
    if (Number.isInteger(tabId)) {
      try {
        const tab = await chrome.tabs.get(tabId);
        if (!tab.incognito && /^https?:\/\//.test(tab.url || "")) {
          source = {tabId, digest: await digest(tab.url)};
          const host = new URL(tab.url).hostname;
          platform = host === "mail.google.com" ? "Gmail" : ["outlook.live.com", "outlook.office.com", "outlook.office365.com"].includes(host) ? "Outlook" : PhishLensChatPlatforms.detect(tab.url)?.label || "";
        }
      } catch { /* Source closed; the result remains readable. */ }
    }
    return change(rows => {
      if (!rows.some(item => item.owner === account && item.id === record.id)) rows.push({id: record.id, owner: account, created: record.created, kind, platform, source, record, status: "running"});
    });
  }
  function compact(job) {
    const state = {status: ["running", "complete", "error"].includes(job.status) ? job.status : "running", queued: Boolean(job.queued), cancelled: job.error?.status === 499};
    if (job.progress) state.progress = {completed: Math.max(0, Math.min(64, Number(job.progress.completed) || 0)), total: Math.max(0, Math.min(64, Number(job.progress.total) || 0)), stopping: Boolean(job.progress.cancel_requested)};
    if (job.status === "complete") {
      const data = job.result;
      state.risk = levels.has(data?.final?.risk_level) ? data.final.risk_level : "UNKNOWN";
      state.urlRisk = levels.has(data?.assessments?.url?.risk_level) ? data.assessments.url.risk_level : "UNKNOWN";
      state.urls = Math.min(3200, data?.urls?.length || 0);
      state.partial = Boolean(data?.conversation_batch && !data.conversation_batch.complete);
      state.technicalError = data?.llm?.status === "error";
    }
    return state;
  }
  async function observe(record, job, access) {
    const account = await owner(access), state = compact(job);
    await change(rows => { const item = rows.find(row => row.owner === account && row.id === record.id); if (item) Object.assign(item, state); });
  }
  async function scope() { const access = await PhishLensJobs.access(); return {access, account: await owner(access)}; }
  async function rowsFor(account) {
    await writing.catch(() => {});
    const saved = await chrome.storage.session.get(storageKey);
    return (saved[storageKey] || []).filter(item => item.owner === account && !expired(item));
  }
  const publicRow = ({owner: account, record, source, ...row}) => ({...row, hasSource: Boolean(source)});
  async function list() {
    const {account} = await scope();
    return {items: (await rowsFor(account)).sort((a, b) => b.created - a.created).map(publicRow)};
  }
  async function find(id) {
    const {access, account} = await scope(), item = (await rowsFor(account)).find(row => row.id === id);
    if (!item) throw new Error("Lượt kiểm tra không còn trong phiên này.");
    return {access, account, item};
  }
  async function status(id) {
    const {access, account, item} = await find(id);
    try {
      const job = await PhishLensJobs.status(item.record);
      return {item: {...publicRow(item), ...compact(job)}};
    } catch (error) {
      // A transport failure does not mean the job failed or finished safely.
      if (error.httpStatus === 404) {
        await change(rows => { const row = rows.find(value => value.owner === account && value.id === id); if (row) row.status = "expired"; });
        return {item: {...publicRow(item), status: "expired"}};
      }
      return {item: {...publicRow(item), unavailable: true}, message: error.message};
    }
  }
  async function open(id) { const {item} = await find(id); if (["error", "expired"].includes(item.status)) throw new Error("Lượt này không còn kết quả để mở."); return {record: item.record}; }
  async function focus(id) {
    const {item} = await find(id);
    if (!item.source) throw new Error("Lượt này không gắn với tab nguồn.");
    let tab;
    try { tab = await chrome.tabs.get(item.source.tabId); } catch { throw new Error("Tab nguồn đã đóng. Bạn vẫn có thể mở kết quả còn hạn."); }
    if (tab.incognito || !/^https?:\/\//.test(tab.url || "") || await digest(tab.url) !== item.source.digest) throw new Error("Tab nguồn đã chuyển sang nội dung khác. Kết quả đã lưu vẫn giữ nguyên.");
    await chrome.tabs.update(tab.id, {active: true}); await chrome.windows.update(tab.windowId, {focused: true});
    return {focused: true};
  }
  async function remove(id, all = false) {
    const {account} = await scope();
    await change(rows => {
      for (let index = rows.length - 1; index >= 0; index--) {
        const row = rows[index];
        if (row.owner === account && terminal.has(row.status) && (all || row.id === id)) rows.splice(index, 1);
      }
    });
    return {ok: true};
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["ACTIVITY_LIST", "ACTIVITY_STATUS", "ACTIVITY_OPEN", "ACTIVITY_SOURCE", "ACTIVITY_REMOVE", "ACTIVITY_CLEAR"].includes(message?.type)) return;
    if (sender.id !== chrome.runtime.id || sender.url?.split(/[?#]/)[0] !== chrome.runtime.getURL("check.html")) return;
    (message.type === "ACTIVITY_LIST" ? list() : message.type === "ACTIVITY_STATUS" ? status(message.id) : message.type === "ACTIVITY_OPEN" ? open(message.id) : message.type === "ACTIVITY_SOURCE" ? focus(message.id) : remove(message.id, message.type === "ACTIVITY_CLEAR"))
      .then(respond, error => respond({error: error.message}));
    return true;
  });
  return {remember, observe};
})();
