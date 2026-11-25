"use strict";
(() => {
  if (globalThis.PhishLensMailReader) return;
  const hosts = new Set(["mail.google.com", "outlook.live.com", "outlook.office.com", "outlook.office365.com"]);
  const supported = location.protocol === "https:" && hosts.has(location.hostname);
  const visible = el => el && !el.closest('[hidden],[aria-hidden="true"],[contenteditable="true"],[role="dialog"]') && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden";
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
      if (el.nodeType !== Node.ELEMENT_NODE || !visible(el) || el.matches('script,style,noscript,svg,input,textarea,button,select,[contenteditable]')) return;
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
      if (!visible(a)) continue;
      const url = destination(a.getAttribute("href"));
      if (!url || seen.has(url)) continue;
      seen.add(url); links.push({text: (a.innerText || "Liên kết").trim().slice(0, 140), url});
    }
    const text = [(subject ? "Tiêu đề: " + subject : ""), (sender ? "Người gửi hiển thị: " + sender : ""), "", content,
      ...(links.length ? ["", "Đường dẫn trong thư:", ...links.map(link => link.text + " → " + link.url)] : [])].filter(x => x !== undefined).join("\n").trim();
    if (text.length > 8000) throw new Error("Email vượt 8.000 ký tự. Chọn phần cần kiểm tra hoặc dùng khoanh vùng; thư chưa được gửi đi.");
    return {text, subject, provider: gmail ? "Gmail" : "Outlook", links: links.length};
  }
  let observer = null, timer = null, host = null, signature = "", stopped = true;
  function stop() { stopped = true; observer?.disconnect(); observer = null; clearTimeout(timer); host?.remove(); host = null; signature = ""; }
  async function scan() {
    if (stopped || document.visibilityState !== "visible") return;
    let mail; try { mail = read(); } catch { host?.remove(); host = null; signature = ""; return; }
    if (mail.text === signature) return;
    signature = mail.text;
    if (!host) {
      host = document.createElement("div"); host.setAttribute("data-phishlens-mail", "");
      Object.assign(host.style, {position: "fixed", right: "20px", bottom: "90px", zIndex: "2147483644"});
      const root = host.attachShadow({mode: "closed"}), button = document.createElement("button");
      button.type = "button"; button.textContent = "✦ Kiểm tra email này";
      Object.assign(button.style, {border: "1px solid #a79eff", borderRadius: "12px", background: "#5144bd", color: "white", padding: "12px 17px", boxShadow: "0 5px 22px #1d224833", cursor: "pointer", font: "600 13px system-ui"});
      button.addEventListener("click", event => { if (event.isTrusted) chrome.runtime.sendMessage({type: "OPEN_EMAIL"}).then(result => { if (result?.error) button.textContent = result.error; }).catch(() => { button.textContent = "Tải lại trang để dùng PhishLens"; }); });
      root.append(button); document.documentElement.append(host);
    }
    chrome.runtime.sendMessage({type: "MAIL_READY"}).catch(() => {});
  }
  function start() {
    if (observer || !supported) return;
    stopped = false;
    observer = new MutationObserver(records => {
      if (records.every(record => record.target.closest?.('[data-phishlens-mail],[data-phishlens-dock],[data-phishlens-region]') || [...record.addedNodes, ...record.removedNodes].every(node => node.nodeType === 1 && node.matches?.('[data-phishlens-mail],[data-phishlens-dock],[data-phishlens-region]')) && record.type === 'childList')) return;
      clearTimeout(timer); timer = setTimeout(scan, 350);
    });
    observer.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["hidden", "aria-expanded", "aria-hidden"]});
    scan();
  }
  globalThis.PhishLensMailReader = {read, start, stop};
  if (supported && globalThis.chrome?.runtime) {
    chrome.runtime.onMessage.addListener((message, sender) => {
      if (sender.id !== chrome.runtime.id) return;
      if (message.type === "STOP_MAIL_HELPER") stop();
    });
    chrome.runtime.sendMessage({type: "GET_MAIL_SETTINGS"}).then(config => { if (config?.enabled) start(); }).catch(() => {});
    document.addEventListener("visibilitychange", () => { if (!stopped) scan(); });
  }
})();
