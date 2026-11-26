"use strict";
// Only short network requests run in the MV3 worker. The server owns AI tasks.
globalThis.PhishLensJobs = (() => {
  let keyPromise;
  async function key() {
    if (!keyPromise) keyPromise = (async () => {
      const saved = await chrome.storage.session.get("jobClientKey");
      if (/^[a-f0-9]{64}$/.test(saved.jobClientKey || "")) return saved.jobClientKey;
      const value = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2, "0")).join("");
      await chrome.storage.session.set({jobClientKey: value}); return value;
    })();
    return keyPromise;
  }
  async function connection() {
    const local = await chrome.storage.local.get(["connection", "autoConnectDisabled"]), memory = await chrome.storage.session.get("connection");
    if (local.autoConnectDisabled) throw new Error("Mở PhishLens và kết nối lại ứng dụng trên máy.");
    const value = local.connection || memory.connection;
    if (!value || value.expires_at * 1000 <= Date.now()) throw new Error("Mở PhishLens để kết nối ứng dụng trên máy.");
    const url = new URL(value.base);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error("Địa chỉ PhishLens chưa hợp lệ.");
    return {...value, base: url.origin};
  }
  async function request(path, body, credentials = null) {
    const access = credentials || await connection(), abort = new AbortController(), timer = setTimeout(() => abort.abort(), 15000);
    try {
      const response = await fetch(access.base + "/api/extension/" + path, {method: "POST", credentials: "omit", cache: "no-store", signal: abort.signal,
        headers: {"Content-Type": "application/json", "X-PhishLens-Extension": chrome.runtime.id, ...(access.token ? {Authorization: "Bearer " + access.token} : {})}, body: JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Yêu cầu chưa hợp lệ.");
      return data;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) throw new Error("Chưa kết nối được PhishLens. Lượt đã gửi vẫn chạy khi ứng dụng còn mở.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function start(payload, metadata = {}) {
    const credentials = await connection(), requestKey = crypto.randomUUID(), clientKey = await key();
    // Pointers only: never store raw mail, approved text or analysis in storage.
    // Persist the idempotency key before sending, so a lost reply is recoverable.
    const record = {id: requestKey, base: credentials.base, context: metadata.context || null, created: Date.now()};
    const entries = {analysisCurrent: record};
    if (record.context) entries["mail-job-" + record.context.tabId] = record;
    await chrome.storage.session.set(entries);
    const job = await request("jobs/start", {client_key: clientKey, request_key: requestKey, payload}, credentials);
    if (record.context) chrome.tabs.sendMessage(record.context.tabId, {type: "MAIL_JOB_CHANGED"}, {documentId: record.context.documentId}).catch(() => {});
    return {...job, record};
  }
  async function status(record) {
    if (!record?.id || Date.now() - record.created > 16 * 60 * 1000) throw new Error("Kết quả đã hết hạn. Hãy kiểm tra lại.");
    const credentials = await connection();
    if (record.base !== credentials.base) throw new Error("Kết quả thuộc kết nối trước. Hãy kết nối lại ứng dụng đó.");
    return request("jobs/status", {client_key: await key(), id: record.id}, credentials);
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["START_ANALYSIS", "ANALYSIS_STATUS"].includes(message?.type)) return;
    if (sender.id !== chrome.runtime.id || sender.url?.split(/[?#]/)[0] !== chrome.runtime.getURL("check.html")) return;
    (message.type === "START_ANALYSIS" ? start(message.payload, {context: message.context}) : status(message.record))
      .then(respond, error => respond({error: error.message}));
    return true;
  });
  return {start, status, request};
})();
