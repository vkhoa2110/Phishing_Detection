"use strict";
// One host registry for the worker, panel and isolated page readers.
globalThis.PhishLensChatPlatforms = (() => {
  const all = [
    {id: "zalo", label: "Zalo Web", origins: ["https://chat.zalo.me/*"], matches: ["https://chat.zalo.me/*"]},
    {id: "messenger", label: "Messenger", origins: ["https://messenger.com/*", "https://www.messenger.com/*", "https://www.facebook.com/*", "https://web.facebook.com/*"],
      matches: ["https://messenger.com/*", "https://www.messenger.com/*", "https://www.facebook.com/messages*", "https://web.facebook.com/messages*"]},
    {id: "telegram", label: "Telegram Web", origins: ["https://web.telegram.org/*"], matches: ["https://web.telegram.org/*"]}
  ];
  function detect(value) {
    try {
      const u = new URL(value);
      if (u.protocol !== "https:" || u.username || u.password || u.port) return null;
      if (u.hostname === "chat.zalo.me") return all[0];
      if (["messenger.com", "www.messenger.com"].includes(u.hostname) ||
          ["www.facebook.com", "web.facebook.com"].includes(u.hostname) && /^\/messages(?:\/|$)/.test(u.pathname)) return all[1];
      if (u.hostname === "web.telegram.org" && /^\/(?:[ak](?:\/|$))?$/.test(u.pathname)) return all[2];
    } catch { /* Unsupported URL. */ }
    return null;
  }
  return {all, detect, get: id => all.find(site => site.id === id), label: id => all.find(site => site.id === id)?.label || "Hội thoại"};
})();
