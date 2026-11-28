"use strict";
// Scroll only the chosen chat's rendered list. Never calls app-private APIs,
// reads app stores, clicks messages, or sends anything to the AI provider.
(() => {
  if (globalThis.PhishLensConversationHistory) return;
  const reader = PhishLensConversationReader.history;
  let scan = null;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const day = date => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
  function validDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    const date = new Date(+match[1], +match[2] - 1, +match[3]);
    return day(date) === value ? value : null;
  }
  function parseDate(value) {
    value = String(value || "").trim();
    if (/^20\d{2}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
      const date = new Date(value); return Number.isNaN(+date) ? null : day(date);
    }
    if (/^\d{10}(?:\d{3})?$/.test(value)) {
      const date = new Date(Number(value) * (value.length === 10 ? 1000 : 1));
      return date.getFullYear() >= 2000 && date.getFullYear() <= 2100 ? day(date) : null;
    }
    let m = /\b(20\d{2})-(\d{2})-(\d{2})(?:\b|T)/.exec(value);
    if (m) return validDate(`${m[1]}-${m[2]}-${m[3]}`);
    m = /\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})\b/.exec(value);
    if (!m) m = /(?:ngày\s*)?(\d{1,2})\s+tháng\s+(\d{1,2})[,]?\s+(?:năm\s*)?(20\d{2})/i.exec(value);
    if (m) return validDate(`${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`);
    if (/^(hôm nay|today)$/i.test(value)) return day(new Date());
    if (/^(hôm qua|yesterday)$/i.test(value)) { const date = new Date(); date.setDate(date.getDate() - 1); return day(date); }
    // Only accept English month names when an explicit year is present.
    if (/\b20\d{2}\b/.test(value) && /\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/i.test(value)) {
      const date = new Date(value); if (!Number.isNaN(+date)) return day(date);
    }
    return null;
  }
  function dateOf(element, root) {
    const direct = [element, ...element.querySelectorAll('time,[data-timestamp],[data-date],[datetime]')];
    for (const node of direct) for (const attribute of ["data-timestamp", "data-time", "data-date", "datetime", "title", "aria-label"]) {
      const value = parseDate(node.getAttribute(attribute)); if (value) return value;
    }
    const group = element.closest('.message-date-group,.bubbles-date-group,[data-date]');
    if (group && root.contains(group)) {
      const value = parseDate(group.getAttribute("data-date")) || parseDate(group.querySelector('.sticky-date,.date-header,.date-separator,.chat-date,.date-divider')?.textContent);
      if (value) return value;
    }
    let found = null;
    for (const header of root.querySelectorAll('.sticky-date,.date-header,.date-separator,.chat-date,.date-divider,.date-sep')) {
      if (element.contains(header) || !(header.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      const value = parseDate(header.getAttribute("data-date")) || parseDate(header.textContent);
      if (value) found = value;
    }
    return found;
  }
  function scrollable(root) {
    const messages = reader.elements(root), view = reader.view(root), candidates = [];
    // Native viewports are often INSIDE a non-scrolling wrapper (#messageView
    // -> custom Scrollbars -> native overflow:auto -> messageViewScroll on
    // Zalo). All ancestors common to message bubbles form one bounded chain.
    // Prefer the innermost native scrolling viewport over overflow:hidden
    // wrappers; multiple nested candidates do not mean ambiguous conversations.
    for (let node = messages[0]?.parentElement || root; node; node = node.parentElement) {
      if (node === document.body || node === document.documentElement) break;
      if (messages.every(message => node.contains(message)) && node.clientHeight > 0 && !node.querySelector('[contenteditable="true"],textarea')) {
        const overflow = getComputedStyle(node).overflowY;
        if (/^(auto|scroll|overlay)$/.test(overflow)) candidates.push({node, rank: 2});
        else if (overflow === "hidden" && node.scrollHeight > node.clientHeight + 4) candidates.push({node, rank: 1});
      }
      if (node === view) break;
    }
    return candidates.sort((a, b) => b.rank - a.rank)[0]?.node || null;
  }
  function limits(node) {
    const extent = Math.max(0, node.scrollHeight - node.clientHeight);
    // column-reverse lists use negative scrollTop: zero is the newest end.
    const reversed = getComputedStyle(node).flexDirection === "column-reverse";
    return {older: reversed ? -extent : 0, newer: reversed ? 0 : extent};
  }
  function move(node, top) {
    node.scrollTo({top, behavior: "instant"});
    node.dispatchEvent(new Event("scroll"));
  }
  function assertSource(task) {
    if (task !== scan || task.cancelled) return false;
    let root;
    try { root = reader.root(); } catch (error) {
      // A virtual list may briefly remove every row before rendering its next
      // page. Keep the existing bounded pane only while its identity is intact.
      if (!task.root.isConnected || reader.identity(task.root) !== task.identity) throw error;
      root = task.root;
    }
    if (reader.identity(root) !== task.identity) throw new Error("Bạn đã đổi cuộc trò chuyện. Chọn lại phạm vi; chưa gửi nội dung tới AI.");
    task.root = root;
    if (document.visibilityState === "hidden") { task.cancelled = true; task.reason = "source_hidden"; return false; }
    return true;
  }
  function status(id) {
    if (!scan || scan.id !== id) throw new Error("Lượt tải hội thoại đã hết. Chọn lại phạm vi.");
    const {state, count, pages, reason, error, result, cancelled, phase} = scan;
    const node = scan.container;
    const diagnostics = {version: "0.17.0", platform: PhishLensChatPlatforms.detect(location.href)?.id, state, phase, mode: scan.options.mode, requested_limit: scan.options.limit, count, pages, reason: reason || null,
      stable_message_ids: scan.map.size, uncertain_ids: Boolean(scan.uncertain), updated_messages: scan.updated.size,
      scroll: node?.isConnected ? {overflow: getComputedStyle(node).overflowY, height: node.clientHeight, content_height: node.scrollHeight, position: Math.round(node.scrollTop), direction: getComputedStyle(node).flexDirection} : null};
    return {id, state, count, pages, reason, error, cancelled, phase, diagnostics, ...(state === "complete" ? {result} : {})};
  }
  const normalized = value => value.normalize("NFC").replace(/\s+/g, " ").trim();
  function overlap(rows, previous) {
    const equal = (row, item) => row.source && item.source ? row.source === item.source : normalized(row.text) === normalized(item.text) && (!row.date || !item.date || row.date === item.date);
    let best = [], score = 0;
    // Align contiguous rendered windows instead of deduplicating all history
    // globally by text. The same "ok" in two distant pages remains two turns.
    for (let offset = -rows.length + 1; offset < previous.length; offset++) {
      const start = Math.max(0, -offset), end = Math.min(rows.length, previous.length - offset);
      if (end - start <= score) continue;
      let valid = true;
      for (let i = start; i < end; i++) if (!equal(rows[i], previous[i + offset])) { valid = false; break; }
      if (valid) { best = Array.from({length: end - start}, (_, n) => [start + n, previous[start + n + offset]]); score = end - start; }
    }
    return new Map(best);
  }
  function merge(task, direction) {
    const window = [];
    let elements = reader.elements(task.root);
    if (!task.initialized && elements.length > task.options.limit) { elements = elements.slice(-task.options.limit); task.initialTrimmed = true; }
    const rows = elements.map(element => ({...reader.inspect(element), element, date: dateOf(element, task.root)})).filter(row => row.text);
    const seen = new Set();
    for (const row of rows) if (row.source) { if (seen.has(row.source)) task.untrusted.add(row.source); seen.add(row.source); }
    for (const row of rows) if (task.untrusted.has(row.source)) row.source = "";
    const matched = overlap(rows, task.lastWindow);
    for (const [index, row] of rows.entries()) {
      const {element, source, date} = row;
      if (!source) task.uncertain = true;
      const live = task.dom.get(element);
      let item = (source && task.map.get(source)) || matched.get(index) ||
        (live && normalized(live.text) === normalized(row.text) && (!source || !live.source || source === live.source) ? live : null);
      if (!item) {
        if (task.items.length + window.filter(item => !task.items.includes(item)).length >= 2000 || task.characters + row.text.length + 70 > 190000) { task.reason = "safety_limit"; break; }
        item = {id: crypto.randomUUID(), element, text: row.text, rawSpeaker: row.sender, outgoing: row.outgoing,
          time: row.time, date, attachment: row.attachment, source: source || "", stamp: reader.stamp(row)};
        task.characters += row.text.length + 70;
      } else {
        // Capture the latest observed version before the review step. A live
        // conversation is not an immutable transaction; do not abort the whole
        // scan because of edits or asynchronously enriched rendering metadata.
        if (normalized(item.text) !== normalized(row.text)) {
          if (task.characters - item.text.length + row.text.length > 190000) { task.reason = "safety_limit"; break; }
          task.characters += row.text.length - item.text.length; task.updated.add(item.id); item.text = row.text;
        }
        Object.assign(item, {element, source: source || item.source, stamp: reader.stamp({...row, source: source || item.source}), attachment: row.attachment});
        if (row.sender) item.rawSpeaker = row.sender;
        if (row.outgoing) item.outgoing = true;
        if (date) item.date = date;
      }
      if (source) task.map.set(source, item);
      task.dom.set(element, item);
      window.push(item);
    }
    const previous = task.items;
    // Reconcile overlapping windows in visual order. Stable platform IDs retain
    // repeated messages; sequence matching without IDs is reported uncertain.
    for (let index = window.length - 1; index >= 0; index--) {
      const item = window[index];
      if (previous.includes(item)) continue;
      const next = window.slice(index + 1).find(row => previous.includes(row));
      if (next) previous.splice(previous.indexOf(next), 0, item);
      else {
        const before = window.slice(0, index).reverse().find(row => previous.includes(row));
        if (before) previous.splice(previous.indexOf(before) + 1, 0, item);
        else if (direction === "older") previous.unshift(item);
        else previous.push(item);
      }
    }
    // Initial/downward windows must preserve their original order too.
    if (!task.initialized) { task.items = [...window]; task.initialized = true; }
    task.lastWindow = window;
    task.count = task.items.length;
    return window;
  }
  async function collect(task) {
    let container = scrollable(task.root), stagnant = 0, boundary = false, lastGrowth = Date.now();
    task.container = container; task.phase = "positioning";
    const started = Date.now();
    // Latest/date/all are anchored at the currently loaded newest end first.
    if (container) {
      let settled = 0;
      for (let n = 0; Date.now() - started < 20000 && assertSource(task); n++) {
        const tail = () => JSON.stringify(reader.elements(task.root).slice(-3).map(element => { const row = reader.inspect(element); return [row.source, normalized(row.text)]; }));
        const before = tail(); move(container, limits(container).newer); await pause(400);
        if (before === tail() && Math.abs(container.scrollTop - limits(container).newer) < 4) settled++; else settled = 0;
        // Virtualised pages can replace rows without changing scrollHeight.
        if (settled >= 6) break;
      }
    }
    while (assertSource(task)) {
      container = scrollable(task.root) || (container?.isConnected ? container : null);
      task.container = container; task.phase = container ? "collecting" : "manual";
      const count = task.count, rows = merge(task, "older"); task.pages++;
      if (task.count > count) lastGrowth = Date.now();
      if (task.reason === "safety_limit") break;
      const dated = task.items.filter(row => row.date);
      if (task.options.mode === "latest" && task.count >= task.options.limit) { task.reason = "requested_count"; break; }
      if (task.options.mode === "dates" && rows.length && rows.every(row => row.date) && dated.some(row => row.date < task.options.from)) {
        task.reason = "date_boundary"; boundary = true; break;
      }
      if (task.count >= task.options.limit) { task.reason = "message_limit"; break; }
      if (Date.now() - started > 120000 || task.pages >= 240) { task.reason = "time_limit"; break; }
      if (!container) {
        // Do not immediately return the first 14-15 loaded messages. Give the
        // app time to mount its viewport; manual scrolling also accumulates
        // messages while the panel reports that automatic scrolling is absent.
        if (Date.now() - lastGrowth > 15000) { task.reason = "no_scroll_container"; break; }
        await pause(450); continue;
      }
      // No new IDs while moving inside a tall loaded page is normal. Only
      // consider an exhausted boundary after actually reaching the top.
      const edge = limits(container), busy = task.root.querySelector('[aria-busy="true"],[role="progressbar"],.loading-top,.top-loader');
      if (task.count === count && Math.abs(container.scrollTop - edge.older) <= 4 && !busy) stagnant++; else stagnant = 0;
      if (stagnant >= 14 && Date.now() - lastGrowth > 6000) { task.reason = "no_more_loaded"; break; }
      move(container, Math.max(Math.min(edge.older, edge.newer), container.scrollTop - Math.max(100, container.clientHeight * .8)));
      await pause(450);
    }
    if (task !== scan) return;
    if (reader.identity(task.root) !== task.identity) throw new Error("Hội thoại đã thay đổi trong lúc tải. Hãy chọn lại.");
    let items = task.items;
    const unknown = items.filter(row => !row.date).length;
    if (task.options.mode === "dates") items = items.filter(row => row.date && row.date >= task.options.from && (!task.options.to || row.date <= task.options.to));
    items = items.slice(-task.options.limit);
    if (!items.length && !task.cancelled) throw new Error(task.options.mode === "dates" && unknown ? "Chưa đọc được ngày của các tin. Chọn số tin gần nhất hoặc dùng giao diện ngày có đủ năm." : "Không có tin trong phạm vi đã chọn.");
    const speakers = new Map();
    items = items.map(item => {
      if (item.rawSpeaker && !speakers.has(item.rawSpeaker)) speakers.set(item.rawSpeaker, "Người " + (speakers.size + 1));
      const {rawSpeaker, outgoing, ...rest} = item;
      return {...rest, speaker: outgoing ? "Bạn" : rawSpeaker ? speakers.get(rawSpeaker) : "Chưa rõ người gửi"};
    });
    const scope = {mode: task.options.mode, requested_limit: task.options.limit, from_date: task.options.from || null, to_date: task.options.to || null,
      collected_count: items.length, stop_reason: task.cancelled ? task.reason || "user_cancelled" : task.reason,
      unknown_dates: unknown, complete: !task.cancelled && (task.reason === "requested_count" || boundary) && !task.uncertain};
    task.result = {...reader.install(items, scope), dedup_uncertain: task.uncertain, updated_messages: task.updated.size,
      partial: !scope.complete, requested_count_missing: task.options.mode === "latest" && items.length < task.options.limit};
    task.phase = "complete";
    task.state = "complete";
  }
  function start(options) {
    if (scan?.state === "running") throw new Error("Đang tải hội thoại. Dừng lượt hiện tại trước.");
    if (!["latest", "dates", "all"].includes(options?.mode) || !Number.isInteger(options.limit) || options.limit < 1 || options.limit > 2000) throw new Error("Chọn phạm vi từ 1 đến 2.000 tin.");
    if (options.mode === "dates" && (!validDate(options.from) || options.to && (!validDate(options.to) || options.from > options.to))) throw new Error("Chọn ngày bắt đầu và ngày kết thúc hợp lệ.");
    if (options.mode !== "dates") options = {...options, from: "", to: ""};
    reader.begin();
    const root = reader.root();
    scan = {id: crypto.randomUUID(), options, root, identity: reader.identity(root), state: "running", count: 0, pages: 0, map: new Map(), dom: new WeakMap(), updated: new Set(), untrusted: new Set(), lastWindow: [], items: [], characters: 0, cancelled: false, phase: "starting"};
    const task = scan;
    collect(task).catch(error => { task.state = "error"; task.error = error.message; task.items = []; task.lastWindow = []; task.dom = new WeakMap(); task.map.clear(); task.updated.clear(); task.untrusted.clear(); });
    return status(task.id);
  }
  function cancel(id) { status(id); scan.cancelled = true; scan.reason = "user_cancelled"; return status(id); }
  globalThis.PhishLensConversationHistory = {start, status, cancel, parseDate};
  window.addEventListener("pagehide", () => { if (scan) { scan.cancelled = true; scan.items = []; scan.map.clear(); } scan = null; });
})();
