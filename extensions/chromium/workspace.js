"use strict";
// Native side panel first; otherwise tile one details window beside its source.
globalThis.PhishLensWorkspace = (() => {
  const page = chrome.runtime.getURL("check.html"), dockKey = "workspaceDock";
  let opening = Promise.resolve(), recentlyCreated = null;
  const isOurs = tab => tab?.url?.split(/[?#]/)[0] === page;
  const bounds = win => ({left: win.left, top: win.top, width: win.width, height: win.height});
  const sameBounds = (a, b) => ["left", "top", "width", "height"].every(key => Math.abs(a[key] - b[key]) <= 2);
  function enqueue(action) {
    const operation = opening.catch(() => {}).then(action);
    opening = operation; return operation;
  }
  async function findWindow() {
    const windows = await chrome.windows.getAll(), contexts = await chrome.runtime.getContexts({contextTypes: ["TAB"]});
    const ours = new Set(contexts.filter(value => value.documentUrl?.split(/[?#]/)[0] === page).map(value => value.windowId));
    return windows.find(value => value.type === "popup" && (ours.has(value.id) || value.id === recentlyCreated?.id && Date.now() - recentlyCreated.created < 5000));
  }
  async function position(id, rectangle) {
    const win = await chrome.windows.get(id);
    // Chrome forbids bounds together with maximized/fullscreen state updates.
    if (win.state !== "normal") await chrome.windows.update(id, {state: "normal"});
    return chrome.windows.update(id, rectangle);
  }
  async function show(input, focus, rectangle = null) {
    let win = await findWindow();
    if (!win) {
      win = await chrome.windows.create({url: page + "?workspace=1&capture=1", type: "popup", width: 440, height: 850, ...rectangle, focused: focus});
      recentlyCreated = {id: win.id, created: Date.now()};
    } else if (rectangle) win = await position(win.id, rectangle);
    if (input) await chrome.storage.session.set({workspaceInput: {...input, targetWindowId: win.id, created: Date.now(), nonce: crypto.randomUUID()}});
    if (focus) await chrome.windows.update(win.id, {focused: true});
    return win;
  }
  async function restore() {
    const {[dockKey]: dock} = await chrome.storage.session.get(dockKey);
    if (!dock) return;
    await chrome.storage.session.remove(dockKey);
    try {
      const current = await chrome.windows.get(dock.sourceId);
      // Respect a layout the user has manually moved/resized in the meantime.
      if (current.state !== "normal" || !sameBounds(current, dock.applied)) return;
      await position(dock.sourceId, bounds(dock.original));
      if (["maximized", "fullscreen"].includes(dock.original.state)) await chrome.windows.update(dock.sourceId, {state: dock.original.state});
    } catch { /* The source browser window has already closed. */ }
  }
  function layout(area) {
    const gap = 8;
    if (area.width >= 900) {
      const width = Math.min(480, Math.max(360, Math.round(area.width * .34)));
      return {source: {...bounds(area), width: area.width - width - gap},
        details: {left: area.left + area.width - width, top: area.top, width, height: area.height}};
    }
    // A narrow screen/window keeps both views usable by stacking them.
    const height = Math.round((area.height - gap) * .53);
    return {source: {...bounds(area), height},
      details: {left: area.left, top: area.top + height + gap, width: area.width, height: area.height - height - gap}};
  }
  async function availableArea(windowId, rectangle) {
    try {
      const [tab] = await chrome.tabs.query({active: true, windowId});
      const [value] = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: () =>
        ({left: screen.availLeft, top: screen.availTop, width: screen.availWidth, height: screen.availHeight})});
      const area = value.result;
      if (!["left", "top", "width", "height"].every(key => Number.isFinite(area?.[key])) || area.width < 320 || area.height < 240) return rectangle;
      const left = Math.max(rectangle.left, area.left), top = Math.max(rectangle.top, area.top);
      const width = Math.min(rectangle.left + rectangle.width, area.left + area.width) - left;
      const height = Math.min(rectangle.top + rectangle.height, area.top + area.height) - top;
      return width >= 500 && height >= 400 ? {left, top, width, height} : area;
    } catch { return rectangle; } // Restricted pages retain the browser bounds.
  }
  function dock(input, windowId) {
    return enqueue(async () => {
      let source = await chrome.windows.get(windowId);
      if (source.type !== "normal" || source.incognito) return show(input, true);
      const {[dockKey]: previous} = await chrome.storage.session.get(dockKey);
      let original = {...bounds(source), state: source.state};
      if (previous?.sourceId === windowId && source.state === "normal" && sameBounds(source, previous.applied)) original = previous.original;
      else if (previous) { await restore(); source = await chrome.windows.get(windowId); original = {...bounds(source), state: source.state}; }
      const split = layout(await availableArea(windowId, original));
      try {
        const applied = await position(windowId, split.source);
        const win = await show(input, true, split.details);
        await chrome.storage.session.set({[dockKey]: {sourceId: windowId, detailsId: win.id, original, applied: bounds(applied)}});
        return win;
      } catch (error) {
        await chrome.storage.session.remove(dockKey);
        try {
          await position(windowId, bounds(original));
          if (["maximized", "fullscreen"].includes(original.state)) await chrome.windows.update(windowId, {state: original.state});
        } catch { /* The source may have closed during layout. */ }
        throw error;
      }
    });
  }
  function popup(input, focus = true) { return enqueue(() => show(input, focus)); }
  function preparePanel(windowId) {
    // Must run synchronously in the trusted click handler, before any await.
    if (!Number.isInteger(windowId) || !chrome.sidePanel?.open) return Promise.resolve(false);
    try { return chrome.sidePanel.open({windowId}).then(() => true, () => false); }
    catch { return Promise.resolve(false); }
  }
  function open(input, windowId, preferPanel = true, prepared = null) {
    if (!Number.isInteger(windowId)) return popup(input);
    const panel = preferPanel ? prepared || preparePanel(windowId) : Promise.resolve(false);
    return panel.then(opened => {
      if (!opened) return dock(input, windowId);
      return enqueue(async () => {
        const {[dockKey]: previous} = await chrome.storage.session.get(dockKey);
        await restore();
        if (previous) { try { await chrome.windows.update(previous.detailsId, {state: "minimized"}); } catch { /* Closed meanwhile. */ } }
        if (input) await chrome.storage.session.set({panelInput: {...input, windowId, created: Date.now(), nonce: crypto.randomUUID()}});
        return {id: windowId};
      });
    });
  }
  chrome.windows.onRemoved.addListener(id => {
    enqueue(async () => {
      const {[dockKey]: dock} = await chrome.storage.session.get(dockKey);
      if (dock?.detailsId === id) await restore();
      else if (dock?.sourceId === id) await chrome.storage.session.remove(dockKey);
    }).catch(() => {});
  });
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (message?.type !== "DETACH_WORKSPACE") return;
    if (sender.id !== chrome.runtime.id || !isOurs(sender)) return;
    enqueue(async () => { await restore(); return show(message.input, true); })
      .then(win => respond({windowId: win.id}), error => respond({error: error.message}));
    return true;
  });
  return {open, popup, preparePanel};
})();
