"use strict";
(() => {
  if (globalThis.PhishLensMailReader) return;
  const hosts = new Set(["mail.google.com", "outlook.live.com", "outlook.office.com", "outlook.office365.com"]);
  const supported = location.protocol === "https:" && hosts.has(location.hostname);
  const owned = '[data-phishlens-mail],[data-phishlens-dock],[data-phishlens-region],[data-phishlens-annotations]';
  const excluded = 'script,style,noscript,svg,input,textarea,button,select,[contenteditable]';
  const visible = el => el && !el.closest('[hidden],[aria-hidden="true"],[contenteditable="true"],[role="dialog"]') && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden";
  let snapshot = null;
  function destination(href) {
    try {
      let url = new URL(href, location.href);
      if (url.hostname === "www.google.com" && url.pathname === "/url") url = new URL(url.searchParams.get("q") || url.searchParams.get("url") || href);
      else if (url.hostname.endsWith(".safelinks.protection.outlook.com") && url.searchParams.has("url")) url = new URL(url.searchParams.get("url"));
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function read() {
    if (!supported) throw new Error("Mở một email trên Gmail hoặc Outlook web để dùng chức năng này.");
    const gmail = location.hostname === "mail.google.com", main = document.querySelector('[role="main"]');
    if (!main) throw new Error("Chưa thấy nội dung thư đang mở. Hãy mở một email rồi thử lại.");
    const selectors = gmail ? '.a3s.aiL, .ii.gt .a3s' : '[data-testid="message-body"], [id^="UniqueMessageBody"], [role="document"].allowTextSelection, [aria-label="Message body"], [aria-label="Nội dung thư"]';
    let bodies = [...main.querySelectorAll(selectors)].filter(visible);
    bodies = bodies.filter(el => !bodies.some(other => other !== el && other.contains(el)));
    if (bodies.length !== 1) throw new Error(bodies.length ? "Có nhiều thư đang mở. Thu gọn các thư khác rồi chọn email cần kiểm tra." : "Chưa nhận diện được nội dung thư. Hãy mở rộng email hoặc dùng khoanh vùng.");
    const body = bodies[0], container = gmail ? body.closest('.adn, [data-message-id]') || main : body.closest('[data-app-section="MailReadCompose"], [data-testid="reading-pane"]') || main;
    const subjectNode = main.querySelector(gmail ? 'h2.hP' : '[data-testid="message-subject"], [role="heading"][aria-level="2"], h1');
    const senderNode = container.querySelector(gmail ? '.gD[email]' : '[data-testid="message-sender"], [email]');
    const subject = (subjectNode?.innerText || "").trim(), sender = (senderNode?.getAttribute("email") || senderNode?.innerText || "").trim();
    // Read only this rendered message, never the inbox, drafts or form values.
    const parts = [];
    function walk(el) {
      if (el.nodeType === Node.TEXT_NODE) { parts.push(el.textContent); return; }
      if (el.nodeType !== Node.ELEMENT_NODE || !visible(el) || el.matches(excluded) || el.matches(owned)) return;
      const block = /^(P|DIV|BR|LI|TR|H[1-6]|BLOCKQUOTE|SECTION|ARTICLE)$/.test(el.tagName);
      if (block) parts.push("\n");
      for (const child of el.childNodes) walk(child);
      if (block) parts.push("\n");
    }
    walk(body);
    const content = parts.join("").replace(/[\t \u00a0]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!content) throw new Error("Thư chưa có chữ đọc được. Với email dạng ảnh, hãy dùng khoanh vùng.");
    const links = [], seen = new Set();
    for (const a of body.querySelectorAll('a[href]')) {
      if (!visible(a) || a.closest(excluded + ',' + owned)) continue;
      const url = destination(a.getAttribute("href"));
      if (!url || seen.has(url)) continue;
      seen.add(url); links.push({text: (a.innerText || "Liên kết").trim().slice(0, 140), url});
    }
    const text = [(subject ? "Tiêu đề: " + subject : ""), (sender ? "Người gửi hiển thị: " + sender : ""), "", content,
      ...(links.length ? ["", "Đường dẫn trong thư:", ...links.map(link => link.text + " → " + link.url)] : [])].filter(x => x !== undefined).join("\n").trim();
    if (text.length > 8000) throw new Error("Email vượt 8.000 ký tự. Chọn phần cần kiểm tra hoặc dùng khoanh vùng; thư chưa được gửi đi.");
    // Keep the identity in the isolated content-script world, never in the email DOM.
    // DOM identity and route matter even when two different messages have equal text.
    if (!snapshot || snapshot.body !== body || snapshot.text !== text || snapshot.route !== location.href) {
      snapshot = {id: crypto.randomUUID(), body, text, route: location.href};
    }
    return {text, subject, provider: gmail ? "Gmail" : "Outlook", links: links.length, contextId: snapshot.id};
  }
  function current(id) {
    const mail = read();
    if (mail.contextId !== id) throw new Error("Email đã thay đổi. Đọc và kiểm tra lại thư đang mở.");
    return snapshot.body;
  }
  let observer = null, timer = null, pollTimer = null, host = null, signature = "", stopped = true;
  let mainButton, detailsButton, retryButton, caption, currentState = "idle", checking = false, generation = 0;
  function stop() { stopped = true; observer?.disconnect(); observer = null; clearTimeout(timer); clearTimeout(pollTimer); host?.remove(); host = null; signature = ""; globalThis.PhishLensMailAnnotations?.clear(); }
  function paint(result) {
    if (!host) return;
    currentState = result.status || "idle";
    host.dataset.status = currentState;
    mainButton.disabled = currentState === "running";
    mainButton.textContent = currentState === "running" ? "◌ Đang kiểm tra email…" : currentState === "complete" ? "✓ " + result.label : currentState === "review" ? "Duyệt bản gửi trong PhishLens" : currentState === "error" ? "Chưa kiểm tra được email" : "✦ Kiểm tra email này";
    detailsButton.hidden = currentState !== "complete" && currentState !== "running";
    retryButton.hidden = !["complete", "error"].includes(currentState);
    caption.hidden = !["complete", "error"].includes(currentState);
    caption.textContent = currentState === "complete" ? `${result.evidence} dấu hiệu · ${result.links} liên kết` : result.message || "Bấm kiểm tra lại khi ứng dụng sẵn sàng.";
    host.title = currentState === "error" ? caption.textContent : "PhishLens";
    host.dataset.risk = result.risk || "";
  }
  async function updateJob(id, revision = generation) {
    clearTimeout(pollTimer);
    if (stopped || checking || id !== signature || revision !== generation || document.visibilityState !== "visible") return;
    try {
      const result = await chrome.runtime.sendMessage({type: "MAIL_JOB_STATUS", contextId: id});
      if (id !== signature || stopped || revision !== generation) return;
      if (result?.error) { paint({status: "error", message: result.error}); return; }
      if (result?.status === "paused") { pollTimer = setTimeout(() => updateJob(id), 1200); return; }
      if (result?.status === "idle" && currentState === "review") return;
      paint(result || {status: "idle"});
      if (result?.status === "running") pollTimer = setTimeout(() => updateJob(id), 1200);
    } catch { if (id === signature) paint({status: "error", message: "Tải lại trang để dùng PhishLens."}); }
  }
  async function check(recheck = false) {
    if (checking || stopped) return;
    checking = true; const id = signature, revision = ++generation; paint({status: "running"});
    try {
      const result = await chrome.runtime.sendMessage({type: "OPEN_EMAIL", recheck});
      if (id !== signature || stopped || revision !== generation) return;
      paint(result?.error ? {status: "error", message: result.error} : result);
      if (result?.status === "running" || result?.status === "review") pollTimer = setTimeout(() => updateJob(id), 1000);
    } catch { if (id === signature) paint({status: "error", message: "Tải lại trang để dùng PhishLens."}); }
    finally { if (revision === generation) checking = false; }
  }
  async function scan() {
    if (stopped || document.visibilityState !== "visible") return;
    let mail; try { mail = read(); } catch { host?.remove(); host = null; signature = ""; return; }
    if (mail.contextId === signature) return;
    clearTimeout(pollTimer); signature = mail.contextId; checking = false; generation++;
    if (!host) {
      host = document.createElement("div"); host.setAttribute("data-phishlens-mail", "");
      Object.assign(host.style, {position: "fixed", right: "20px", bottom: "20px", zIndex: "2147483644"});
      const root = host.attachShadow({mode: "closed"}), sheet = new CSSStyleSheet();
      sheet.replaceSync(`:host{font:13px/1.45 system-ui;color:#263047;color-scheme:light dark}*{box-sizing:border-box}[hidden]{display:none!important}
        .bar{max-width:min(430px,calc(100vw - 40px));border:1px solid #d6d2ee;border-radius:14px;padding:6px;background:#fff;box-shadow:0 6px 25px #1d22482b}
        .actions{display:flex;align-items:center;gap:3px}button{font:600 12px/1.45 system-ui;border:0;border-radius:9px;padding:10px 12px;cursor:pointer;background:transparent;color:#5946b7}button:hover{background:#f1eefc}button:focus-visible{outline:3px solid #a498f0;outline-offset:1px}button:disabled{cursor:progress;opacity:.8}
        .main{text-align:left;font-size:13px;flex:1}small{display:block;padding:0 12px 7px;color:#6c7890;max-width:320px;overflow-wrap:anywhere}:host([data-risk="HIGH"]) .main{color:#aa352c}:host([data-risk="LOW"]) .main{color:#247760}
        @media(prefers-color-scheme:dark){:host{color:#e1e7f1}.bar{background:#202735;border-color:#3c455e}button{color:#c9bfff}button:hover{background:#32384e}small{color:#a5b3c9}:host([data-risk="HIGH"]) .main{color:#ffa393}:host([data-risk="LOW"]) .main{color:#8bdbbd}}`);
      root.adoptedStyleSheets = [sheet];
      const bar = document.createElement("div"), actions = document.createElement("div"); bar.className = "bar"; actions.className = "actions";
      mainButton = document.createElement("button"); mainButton.type = "button"; mainButton.className = "main";
      detailsButton = document.createElement("button"); detailsButton.type = "button"; detailsButton.textContent = "Chi tiết";
      retryButton = document.createElement("button"); retryButton.type = "button"; retryButton.textContent = "↻"; retryButton.title = "Kiểm tra lại email"; retryButton.setAttribute("aria-label", "Kiểm tra lại email");
      caption = document.createElement("small"); caption.setAttribute("role", "status"); caption.setAttribute("aria-live", "polite");
      mainButton.addEventListener("click", event => { if (!event.isTrusted) return; if (currentState === "complete") globalThis.PhishLensMailAnnotations?.focus({}); else if (currentState === "error") updateJob(signature); else check(); });
      retryButton.addEventListener("click", event => { if (event.isTrusted) check(true); });
      detailsButton.addEventListener("click", event => { if (event.isTrusted) chrome.runtime.sendMessage({type: "MAIL_DETAILS", contextId: signature}).then(result => { if (result?.error) paint({status: "error", message: result.error}); }).catch(() => {}); });
      actions.append(mainButton, detailsButton, retryButton); bar.append(actions, caption); root.append(bar); document.documentElement.append(host);
    }
    paint({status: "idle"}); updateJob(signature);
    chrome.runtime.sendMessage({type: "MAIL_READY"}).catch(() => {});
  }
  function start() {
    if (observer || !supported) return;
    stopped = false;
    observer = new MutationObserver(records => {
      if (records.every(record => record.target.closest?.(owned) || [...record.addedNodes, ...record.removedNodes].every(node => node.nodeType === 1 && node.matches?.(owned)) && record.type === 'childList')) return;
      clearTimeout(timer); timer = setTimeout(scan, 350);
    });
    observer.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden", "aria-expanded", "aria-hidden"]});
    scan();
  }
  globalThis.PhishLensMailReader = {read, current, destination, visible, excluded, owned, start, stop};
  if (supported && globalThis.chrome?.runtime) {
    chrome.runtime.onMessage.addListener((message, sender) => {
      if (sender.id !== chrome.runtime.id) return;
      if (message.type === "STOP_MAIL_HELPER") stop();
    });
    chrome.runtime.sendMessage({type: "GET_MAIL_SETTINGS"}).then(config => { if (config?.enabled) start(); }).catch(() => {});
    document.addEventListener("visibilitychange", () => { if (!stopped) { scan(); if (signature) updateJob(signature); } });
    chrome.runtime.onMessage.addListener((message, sender) => { if (sender.id === chrome.runtime.id && message.type === "MAIL_JOB_CHANGED" && signature) updateJob(signature); });
  }
})();
