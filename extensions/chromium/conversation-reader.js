"use strict";
// Platform adapters: rendered messages only. Never reads storage, inbox, composer,
// hidden history, network responses or application-internal objects.
(() => {
  if (globalThis.PhishLensConversationReader) return;
  const platform = globalThis.PhishLensChatPlatforms?.detect(location.href);
  const adapters = {
    zalo: {views: '#chatView,#chat-view,.chat-view,[data-testid="chat-view"]', roots: '#messageView,#message-view,.message-view,.chat-view__body,[data-testid="message-list"]',
      messages: ['[data-component="bubble-message"],[data-node-type="bubble-message"]', '[data-message-id]', '.chat-message', '.chat-item', '.message-item', '.msg-item'],
      body: '[data-component="message-text-content"],.message-text-content,.text-message,.message-text,.message-content,.text',
      sender: '.message-sender-name-content,.message-sender-name,.sender-name,.message-author,.name,[data-testid="message-sender"]', outgoing: '[data-direction="outgoing"],[data-from-me="true"],.me,.is-outgoing,.message-out,.message-send',
      title: '.header-title,.chat-title,.conv-title,[data-testid="conversation-title"],header h1,header h2', fallback: true},
    telegram_a: {views: '#MiddleColumn', roots: '#MiddleColumn .MessageList', messages: ['.Message[data-message-id]'],
      body: '.text-content', sender: '.message-title .sender-title', outgoing: '.own', title: '.MiddleHeader .title,.MiddleHeader .fullName'},
    telegram_k: {views: '#column-center .chat', roots: '#column-center .chat .bubbles-inner', messages: ['.bubble[data-mid]:not(.is-date):not(.service)'],
      body: '.message', sender: '.bubble-content > .name,.bubble-content-wrapper > .name', outgoing: '.is-out', title: '.chat-info .peer-title,.topbar .peer-title'},
    messenger: {views: '[role="main"],main', roots: '[data-scope="messages_table"],[role="grid"],[role="log"]', messages: ['[role="row"]', '[data-message-id]', '[data-ad-rendering-role="message"]'],
      body: '[data-ad-rendering-role="message"],[data-lexical-text="true"],[dir="auto"]', sender: '[data-sender-name]',
      outgoing: '[data-direction="outgoing"],[data-from-me="true"]', title: '[role="heading"],h1,h2'}
  };
  function adapter() {
    if (!platform || PhishLensChatPlatforms.detect(location.href)?.id !== platform.id) throw new Error("Mở cuộc trò chuyện trên Zalo, Messenger hoặc Telegram Web để chọn tin.");
    if (platform.id === "telegram") {
      if (location.pathname.startsWith("/a/")) return adapters.telegram_a;
      if (location.pathname.startsWith("/k/")) return adapters.telegram_k;
      throw new Error("Mở cuộc trò chuyện trong Telegram Web A hoặc K trước khi chọn tin.");
    }
    return adapters[platform.id];
  }
  const owned = "[data-phishlens-conversation],[data-phishlens-chat-helper],[data-phishlens-dock],[data-phishlens-region]";
  const excluded = "script,style,noscript,svg,button,input,textarea,select,[contenteditable],.message-actions,.msg-actions,.reactions,.Reactions,.message-time,.timestamp,time,.time,.MessageMeta,.message-title,.message-sender-name,.message-sender-name-wrapper,.seen-msg-stt,.message-reaction-container,.sender-name,.message-author,.name,[data-testid=message-sender],[data-sender-name],[role=tooltip],[role=menu],.reply,.Reply,.reply-content,.reply-preview,.reply-wrapper,.message-quote-fragment__container,.forward-header,.forwarded,.webpage-preview,.web-page";
  const normalize = value => value.normalize("NFC").replace(/\s+/g, " ").trim();
  const visible = el => Boolean(el?.isConnected && !el.closest('[hidden],[aria-hidden="true"],[contenteditable],[role="dialog"]') && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden" && getComputedStyle(el).display !== "none");
  const ids = new WeakMap();
  let snapshot = null, observer = null, timer, marks = null;
  // Group headers, read receipts, lazy avatars and timestamps can change as a
  // virtual list is rendered. They do not constitute an edit to message text.
  const stamp = row => JSON.stringify([normalize(row.text), row.source]);
  function key(node) { if (!ids.has(node)) ids.set(node, crypto.randomUUID()); return ids.get(node); }
  function unique(elements) {
    const set = new Set(elements);
    return [...set].filter(el => { for (let parent = el.parentElement; parent; parent = parent.parentElement) if (set.has(parent)) return false; return true; });
  }
  function messageRows(root) {
    for (const selector of adapter().messages) {
      const rows = unique([...root.querySelectorAll(selector)].filter(el => {
        if (!visible(el) || el.closest(excluded + "," + owned)) return false;
        if (platform.id !== "messenger") return true;
        // Inbox/search rows link to a different thread. They are not messages,
        // even though Messenger renders both lists with the same ARIA roles.
        const body = el.matches('[data-ad-rendering-role="message"]') || el.querySelector('[data-ad-rendering-role="message"]');
        const threadLink = [...el.querySelectorAll('a[href]')].some(link => {
          try { const u = new URL(link.href); return /(^|\.)messenger\.com$/.test(u.hostname) && /^\/(?:e2ee\/)?t\//.test(u.pathname) || /(^|\.)facebook\.com$/.test(u.hostname) && /^\/messages\/t\//.test(u.pathname); } catch { return false; }
        });
        return Boolean(body || !threadLink && el.querySelector('[dir="auto"],[data-lexical-text="true"]'));
      }));
      if (rows.length) return rows.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    }
    return [];
  }
  function messengerRoot(roots, views) {
    const candidates = [];
    for (const el of roots) {
      const marker = el.matches('[data-scope="messages_table"]') || Boolean(el.querySelector('[data-scope="messages_table"]'));
      const labelled = /(?:messages|tin nhắn|nội dung trò chuyện|đoạn chat)/i.test(el.getAttribute("aria-label") || "");
      if (/(?:contacts|chats list|danh sách|người liên hệ|search results|kết quả tìm)/i.test(el.getAttribute("aria-label") || "")) continue;
      const rows = messageRows(el); if (!rows.length) continue;
      const view = el.closest(adapters.messenger.views);
      const composer = view?.querySelector('[contenteditable="true"][role="textbox"],[contenteditable="true"][data-lexical-editor="true"],textarea');
      const explicit = rows.some(row => row.matches('[data-ad-rendering-role="message"]') || row.querySelector('[data-ad-rendering-role="message"]'));
      // Unlabelled grids need both message structure and a composer in their
      // bounded main pane. Never fall back to document.body or the whole main.
      if (!marker && !labelled && !(view && composer)) continue;
      if (!marker && !labelled && !explicit && !rows.some(row => row.querySelector('[role="gridcell"] [dir="auto"]'))) continue;
      candidates.push({el, score: marker ? 100 : labelled ? 80 : explicit ? 60 : 40});
    }
    if (!candidates.length) {
      // Some layouts have message markers but no grid/log. Use only their
      // nearest scrollable list inside the main pane, never adjacent columns.
      for (const view of views) {
        for (const body of view.querySelectorAll('[data-ad-rendering-role="message"]')) {
          if (!visible(body)) continue;
          let node = body.parentElement;
          while (node && node !== view) {
            if (/(auto|scroll)/.test(getComputedStyle(node).overflowY) && !node.querySelector('[contenteditable="true"],nav,aside') && messageRows(node).length) {
              if (!candidates.some(item => item.el === node)) candidates.push({el: node, score: 30});
              break;
            }
            node = node.parentElement;
          }
        }
      }
    }
    const score = Math.max(...candidates.map(item => item.score));
    const best = candidates.filter(item => item.score === score).map(item => item.el);
    // Nested representations of the same list collapse to the inner list.
    // Distinct, equally plausible conversations are rejected rather than mixed.
    return best.filter(el => !best.some(other => other !== el && el.contains(other)));
  }
  function findRoot() {
    const config = adapter();
    const views = [...document.querySelectorAll(config.views)].filter(visible);
    if (platform.id === "zalo") {
      // Public Zalo renderer: messageView is a wrapper for banners, overlays and
      // custom scrollbars; messageViewScroll is the actual timeline inside it.
      const timelines = [...document.querySelectorAll('#messageViewScroll,.message-view__scroll__inner')].filter(el => visible(el) && el.closest(config.views));
      const lists = unique(timelines);
      if (lists.length === 1) return lists[0];
      if (lists.length > 1) throw new Error("Có nhiều khung chat đang mở. Giữ lại một cuộc trò chuyện rồi thử lại.");
    }
    const roots = [...document.querySelectorAll(config.roots)].filter(visible)
      .filter(el => !el.closest('aside,nav,[role="navigation"]'));
    const candidates = platform.id === "messenger" ? messengerRoot(roots, views) : unique(roots.length ? roots : config.fallback ? views : []);
    if (candidates.length !== 1) throw new Error(candidates.length > 1 ? "Có nhiều khung chat đang mở. Giữ lại một cuộc trò chuyện rồi thử lại." : "Chưa tìm thấy danh sách tin nhắn. Mở hẳn cuộc trò chuyện, đợi tải xong rồi thử lại; có thể bôi đen hoặc khoanh vùng đoạn cần kiểm tra.");
    return candidates[0];
  }
  function identity(root) {
    const config = adapter(), view = root.closest(config.views) || root;
    // Zalo's real header is a sibling before article#chatView, not inside it.
    const sibling = platform.id === "zalo" && view.previousElementSibling?.matches('header#header') ? view.previousElementSibling : null;
    const title = view.querySelector(config.title) || sibling?.querySelector(config.title);
    return [location.href, view.getAttribute("data-conversation-id"), view.getAttribute("data-conv-id"), platform.id === "messenger" ? "" : root.getAttribute("aria-label"), title?.textContent || ""].join("\n");
  }
  function textOf(node) {
    const chunks = [];
    function visit(el) {
      if (el.nodeType === Node.TEXT_NODE) { chunks.push(el.textContent); return; }
      if (el.nodeType !== Node.ELEMENT_NODE || !visible(el) || el.matches(excluded + "," + owned)) return;
      const block = /^(P|DIV|BR|LI|BLOCKQUOTE)$/.test(el.tagName);
      if (block) chunks.push("\n");
      for (const child of el.childNodes) visit(child);
      if (block) chunks.push("\n");
    }
    visit(node);
    return chunks.join("").replace(/[\t \u00a0]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }
  function inspect(el) {
    const config = adapter();
    const bodies = unique([...(el.matches(config.body) ? [el] : []), ...el.querySelectorAll(config.body)].filter(node => visible(node) && !node.closest(excluded + "," + owned)));
    const content = bodies.length ? bodies.map(textOf).filter(Boolean).join("\n") : config.fallback ? textOf(el) : "";
    const links = [];
    for (const anchor of bodies.flatMap(body => [...body.querySelectorAll("a[href]")]).concat(config.fallback ? [...el.querySelectorAll("a[href]")] : [])) {
      if (!visible(anchor) || anchor.closest(excluded + "," + owned)) continue;
      try {
        const url = new URL(anchor.getAttribute("href"), location.href);
        if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password && !links.includes(url.href)) links.push(url.href);
      } catch { /* Invalid links are not opened. */ }
    }
    const extra = links.filter(url => !content.includes(url));
    const text = content + (extra.length ? "\nLiên kết: " + extra.join("\n") : "");
    const container = platform.id === "zalo" ? el.closest('.chat-item,.message-item,.msg-item,[data-message-id]') || el : el;
    const sender = container.querySelector(config.sender);
    const senderText = (sender?.textContent || "").trim();
    // Do not guess "you" from colour, alignment, account names or page state.
    const outgoing = container.matches(config.outgoing) || el.matches(config.outgoing);
    const time = container.querySelector('time,.message-time,.timestamp,.time,.MessageMeta');
    // Generic DOM IDs/data-id often identify a recycled row SLOT, not a
    // message. Only message-specific attributes or Zalo's actual bubble ID
    // (bound to cliMsgId in its public renderer) are used as stable identity.
    const messageId = el.getAttribute("data-message-id") || el.getAttribute("data-msg-id") || el.getAttribute("data-mid") ||
      (platform.id === "zalo" && el.matches('[data-component="bubble-message"],[data-node-type="bubble-message"]') ? el.id : "");
    const source = messageId ? [platform.id, el.getAttribute("data-peer-id") || "", messageId].join("/") : "";
    return {text: text.trim(), sender: senderText, outgoing, source, time: (time?.getAttribute("datetime") || time?.textContent || "").trim().slice(0, 80),
      attachment: [...el.querySelectorAll('img:not([class*="emoji"]),video,audio,[data-component="photo"],.file-message')].some(node => !node.closest('.avatar,.message-avatar,.sender-avatar,.Avatar,.zl-avatar,[class*="avatar-"]'))};
  }
  function clearMarks() {
    if (marks && globalThis.CSS?.highlights) CSS.highlights.delete("phishlens-chat-evidence");
    if (marks) document.adoptedStyleSheets = document.adoptedStyleSheets.filter(sheet => sheet !== marks);
    marks = null;
  }
  function current(id, selected) {
    if (!snapshot || snapshot.id !== id || !Array.isArray(selected) || !selected.length || selected.length > (snapshot.history ? 2000 : 30) || new Set(selected).size !== selected.length) throw new Error("Chọn lại các tin nhắn cần kiểm tra.");
    const root = findRoot();
    if (snapshot.root !== root || snapshot.identity !== identity(root)) throw new Error("Cuộc trò chuyện đã thay đổi. Hãy đọc lại và chọn tin.");
    const live = snapshot.history ? new Map(messageRows(root).map(element => [inspect(element).source, element])) : null;
    return selected.map(id => {
      const item = snapshot.items.find(item => item.id === id);
      if (!item) throw new Error("Chọn lại các tin nhắn cần kiểm tra.");
      if (item.source && live?.has(item.source)) item.element = live.get(item.source);
      const loaded = item.element?.isConnected && root.contains(item.element);
      const row = loaded ? inspect(item.element) : null;
      // Virtualised history may recycle or remove an old DOM node. The frozen
      // snapshot remains valid for this conversation; only live matching IDs
      // can be checked for subsequent edits.
      if (snapshot.history && (!loaded || !item.source || row.source !== item.source)) return item;
      if (!loaded || stamp(row) !== item.stamp) throw new Error("Tin nhắn đã thay đổi hoặc không còn hiển thị trong trang. Hãy đọc lại trước khi kiểm tra.");
      return item;
    });
  }
  function observe() {
    observer?.disconnect(); clearTimeout(timer);
    observer = new MutationObserver(records => {
      if (!snapshot || records.every(record => record.target.closest?.(owned))) return;
      clearTimeout(timer); timer = setTimeout(() => {
        if (!snapshot) return;
        try {
          const ids = snapshot.selected || snapshot.items.map(item => item.id).slice(0, 30);
          if (!ids.length) return;
          current(snapshot.id, ids);
        } catch {
          clearMarks();
          chrome.runtime.sendMessage({type: "CHAT_CONTENT_CHANGED", contextId: snapshot.id}).catch(() => {});
        }
      }, 180);
    });
    observer.observe(document.body, {childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ["href", "data-conversation-id", "data-conv-id", "data-message-id", "data-mid", "data-peer-id", "data-direction", "data-from-me", "aria-label", "hidden", "aria-hidden", "class"]});
  }
  function read() {
    clearMarks(); const root = findRoot();
    // An inner list can be taller than its scroll viewport. Intersect clipping
    // ancestors so loaded, offscreen history never enters the picker.
    const clip = {top: 0, left: 0, bottom: innerHeight, right: innerWidth};
    for (let node = root; node; node = node.parentElement) {
      const rect = node.getBoundingClientRect(), css = getComputedStyle(node);
      if (node === root || /auto|scroll|hidden|clip/.test(css.overflowY)) { clip.top = Math.max(clip.top, rect.top); clip.bottom = Math.min(clip.bottom, rect.bottom); }
      if (node === root || /auto|scroll|hidden|clip/.test(css.overflowX)) { clip.left = Math.max(clip.left, rect.left); clip.right = Math.min(clip.right, rect.right); }
    }
    const elements = messageRows(root).filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.bottom > Math.max(0, clip.top) && rect.top < Math.min(innerHeight, clip.bottom) && rect.right > Math.max(0, clip.left) && rect.left < Math.min(innerWidth, clip.right) && rect.width > 0;
      });
    if (!elements.length) throw new Error("Chưa đọc được tin nhắn đang hiển thị. Cuộn tới đoạn cần kiểm tra hoặc dùng bôi đen/khoanh vùng.");
    if (elements.length > 80) throw new Error("Đang có quá nhiều tin hiển thị. Thu gọn phạm vi rồi đọc lại.");
    const speakers = new Map(), items = [];
    for (const element of elements) {
      const row = inspect(element);
      if (!row.text) continue;
      if (row.text.length > 8000) throw new Error("Một tin vượt 8.000 ký tự. Hãy bôi đen phần cần kiểm tra; nội dung chưa được gửi.");
      if (row.sender && !speakers.has(row.sender)) speakers.set(row.sender, "Người " + (speakers.size + 1));
      const speaker = row.outgoing ? "Bạn" : row.sender ? speakers.get(row.sender) : "Chưa rõ người gửi";
      items.push({id: key(element), element, text: row.text, speaker, time: row.time, attachment: row.attachment, stamp: stamp(row)});
    }
    if (!items.length) throw new Error("Đoạn đang hiển thị chưa có chữ đọc được. Với ảnh, hãy dùng khoanh vùng.");
    snapshot = {id: crypto.randomUUID(), root, identity: identity(root), items}; observe();
    return {id: snapshot.id, platform: platform.label, platformId: platform.id, scope: "visible_messages", messages: items.map(({element, stamp, ...row}) => row)};
  }
  function validate(id, ids) {
    const items = current(id, ids); snapshot.selected = ids; snapshot.items = items;
    return {valid: true, count: items.length};
  }
  function focus(id, ids, quote) {
    const items = current(id, ids), target = normalize(quote || "");
    if (!target || target.length > 400) throw new Error("Chưa có trích dẫn hợp lệ để đối chiếu.");
    if (snapshot.history) {
      const live = new Map(elements().map(element => [inspect(element).source, element]));
      for (const item of items) if (item.source && live.has(item.source)) item.element = live.get(item.source);
    }
    const matches = items.filter(item => item.element?.isConnected && stamp(inspect(item.element)) === item.stamp && normalize(inspect(item.element).text).includes(target));
    if (!matches.length) throw new Error("Tin gốc chưa nằm trong phần trang đang tải hoặc trích dẫn đã được che/sửa. Cuộn tới đoạn tin đó để đối chiếu bản đã quét.");
    clearMarks();
    const ranges = [];
    for (const item of matches) {
      const range = document.createRange(); range.selectNodeContents(item.element); ranges.push(range);
    }
    if (globalThis.CSS?.highlights && globalThis.Highlight) {
      marks = new CSSStyleSheet();
      marks.replaceSync("::highlight(phishlens-chat-evidence){background:#fff0a9;color:#37291b}");
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, marks];
      CSS.highlights.set("phishlens-chat-evidence", new Highlight(...ranges));
    }
    matches[0].element.scrollIntoView({behavior: "smooth", block: "center"});
    return {matched_messages: matches.length};
  }
  function elements(root) {
    return messageRows(root || findRoot());
  }
  function beginHistory() { clearMarks(); observer?.disconnect(); clearTimeout(timer); snapshot = null; }
  const viewOf = root => root.closest(adapter().views) || root;
  function installHistory(items, scope) {
    const root = findRoot();
    snapshot = {id: crypto.randomUUID(), root, identity: identity(root), items, history: true, scope}; observe();
    return {id: snapshot.id, platform: platform.label, platformId: platform.id, scope,
      messages: items.map(({element, stamp, source, ...row}) => row)};
  }
  globalThis.PhishLensConversationReader = {read, validate, focus, clear: clearMarks,
    history: {root: findRoot, view: viewOf, identity, elements, inspect, stamp, begin: beginHistory, install: installHistory}};
  window.addEventListener("pagehide", () => { clearMarks(); observer?.disconnect(); clearTimeout(timer); snapshot = null; });
})();
