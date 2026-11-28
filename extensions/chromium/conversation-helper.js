"use strict";
(() => {
  if (globalThis.__phishlensChat || !globalThis.PhishLensChatPlatforms?.detect(location.href)) return;
  const host = document.createElement("div"); host.dataset.phishlensChatHelper = "";
  Object.assign(host.style, {position: "fixed", bottom: "20px", right: "20px", zIndex: "2147483644"});
  const root = host.attachShadow({mode: "closed"}), button = document.createElement("button"), sheet = new CSSStyleSheet();
  sheet.replaceSync("button{font:600 13px/1.4 system-ui;padding:12px 17px;background:#5d52cc;color:white;border:1px solid #8d83e0;border-radius:13px;box-shadow:0 6px 24px #3229662b;cursor:pointer}button:hover{background:#4e43b9}button:focus-visible{outline:3px solid #c4bafd;outline-offset:3px}");
  root.adoptedStyleSheets = [sheet];
  button.type = "button"; button.textContent = "✦ Kiểm tra hội thoại";
  button.setAttribute("aria-label", "Chọn tin trong hội thoại để kiểm tra bằng PhishLens");
  button.addEventListener("click", event => { if (event.isTrusted) chrome.runtime.sendMessage({type: "OPEN_CONVERSATION"}).then(result => { if (result?.error) button.textContent = "Mở PhishLens để kết nối"; }).catch(() => { button.textContent = "Tải lại trang để dùng PhishLens"; }); });
  root.append(button); document.documentElement.append(host); globalThis.__phishlensChat = host;
  const listener = (message, sender) => { if (sender.id === chrome.runtime.id && message.type === "STOP_CHAT_HELPER") { host.remove(); delete globalThis.__phishlensChat; chrome.runtime.onMessage.removeListener(listener); } };
  chrome.runtime.onMessage.addListener(listener);
})();
