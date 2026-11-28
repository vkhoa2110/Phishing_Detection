"use strict";
// Page helpers never receive account/provider credentials or screenshots.
importScripts("conversation-platforms.js", "workspace.js", "activity.js", "analysis-jobs.js", "assistant.js", "region-capture.js", "mail.js", "conversation.js");
chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
chrome.sidePanel?.setPanelBehavior?.({openPanelOnActionClick: false})?.catch(() => {});
chrome.action.onClicked.addListener(tab => {
  PhishLensWorkspace.open(null, tab.windowId).catch(() => {});
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id: "phishlens-link", title: "Kiểm tra đường dẫn bằng PhishLens", contexts: ["link"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-selection", title: "Phân tích đoạn chọn bằng PhishLens", contexts: ["selection"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-region", title: "Khoanh vùng trên trang để kiểm tra", contexts: ["page", "image"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-viewport", title: "Chụp toàn vùng hiển thị để kiểm tra", contexts: ["page", "image"], documentUrlPatterns: ["http://*/*", "https://*/*"]});
    chrome.contextMenus.create({id: "phishlens-conversation", title: "Chọn hội thoại để kiểm tra bằng PhishLens", contexts: ["page"], documentUrlPatterns: PhishLensChatPlatforms.all.flatMap(site => site.matches)});
  });
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "phishlens-conversation") { if (PhishLensChatPlatforms.detect(tab.url)) PhishLensWorkspace.open({conversationRequest: true, sourceTab: tab.id}, tab.windowId).catch(() => {}); return; }
  if (info.menuItemId === "phishlens-region") { PhishLensCapture.start(tab).catch(error => PhishLensCapture.error(tab.windowId, error.message)); return; }
  if (info.menuItemId === "phishlens-viewport") { PhishLensCapture.start(tab, true, "viewport").catch(error => PhishLensCapture.error(tab.windowId, error.message)); return; }
  const input = info.menuItemId === "phishlens-link" ? {mode: "url", text: /^https?:\/\//i.test(info.linkUrl || "") ? info.linkUrl : ""} : {mode: "text", text: info.selectionText || ""};
  if (input.text.length > 8000) { input.text = ""; input.warning = "Đoạn chọn quá 8.000 ký tự. Hãy chọn vùng ngắn hơn."; }
  PhishLensWorkspace.open(input, tab.windowId).catch(() => {});
});
chrome.commands.onCommand.addListener(command => {
  if (command === "capture-region") chrome.tabs.query({active: true, lastFocusedWindow: true}).then(tabs => {
    if (tabs[0]) return PhishLensCapture.start(tabs[0]);
  }).catch(error => PhishLensCapture.error(undefined, error.message));
});
