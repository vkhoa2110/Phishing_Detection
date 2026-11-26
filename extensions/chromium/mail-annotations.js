"use strict";
(() => {
  if (globalThis.PhishLensMailAnnotations) return;
  const reader = globalThis.PhishLensMailReader;
  if (!reader) return;
  const names = ["phishlens-mail-evidence", "phishlens-mail-links", "phishlens-mail-high", "phishlens-mail-focus"];
  const labels = {HIGH: "Nguy cơ cao", WARNING: "Cần kiểm tra thêm", LOW: "Chưa thấy dấu hiệu rõ", UNKNOWN: "Chưa đủ thông tin"};
  const normal = text => text.replace(/\s+/gu, " ").trim();
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  let session = null, host = null, root = null, observer = null, expiry = null, style = null;
  let dock, card, content, close;

  // Build a reversible whitespace-only map. Do not rewrite, wrap, or replace
  // any email nodes; Gmail/Outlook retain their original DOM and event handlers.
  function textMap(body) {
    const points = [], chars = [];
    function append(value, node = null) {
      for (let offset = 0; offset < value.length; offset++) {
        const char = /\s/u.test(value[offset]) ? " " : value[offset];
        if (char === " " && (!chars.length || chars[chars.length - 1] === " ")) continue;
        chars.push(char); points.push(node ? {node, offset} : null);
      }
    }
    function walk(node) {
      if (node.nodeType === Node.TEXT_NODE) { append(node.textContent, node); return; }
      if (node.nodeType !== Node.ELEMENT_NODE || !reader.visible(node) || node.matches(reader.excluded + ',' + reader.owned)) { append(" "); return; }
      const block = /^(P|DIV|BR|LI|TR|H[1-6]|BLOCKQUOTE|SECTION|ARTICLE)$/.test(node.tagName);
      if (block) append(" ");
      for (const child of node.childNodes) walk(child);
      if (block) append(" ");
    }
    walk(body);
    return {text: chars.join(""), points};
  }
  function rangesFor(map, quote) {
    const value = normal(quote), ranges = [];
    if (!value) return ranges;
    let offset = 0;
    while (ranges.length < 5) {
      const index = map.text.indexOf(value, offset);
      if (index < 0) break;
      const start = map.points[index], end = map.points[index + value.length - 1];
      if (start && end) {
        const range = document.createRange();
        range.setStart(start.node, start.offset); range.setEnd(end.node, end.offset + 1);
        // Spaces may collapse, but no other spelling or meaning is inferred.
        if (normal(range.toString()) === value) ranges.push(range);
      }
      offset = index + value.length;
    }
    return ranges;
  }
  function urlKey(value) {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function status() { return {active: Boolean(session), evidence: session?.evidence.length || 0, links: session?.links.length || 0, batchId: session?.batchId}; }
  function valid() {
    if (!session) return false;
    try { return reader.current(session.id) === session.body; }
    catch { clear(); return false; }
  }
  function clear(id, batchId) {
    if (id && session?.id !== id || batchId && session?.batchId !== batchId) return status();
    observer?.disconnect(); observer = null; clearTimeout(expiry);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("hashchange", checkCurrent);
    window.removeEventListener("popstate", checkCurrent);
    window.removeEventListener("pagehide", pageHide);
    document.removeEventListener("visibilitychange", checkCurrent);
    for (const name of names) globalThis.CSS?.highlights?.delete(name);
    if (style) document.adoptedStyleSheets = document.adoptedStyleSheets.filter(sheet => sheet !== style);
    host?.remove(); session = host = root = style = null;
    return status();
  }
  function checkCurrent() { valid(); }
  function pageHide() { clear(); }
  function paint() {
    if (!globalThis.CSS?.highlights || !globalThis.Highlight) return;
    style = new CSSStyleSheet();
    style.replaceSync(`::highlight(${names[0]}){background-color:#ffe8a3;color:#3e2a0a}
      ::highlight(${names[1]}){background-color:#e0e7ff;color:#283a86;text-decoration:underline}
      ::highlight(${names[2]}){background-color:#ffd9d4;color:#8e251b;text-decoration:underline}
      ::highlight(${names[3]}){background-color:#ffd078;color:#302006}`);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, style];
    const evidence = new Highlight(...session.evidence.flatMap(item => item.ranges)); evidence.priority = 2;
    CSS.highlights.set(names[0], evidence);
    for (const [name, high] of [[names[1], false], [names[2], true]]) {
      const highlight = new Highlight(...session.links.filter(item => (item.risk === "HIGH") === high).map(item => item.range));
      highlight.priority = 1; CSS.highlights.set(name, highlight);
    }
  }
  function button(label, action, className = "") {
    const node = el("button", label, className); node.type = "button";
    node.addEventListener("click", action); return node;
  }
  function mount() {
    host = el("div"); host.dataset.phishlensAnnotations = "";
    host.style.cssText = "position:fixed!important;right:18px!important;bottom:18px!important;z-index:2147483645!important;color-scheme:light dark!important;";
    root = host.attachShadow({mode: "closed"});
    const css = new CSSStyleSheet(); css.replaceSync(`
      :host{all:initial;font:14px/1.55 system-ui,-apple-system,sans-serif;color:#263047}
      *{box-sizing:border-box} [hidden]{display:none!important} button{font:inherit;cursor:pointer}
      button:focus-visible,summary:focus-visible{outline:3px solid #8675ed;outline-offset:3px}
      .dock{display:flex;gap:10px;align-items:center;margin-left:auto;padding:11px 16px;border:1px solid #d7d2f3;border-radius:14px;background:#fff;color:#44328c;box-shadow:0 5px 22px #18234126;font-weight:650}
      .brand-mark{display:grid;place-items:center;width:27px;height:29px;border-radius:9px;background:#5a46bf;color:white;font-size:18px}
      .card{width:min(388px,calc(100vw - 36px));max-height:min(570px,calc(100dvh - 100px));display:flex;flex-direction:column;margin-bottom:10px;background:#fff;border:1px solid #dce1ec;border-radius:18px;box-shadow:0 14px 50px #1823412e;overflow:hidden}
      header{display:flex;align-items:center;gap:10px;padding:16px 18px;border-bottom:1px solid #e8ebf2} header strong{font-size:16px;flex:1}
      .close{border:0;background:transparent;color:#68748a;font-size:22px;width:30px;height:30px;border-radius:8px}
      .content{padding:17px 18px;overflow:auto;overscroll-behavior:contain;outline:none} h3{font-size:15px;margin:0 0 12px} p{margin:8px 0} blockquote{margin:0;padding:12px 14px;background:#fff5d7;border-left:3px solid #e6ad37;border-radius:0 10px 10px 0;color:#48371b;white-space:pre-wrap}
      .kicker{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#728099;margin:0 0 8px}.reason{margin:13px 0 17px}.list{display:grid;gap:8px;margin:8px 0 20px}
      .item{display:block;width:100%;padding:11px 12px;text-align:left;overflow-wrap:anywhere;border:1px solid #e0e5ef;border-radius:11px;background:#f8f9fd;color:inherit;font-size:13px}.item:hover{border-color:#a99be3;background:#f1eefc}.item small{display:block;color:#69778f;font-size:12px;margin-top:4px}
      .back{border:0;background:none;color:#5945b5;padding:0;margin:0 0 14px;font-size:13px}.domain{font-size:20px;font-weight:700;overflow-wrap:anywhere;color:#43318f;margin:5px 0 14px}.display{overflow-wrap:anywhere;margin-bottom:16px}.comparison{padding:11px 13px;border:1px solid #eed0a1;border-radius:10px;background:#fff7e9;color:#765014}.risk{display:inline-block;padding:4px 9px;border-radius:7px;font-size:12px;background:#eef0f6;color:#536079}.risk.HIGH{background:#ffe6e1;color:#962e24}.risk.WARNING{background:#fff0d2;color:#885a13}
      .muted{color:#748096;font-size:12px} details{margin:15px 0} summary{cursor:pointer;color:#5e6b80;font-size:12px} code{display:block;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace;margin-top:8px}.copy{padding:9px 13px;border:1px solid #d8d0f5;border-radius:9px;background:#f4f1ff;color:#513eab;font-size:12px}.footer{padding:11px 18px;border-top:1px solid #e8ebf2;display:flex;justify-content:space-between;align-items:center;gap:12px}.remove{padding:0;border:0;background:none;color:#68748a;font-size:12px}
      @media(prefers-color-scheme:dark){:host{color:#e0e6f1}.card,.dock{background:#202634;border-color:#3a4358}.dock{color:#cec3ff}header,.footer{border-color:#384156}.close,.muted,.item small,summary,.remove{color:#a7b2c7}.item{background:#282f40;border-color:#3c465d}.item:hover{background:#35304d}.domain,.back{color:#c6b4ff}.comparison{background:#3e3425;border-color:#655336;color:#f0d7aa}.copy{background:#35304d;border-color:#615181;color:#dfd4ff}blockquote{background:#403722;color:#ffe7b5}}
    `); root.adoptedStyleSheets = [css];
    card = el("section", undefined, "card"); card.hidden = true; card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "Dấu hiệu trong email · PhishLens");
    const header = el("header"); header.append(el("span", "✓", "brand-mark"), el("strong", "PhishLens"));
    close = button("×", hide, "close"); close.setAttribute("aria-label", "Thu gọn giải thích"); header.append(close);
    content = el("div", undefined, "content"); content.tabIndex = -1;
    const footer = el("div", undefined, "footer"); footer.append(el("span", "Bấm phần được tô để xem", "muted"), button("Ẩn đánh dấu", () => clear(), "remove"));
    card.append(header, content, footer);
    dock = button("", () => { if (card.hidden) overview(); else hide(); }, "dock");
    dock.setAttribute("aria-expanded", "false"); dock.append(el("span", "✓", "brand-mark"), el("span", `PhishLens · ${session.evidence.length} dấu hiệu · ${session.links.length} liên kết`));
    dock.hidden = session.quiet;
    root.append(card, dock); document.documentElement.append(host);
  }
  function show() { card.hidden = false; dock.setAttribute("aria-expanded", "true"); content.focus({preventScroll: true}); }
  function hide() { card.hidden = true; dock.setAttribute("aria-expanded", "false"); CSS.highlights?.delete(names[3]); dock.focus({preventScroll: true}); }
  function overview() {
    if (!valid()) return;
    content.replaceChildren(el("h3", "Dấu hiệu trong email"));
    const list = el("div", undefined, "list");
    session.evidence.forEach((item, index) => {
      const row = button(`${index + 1}. ${item.quote}`, () => focus({kind: "evidence", index}), "item"); row.dataset.evidenceIndex = index; list.append(row);
    });
    if (!list.childNodes.length) list.append(el("p", "Chưa có trích dẫn khớp nội dung thư.", "muted"));
    content.append(list, el("h3", "Liên kết trong thư"));
    const links = el("div", undefined, "list");
    session.links.forEach((item, index) => {
      const row = button(item.text, () => focus({kind: "link", index}), "item"); row.dataset.linkIndex = index;
      row.append(el("small", "→ " + item.domain)); links.append(row);
    });
    if (!links.childNodes.length) links.append(el("p", "Không có liên kết HTTP/HTTPS trong thư.", "muted"));
    content.append(links); show();
  }
  function focus({kind = "overview", index = 0, batchId} = {}) {
    if (!valid()) throw new Error("Email đã thay đổi. Đọc và kiểm tra lại thư đang mở.");
    if (batchId && session.batchId !== batchId) throw new Error("Đánh dấu lại email để xem dấu hiệu.");
    if (kind === "overview") { overview(); return status(); }
    const item = (kind === "link" ? session.links : session.evidence)[index];
    if (!item) { overview(); return status(); }
    const range = kind === "link" ? item.range : item.ranges[0];
    const target = range.startContainer.parentElement;
    target?.scrollIntoView({block: "center", behavior: "instant"});
    if (globalThis.Highlight && CSS.highlights) { const highlight = new Highlight(range); highlight.priority = 3; CSS.highlights.set(names[3], highlight); }
    content.replaceChildren(button("← Tất cả dấu hiệu", overview, "back"));
    if (kind === "evidence") {
      content.append(el("p", "Dấu hiệu " + (index + 1), "kicker"), el("blockquote", item.quote), el("p", item.reason, "reason"));
    } else {
      content.append(el("p", "Chữ hiển thị", "kicker"), el("p", item.text, "display"), el("p", "Tên miền đích", "kicker"), el("div", item.domain, "domain"));
      if (item.displayDomain && item.displayDomain !== item.domain) content.append(el("p", `Liên kết ghi ${item.displayDomain}, nhưng dẫn tới ${item.domain}.`, "comparison"));
      content.append(el("p", item.risk ? labels[item.risk] : "Chưa chấm được URL này", "risk " + (item.risk || "")));
      const details = el("details"); details.append(el("summary", "Xem đầy đủ đường dẫn"), el("code", item.url)); content.append(details);
      const copy = button("Sao chép đường dẫn", async () => {
        if (!valid()) return;
        try { await navigator.clipboard.writeText(item.url); copy.textContent = "Đã sao chép"; }
        catch { copy.textContent = "Chưa sao chép được"; details.open = true; }
      }, "copy"); content.append(copy);
    }
    show(); return status();
  }
  function onClick(event) {
    if (!event.isTrusted || event.composedPath().includes(host) || !valid() || !session.body.contains(event.target) || !getSelection().isCollapsed) return;
    const link = event.target.closest?.('a[href]'), linkIndex = session.links.findIndex(item => item.anchor === link);
    if (linkIndex >= 0) { event.preventDefault(); event.stopImmediatePropagation(); focus({kind: "link", index: linkIndex}); return; }
    const index = session.evidence.findIndex(item => item.ranges.some(range => [...range.getClientRects()].some(rect => event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom)));
    if (index >= 0) { event.preventDefault(); event.stopImmediatePropagation(); focus({kind: "evidence", index}); }
  }
  function onKey(event) {
    if (event.key === "Escape" && card && !card.hidden) { event.stopImmediatePropagation(); hide(); }
  }
  function apply({id, batchId, evidence = [], urls = [], quiet = false}) {
    const body = reader.current(id); clear();
    const map = textMap(body), items = [];
    for (const [index, item] of evidence.slice(0, 6).entries()) {
      if (typeof item?.quote !== "string" || typeof item?.reason !== "string" || item.quote.length > 8000 || item.reason.length > 2000) continue;
      const ranges = rangesFor(map, item.quote);
      if (ranges.length) items.push({quote: item.quote, reason: item.reason, ranges, sourceIndex: index});
    }
    const scores = new Map(urls.slice(0, 50).filter(item => item && typeof item.url === "string").map(item => [urlKey(item.url), item]));
    const links = [];
    for (const anchor of body.querySelectorAll('a[href]')) {
      if (links.length >= 200) break;
      if (!reader.visible(anchor) || anchor.closest(reader.excluded + ',' + reader.owned)) continue;
      const url = reader.destination(anchor.getAttribute("href")); if (!url) continue;
      const text = (anchor.innerText || "Liên kết không có chữ").trim().slice(0, 300), range = document.createRange(); range.selectNodeContents(anchor);
      const domain = new URL(url).hostname, result = scores.get(urlKey(url));
      let displayDomain = null;
      if (/^(?:https?:\/\/|www\.)\S+$/i.test(text) || /^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:\/\S*)?$/i.test(text)) {
        try { displayDomain = new URL(/^https?:\/\//i.test(text) ? text : "https://" + text).hostname; } catch { /* Plain labels are not domain claims. */ }
      }
      links.push({anchor, range, url, domain, displayDomain, text, risk: result?.status === "ok" && labels[result.risk_level] ? result.risk_level : null});
    }
    session = {id, batchId, body, evidence: items, links, quiet}; paint(); mount();
    document.addEventListener("click", onClick, true); document.addEventListener("keydown", onKey, true);
    window.addEventListener("hashchange", checkCurrent); window.addEventListener("popstate", checkCurrent); window.addEventListener("pagehide", pageHide);
    document.addEventListener("visibilitychange", checkCurrent);
    observer = new MutationObserver(records => {
      if (records.some(record => !record.target.closest?.(reader.owned) && !(record.type === "childList" && [...record.addedNodes, ...record.removedNodes].every(node => node.nodeType === 1 && node.matches?.(reader.owned))))) valid();
    });
    observer.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["href", "hidden", "aria-hidden", "aria-expanded", "class", "style"]});
    expiry = setTimeout(() => clear(), 15 * 60 * 1000);
    return {...status(), unmatched: evidence.length - items.length};
  }
  globalThis.PhishLensMailAnnotations = {apply, clear, focus, status};
})();
