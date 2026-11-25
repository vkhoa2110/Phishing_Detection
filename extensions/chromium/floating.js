"use strict";
(() => {
  if (globalThis.__phishlensDock || !/^https?:$/.test(location.protocol)) return;
  const host = document.createElement("div"), root = host.attachShadow({mode: "closed"});
  host.setAttribute("data-phishlens-dock", "");
  Object.assign(host.style, {all: "initial", position: "fixed", right: "16px", bottom: "22px", zIndex: "2147483645", display: "none", fontFamily: "system-ui,-apple-system,Segoe UI,sans-serif"});
  const make = (tag, text, css = {}) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; Object.assign(item.style, css); return item; };
  const paths = {shield: "m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5l8-3zM8 11l3 3 5-6", scan: "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M6 12h12", globe: "M3 12h18M12 3c-5 4-5 14 0 18 5-4 5-14 0-18zM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", panel: "M3 4h18v16H3zM14 4v16", pause: "M8 5v14M16 5v14", eye: "m3 3 18 18M2 12s4-7 10-7c6 0 10 7 10 7s-4 7-10 7C6 19 2 12 2 12", close: "m6 6 12 12M6 18 18 6", more: "M12 5h.01M12 12h.01M12 19h.01"};
  function icon(name, size = 18) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), path = document.createElementNS(svg.namespaceURI, "path");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", String(size)); svg.setAttribute("height", String(size)); svg.setAttribute("aria-hidden", "true");
    path.setAttribute("d", paths[name]); path.setAttribute("fill", "none"); path.setAttribute("stroke", "currentColor"); path.setAttribute("stroke-width", name === "more" ? "3.3" : "1.7"); path.setAttribute("stroke-linecap", "round"); path.setAttribute("stroke-linejoin", "round"); svg.append(path); return svg;
  }
  const baseButton = {font: "12px/1.6 system-ui,-apple-system,Segoe UI,sans-serif", border: "0", cursor: "pointer", color: "inherit", background: "transparent", boxSizing: "border-box"};
  const dock = make("div", undefined, {display: "flex", alignItems: "stretch", background: "#192438", color: "#fff", border: "1px solid #ffffff28", borderRadius: "15px", boxShadow: "0 6px 26px #15213d30", height: "50px", width: "176px", boxSizing: "border-box"});
  const main = make("button", undefined, {...baseButton, color: "#fff", display: "flex", alignItems: "center", gap: "8px", padding: "7px 8px", flex: "1", minWidth: "0", borderRadius: "14px 0 0 14px", touchAction: "none", textAlign: "left"});
  main.type = "button"; main.title = "Khoanh vùng để kiểm tra · kéo để đổi vị trí"; main.setAttribute("aria-label", "PhishLens: khoanh vùng trên trang để kiểm tra");
  const emblem = make("span", undefined, {display: "grid", placeItems: "center", width: "32px", height: "32px", flexShrink: "0", borderRadius: "10px", background: "#6761df"}); emblem.append(icon("shield", 22));
  const copy = make("span", undefined, {display: "block", minWidth: "0"}), title = make("strong", "PhishLens", {display: "block", fontSize: "12px", fontWeight: "700", letterSpacing: "-.2px"}), subtitle = make("small", "Khoanh vùng", {display: "block", fontSize: "9px", color: "#c2cce1", whiteSpace: "nowrap", marginTop: "1px"}); copy.append(title, subtitle); main.append(emblem, copy);
  const more = make("button", undefined, {...baseButton, color: "#c2cce1", width: "29px", padding: "0", borderLeft: "1px solid #ffffff16", borderRadius: "0 14px 14px 0", display: "grid", placeItems: "center"}); more.type = "button"; more.append(icon("more", 17)); more.title = "Tùy chọn PhishLens"; more.setAttribute("aria-label", "Tùy chọn PhishLens"); more.setAttribute("aria-expanded", "false"); more.setAttribute("aria-haspopup", "menu"); dock.append(main, more);
  const menu = make("div", undefined, {display: "none", position: "absolute", right: "0", bottom: "62px", width: "264px", maxWidth: "calc(100vw - 24px)", padding: "15px", border: "1px solid #e0e5f0", background: "#fff", color: "#24314a", borderRadius: "16px", boxShadow: "0 12px 45px #14244524", boxSizing: "border-box", font: "12px/1.7 system-ui,-apple-system,Segoe UI,sans-serif"});
  menu.setAttribute("role", "menu"); menu.setAttribute("aria-label", "Trợ lý PhishLens");
  const menuTitle = make("strong", "PhishLens", {display: "block", fontSize: "15px", letterSpacing: "-.3px"}), status = make("p", "Sẵn sàng khi bạn cần", {fontSize: "10px", color: "#6a7890", margin: "5px 0 12px", lineHeight: "1.8"}); menu.append(menuTitle, status);
  const items = [];
  function item(label, symbol, action, muted = false) {
    const button = make("button", undefined, {...baseButton, display: "flex", width: "100%", alignItems: "center", gap: "10px", borderRadius: "9px", textAlign: "left", padding: "10px 8px", fontSize: "11px", color: muted ? "#6b7890" : "#253650"}); button.type = "button"; button.setAttribute("role", "menuitem");
    const text = make("span", label); button.append(icon(symbol, 16), text);
    button.addEventListener("mouseenter", () => { button.style.background = "#f2f3fb"; }); button.addEventListener("mouseleave", () => { button.style.background = "transparent"; });
    button.addEventListener("click", event => { if (event.isTrusted) action(); }); menu.append(button); items.push(button); return {button, text};
  }
  let config = null, opened = false, dismissed = null, drag = null, ignoreClick = false, position = {edge: "right", ratio: .88};
  function closeMenu() { menu.style.display = "none"; opened = false; more.setAttribute("aria-expanded", "false"); }
  function layout() {
    const top = Math.max(12, Math.min(innerHeight - 62, innerHeight * position.ratio - 25));
    host.style.top = top + "px"; host.style.bottom = "auto"; host.style.left = position.edge === "left" ? "16px" : "auto"; host.style.right = position.edge === "right" ? "16px" : "auto";
    for (const panel of [menu, notice]) { panel.style.left = position.edge === "left" ? "0" : "auto"; panel.style.right = position.edge === "right" ? "0" : "auto"; }
    menu.style.bottom = top > 365 ? "62px" : "auto"; menu.style.top = top > 365 ? "auto" : "62px";
    notice.style.bottom = top > 180 ? "62px" : "auto"; notice.style.top = top > 180 ? "auto" : "62px";
  }
  function toggleMenu() { opened = !opened; menu.style.display = opened ? "block" : "none"; notice.style.display = "none"; more.setAttribute("aria-expanded", String(opened)); if (opened) { layout(); items[0].focus(); } }
  function error(message) { status.textContent = message; menu.style.display = "block"; opened = true; more.setAttribute("aria-expanded", "true"); layout(); }
  function send(type, values = {}) { return chrome.runtime.sendMessage({type, ...values}).then(result => { if (result?.error) { error(result.error); return null; } return result; }).catch(() => { error("Extension vừa cập nhật. Hãy tải lại trang để dùng PhishLens."); return null; }); }
  function capture() { closeMenu(); notice.style.display = "none"; send("START_REGION"); }
  item("Khoanh vùng để kiểm tra", "scan", capture);
  item("Chụp toàn vùng hiển thị", "scan", () => { closeMenu(); notice.style.display = "none"; send("START_REGION", {captureMode: "viewport"}); });
  item("Kiểm tra URL trang này", "globe", async () => { status.textContent = "Đang kiểm tra URL tại máy…"; await send("CHECK_PAGE"); const fresh = await send("GET_ASSISTANT"); if (fresh) update(fresh); });
  item("Mở bảng PhishLens", "panel", () => { closeMenu(); send("OPEN_ASSISTANT"); });
  menu.append(make("div", undefined, {height: "1px", background: "#e8ecf4", margin: "7px 0"}));
  const pause = item("Tạm nghỉ 1 giờ", "pause", async () => { const result = await send("ASSISTANT_PAUSE", {paused: !config?.pausedUntil}); if (result) update(result); }, true);
  item("Ẩn trên website này", "eye", async () => { await send("HIDE_SITE"); closeMenu(); }, true);
  const menuFooter = make("p", "Chụp ảnh theo yêu cầu. AI luôn chờ bạn đồng ý.", {fontSize: "9px", lineHeight: "1.8", color: "#718098", margin: "11px 4px 0", borderTop: "1px solid #e8ecf4", paddingTop: "10px"}); menu.append(menuFooter);
  const notice = make("div", undefined, {display: "none", position: "absolute", right: "0", bottom: "62px", width: "264px", maxWidth: "calc(100vw - 24px)", padding: "16px", background: "#fff", color: "#29374c", border: "1px solid #f0cbd0", borderRadius: "15px", boxShadow: "0 12px 40px #14244524", boxSizing: "border-box", font: "12px/1.8 system-ui,-apple-system,Segoe UI,sans-serif"}); notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
  const dismiss = make("button", "×", {...baseButton, position: "absolute", right: "9px", top: "7px", fontSize: "20px", color: "#7d8798", width: "25px", height: "25px", padding: "0"}); dismiss.type = "button"; dismiss.setAttribute("aria-label", "Ẩn thông báo này");
  dismiss.addEventListener("click", () => { dismissed = config?.page?.digest; notice.style.display = "none"; });
  notice.append(make("strong", "URL có dấu hiệu rủi ro", {display: "block", color: "#ac3e4d", fontSize: "12px", marginRight: "18px"}), make("p", "Kết quả dựa trên chuỗi URL, chưa xác minh trang đích. Hãy kiểm tra thêm trước khi cung cấp thông tin.", {fontSize: "10px", color: "#6d7890", margin: "8px 0 12px"}));
  const details = make("button", "Kiểm tra chi tiết →", {...baseButton, background: "#5754d6", color: "#fff", borderRadius: "8px", padding: "8px 12px", fontSize: "10px", fontWeight: "650"}); details.type = "button"; details.addEventListener("click", event => { if (event.isTrusted) { dismissed = config?.page?.digest; notice.style.display = "none"; send("OPEN_ASSISTANT", {check: true}); } }); notice.append(details, dismiss);
  function update(next) {
    config = next; position = next.position || position;
    if (!next.floatingEnabled) { dispose(); return; }
    host.style.display = next.visible ? "block" : "none";
    if (!host.isConnected) document.documentElement.append(host);
    const record = next.page || {}, labels = {HIGH: "URL cần xác minh", WARNING: "URL cần kiểm tra", LOW: "URL đã kiểm tra", UNKNOWN: "URL chưa đủ rõ"};
    title.textContent = next.pausedUntil ? "Tạm nghỉ" : "PhishLens";
    subtitle.textContent = next.pausedUntil ? "Mở menu để bật lại" : record.status === "checking" ? "Đang kiểm URL…" : record.status === "ok" ? labels[record.risk] || "Khoanh vùng" : "Khoanh vùng";
    emblem.style.background = next.pausedUntil ? "#627086" : record.status === "ok" && record.risk === "HIGH" ? "#c65463" : "#6761df";
    pause.text.textContent = next.pausedUntil ? "Bật lại trợ lý" : "Tạm nghỉ 1 giờ";
    const explanation = {idle: "Chủ động kiểm tra URL, tin nhắn hoặc vùng ảnh.", checking: "Đang kiểm tra URL tại máy…", disconnected: "Mở ứng dụng PhishLens trên máy để kết nối.", unavailable: "Chưa kiểm tra được URL. Hãy mở ứng dụng trên máy và thử lại."};
    status.textContent = !next.connected ? "Mở PhishLens trên máy rồi kết nối để kiểm tra." : next.pausedUntil ? "Tự kiểm URL đang tạm nghỉ. Bạn có thể tiếp tục bất kỳ lúc nào." : record.status === "ok" ? (record.risk === "LOW" ? "Chưa thấy dấu hiệu rõ trong chuỗi URL. Vẫn cần xác minh nguồn gửi." : labels[record.risk] + ". Chưa xác minh trang đích.") : explanation[record.status] || explanation.idle;
    if (record.status === "ok" && typeof record.score === "number") status.textContent += " Điểm mô hình: " + (record.score * 100).toLocaleString("vi-VN", {maximumFractionDigits: 1}) + "%; chưa phải xác suất đã kiểm chứng.";
    notice.style.display = next.visible && !next.pausedUntil && next.autoCheckEnabled && record.status === "ok" && record.risk === "HIGH" && record.digest !== dismissed && !opened ? "block" : "none";
    layout();
  }
  more.addEventListener("click", event => { if (event.isTrusted) toggleMenu(); });
  main.addEventListener("click", event => { if (!event.isTrusted) return; if (ignoreClick) { ignoreClick = false; return; } if (config?.pausedUntil) toggleMenu(); else capture(); });
  main.addEventListener("pointerdown", event => { if (!event.isTrusted || event.button !== 0) return; const bounds = host.getBoundingClientRect(); drag = {id: event.pointerId, x: event.clientX, y: event.clientY, left: bounds.left, top: bounds.top, moved: false}; main.setPointerCapture(event.pointerId); });
  main.addEventListener("pointermove", event => {
    if (!drag || !event.isTrusted) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < 7) return;
    drag.moved = true; closeMenu(); notice.style.display = "none";
    Object.assign(host.style, {left: Math.max(12, Math.min(innerWidth - 188, drag.left + dx)) + "px", top: Math.max(12, Math.min(innerHeight - 62, drag.top + dy)) + "px", right: "auto", bottom: "auto"});
  });
  main.addEventListener("pointerup", event => {
    if (!drag || event.pointerId !== drag.id) return;
    if (drag.moved) { ignoreClick = true; const bounds = host.getBoundingClientRect(); position = {edge: bounds.left + bounds.width / 2 < innerWidth / 2 ? "left" : "right", ratio: Math.max(.04, Math.min(.96, (bounds.top + 25) / innerHeight))}; layout(); send("DOCK_POSITION", position); }
    drag = null;
  });
  main.addEventListener("pointercancel", () => { drag = null; ignoreClick = true; });
  menu.addEventListener("keydown", event => { if (event.key === "Escape") { closeMenu(); more.focus(); event.preventDefault(); } else if (["ArrowUp", "ArrowDown"].includes(event.key)) { const current = items.indexOf(root.activeElement), direction = event.key === "ArrowDown" ? 1 : -1; items[(current + direction + items.length) % items.length].focus(); event.preventDefault(); } });
  const outside = event => { if (!event.composedPath().includes(host)) closeMenu(); }, resize = () => layout();
  document.addEventListener("pointerdown", outside, true); window.addEventListener("resize", resize);
  const listener = (request, sender) => { if (sender.id !== chrome.runtime.id) return; if (request.type === "HIDE_FLOATING") dispose(); else if (request.type === "ASSISTANT_UPDATE") update(request.state); };
  function dispose() { host.remove(); delete globalThis.__phishlensDock; chrome.runtime.onMessage.removeListener(listener); document.removeEventListener("pointerdown", outside, true); window.removeEventListener("resize", resize); }
  root.append(dock, menu, notice); globalThis.__phishlensDock = host; chrome.runtime.onMessage.addListener(listener);
  send("GET_ASSISTANT").then(result => { if (result) update(result); });
})();
