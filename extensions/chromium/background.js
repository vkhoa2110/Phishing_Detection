"use strict";
// Page helpers never receive account/provider credentials or screenshots.
importScripts("assistant.js", "region-capture.js", "mail.js");
chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id: "phishlens-link", title: "Kiểm tra đường dẫn bằng PhishLens", contexts: ["link"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-selection", title: "Phân tích đoạn chọn bằng PhishLens", contexts: ["selection"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-region", title: "Khoanh vùng trên trang để kiểm tra", contexts: ["page", "image"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-viewport", title: "Chụp toàn vùng hiển thị để kiểm tra", contexts: ["page", "image"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
  });
});
async function openCheck(input) {
  const pending = await chrome.storage.session.get(null), expired = [];
  for (const [key, value] of Object.entries(pending)) if (key.startsWith("input-") && value.created < Date.now() - 600000) expired.push(key);
  if (expired.length) await chrome.storage.session.remove(expired);
  const id = "input-" + crypto.randomUUID();
  if (input.text.length > 8000) input = {mode: input.mode, text: "", warning: "Đoạn chọn vượt 8.000 ký tự. Hãy chọn đoạn ngắn hơn hoặc dán phần cần kiểm tra."};
  await chrome.storage.session.set({[id]: {...input, created: Date.now()}});
  try {
    await chrome.windows.create({url: chrome.runtime.getURL("check.html#" + id), type: "popup", width: 590, height: 860});
  } catch (error) { await chrome.storage.session.remove(id); throw error; }
}
async function handleContext(info) {
  if (info.menuItemId === "phishlens-link") {
    const text = /^https?:\/\//i.test(info.linkUrl || "") ? info.linkUrl : "";
    await openCheck({mode: "url", text, warning: text ? "" : "Chỉ kiểm tra đường dẫn HTTP/HTTPS."});
  } else if (info.menuItemId === "phishlens-selection") await openCheck({mode: "text", text: info.selectionText || ""});
}
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "phishlens-region") { PhishLensCapture.start(tab).catch(error => PhishLensCapture.error(tab.windowId, error.message)); return; }
  if (info.menuItemId === "phishlens-viewport") { PhishLensCapture.start(tab, true, "viewport").catch(error => PhishLensCapture.error(tab.windowId, error.message)); return; }
  const panel = chrome.sidePanel.open({windowId: tab.windowId});
  panel.then(async () => {
    const input = info.menuItemId === "phishlens-link" ? {mode: "url", text: /^https?:\/\//i.test(info.linkUrl || "") ? info.linkUrl : ""} : {mode: "text", text: info.selectionText || ""};
    if (input.text.length > 8000) { input.text = ""; input.warning = "Đoạn chọn quá 8.000 ký tự. Hãy chọn vùng ngắn hơn."; }
    await chrome.storage.session.set({panelInput: {...input, windowId: tab.windowId, created: Date.now(), nonce: crypto.randomUUID()}});
  }).catch(() => handleContext(info).catch(() => {}));
});
chrome.commands.onCommand.addListener(command => {
  if (command === "capture-region") chrome.tabs.query({active: true, lastFocusedWindow: true}).then(tabs => {
    if (tabs[0]) return PhishLensCapture.start(tabs[0]);
  }).catch(error => PhishLensCapture.error(undefined, error.message));
});
