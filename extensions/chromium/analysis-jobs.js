"use strict";
// Only short network requests run in the MV3 worker. The server owns AI tasks.
globalThis.PhishLensJobs = (() => {
  let keyPromise, connecting;
  async function key() {
    if (!keyPromise) keyPromise = (async () => {
      const saved = await chrome.storage.session.get("jobClientKey");
      if (/^[a-f0-9]{64}$/.test(saved.jobClientKey || "")) return saved.jobClientKey;
      const value = Array.from(crypto.getRandomValues(new Uint8Array(32)), n => n.toString(16).padStart(2, "0")).join("");
      await chrome.storage.session.set({jobClientKey: value}); return value;
    })();
    return keyPromise;
  }
  function baseURL(value) {
    const url = new URL(value);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== "/") throw new Error("Địa chỉ PhishLens chưa hợp lệ.");
    return url.origin;
  }
  function savedConnection(local, memory) {
    for (const value of [local.connection, memory.connection]) {
      if (!value || !Number.isFinite(value.expires_at) || value.expires_at * 1000 <= Date.now()) continue;
      try { return {...value, base: baseURL(value.base)}; } catch { /* Never contact an address outside loopback. */ }
    }
    return null;
  }
  const paused = () => new Error("Kết nối đang tạm ngừng. Mở PhishLens để bật lại.");
  async function discover(local, memory) {
    const candidates = [local.base, local.connection?.base, memory.connection?.base, "http://127.0.0.1:8001", "http://127.0.0.1:8000"], bases = new Set();
    for (const value of candidates) {
      if (!value) continue;
      try { bases.add(baseURL(value)); } catch { /* Ignore invalid saved addresses. */ }
    }
    for (const base of bases) {
      const access = {base, guest: true, expires_at: Date.now() / 1000 + 30 * 86400};
      try {
        // This request contains no email, image or conversation. A fresh worker
        // must also connect without requiring the user to open check.html first.
        const data = await request("session", {}, access);
        if (data.guest !== true || typeof data.user?.display_name !== "string" || typeof data.ml_ready !== "boolean" || typeof data.llm_ready !== "boolean" || data.analysis_jobs !== true) continue;
      } catch { continue; }
      const [current, session] = await Promise.all([chrome.storage.local.get(["connection", "autoConnectDisabled"]), chrome.storage.session.get("connection")]);
      if (current.autoConnectDisabled) throw paused();
      // An explicit connection made while discovery was pending takes priority.
      const saved = savedConnection(current, session);
      if (saved) return saved;
      await chrome.storage.local.set({base, connection: access});
      return access;
    }
    throw new Error("Không kết nối được ứng dụng trên máy. Khởi động PhishLens rồi bấm Thử lại.");
  }
  async function connection() {
    const [local, memory] = await Promise.all([chrome.storage.local.get(["base", "connection", "autoConnectDisabled"]), chrome.storage.session.get("connection")]);
    if (local.autoConnectDisabled) throw paused();
    const saved = savedConnection(local, memory);
    if (saved) return saved;
    // Never silently downgrade a paired account to guest or change job owners.
    if (local.connection?.token || memory.connection?.token) throw new Error("Kết nối tài khoản đã hết hạn. Mở PhishLens để kết nối lại hoặc dùng chế độ khách.");
    if (!connecting) connecting = discover(local, memory).finally(() => { connecting = null; });
    const access = await connecting;
    if ((await chrome.storage.local.get("autoConnectDisabled")).autoConnectDisabled) throw paused();
    return access;
  }
  async function request(path, body, credentials = null) {
    const access = credentials || await connection(), abort = new AbortController(), timer = setTimeout(() => abort.abort(), path === "session" ? 20000 : 15000);
    try {
      const response = await fetch(access.base + "/api/extension/" + path, {method: "POST", credentials: "omit", cache: "no-store", signal: abort.signal,
        headers: {"Content-Type": "application/json", "X-PhishLens-Extension": chrome.runtime.id, ...(access.token ? {Authorization: "Bearer " + access.token} : {})}, body: JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) { const error = new Error(typeof data.detail === "string" ? data.detail : "Yêu cầu chưa hợp lệ."); error.httpStatus = response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name === "AbortError" || error instanceof TypeError) throw new Error("Chưa kết nối được PhishLens. Lượt đã gửi vẫn chạy khi ứng dụng còn mở.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function start(payload, metadata = {}) {
    const credentials = await connection(), requestKey = crypto.randomUUID(), clientKey = await key();
    if (metadata.conversation) await PhishLensConversation.validate(metadata.conversation);
    // Pointers only: never store raw mail, approved text or analysis in storage.
    // Persist the idempotency key before sending, so a lost reply is recoverable.
    const record = {id: requestKey, base: credentials.base, context: metadata.context || null, created: Date.now()};
    if (metadata.conversation) record.conversation = metadata.conversation;
    if (metadata.conversation?.history) record.batch = true;
    const entries = {analysisCurrent: record};
    if (record.context) entries["mail-job-" + record.context.tabId] = record;
    await chrome.storage.session.set(entries);
    await PhishLensActivity.remember(record, credentials, metadata);
    const body = record.batch ? {text: payload.text, llm_text: payload.llm_text || payload.text, use_llm: payload.use_llm, consent: payload.consent,
      include_ml: payload.include_ml, explain_evidence: Boolean(payload.explain_evidence), scope: metadata.conversation.scope} : payload;
    const job = await request(record.batch ? "conversation/start" : "jobs/start", {client_key: clientKey, request_key: requestKey, payload: body}, credentials);
    await PhishLensActivity.observe(record, job, credentials);
    if (record.context) chrome.tabs.sendMessage(record.context.tabId, {type: "MAIL_JOB_CHANGED"}, {documentId: record.context.documentId}).catch(() => {});
    return {...job, record};
  }
  async function status(record) {
    if (!record?.id || Date.now() - record.created > 60 * 60 * 1000) throw new Error("Kết quả đã hết hạn. Hãy kiểm tra lại.");
    const credentials = await connection();
    if (record.base !== credentials.base) throw new Error("Kết quả thuộc kết nối trước. Hãy kết nối lại ứng dụng đó.");
    const job = await request("jobs/status", {client_key: await key(), id: record.id}, credentials);
    await PhishLensActivity.observe(record, job, credentials);
    return job;
  }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["START_ANALYSIS", "ANALYSIS_STATUS", "CANCEL_CONVERSATION_JOB", "CANCEL_QUEUED_JOB"].includes(message?.type)) return;
    if (sender.id !== chrome.runtime.id || sender.url?.split(/[?#]/)[0] !== chrome.runtime.getURL("check.html")) return;
    (message.type === "START_ANALYSIS" ? start(message.payload, {context: message.context, conversation: message.conversation, kind: message.kind, sourceTab: message.sourceTab}) : message.type === "CANCEL_CONVERSATION_JOB" ?
      (async () => { if (!message.record?.batch) throw new Error("Lượt này không hỗ trợ dừng theo phần."); const access = await connection(); if (access.base !== message.record.base) throw new Error("Kết nối đã thay đổi."); return request("conversation/cancel", {client_key: await key(), id: message.record.id}, access); })() : message.type === "CANCEL_QUEUED_JOB" ?
      (async () => { const access = await connection(); if (access.base !== message.record?.base) throw new Error("Kết nối đã thay đổi."); const job = await request("jobs/cancel", {client_key: await key(), id: message.record.id}, access); await PhishLensActivity.observe(message.record, job, access); return job; })() : status(message.record))
      .then(respond, error => respond({error: error.message}));
    return true;
  });
  return {start, status, request, access: connection};
})();
