"use strict";
(() => {
  if (globalThis.PhishLensRegion) return;
  let finishCurrent = null;
  const style = (el, values) => { Object.assign(el.style, values); return el; };
  globalThis.PhishLensRegion = {
    start(nonce, mode = "region") {
      if (finishCurrent) finishCurrent();
      const host = document.createElement("div"), root = host.attachShadow({mode: "closed"});
      host.setAttribute("data-phishlens-region", "");
      style(host, {all: "initial", position: "fixed", inset: "0", width: "100vw", height: "100vh", zIndex: "2147483647", display: "block", touchAction: "none"});
      const overlay = style(document.createElement("div"), {position: "absolute", inset: "0", cursor: "crosshair", background: "rgba(16,22,36,.2)", userSelect: "none", fontFamily: "system-ui,sans-serif"});
      const hint = style(document.createElement("div"), {position: "absolute", left: "50%", top: "18px", transform: "translateX(-50%)", padding: "12px 18px", borderRadius: "12px", background: "#171d2d", color: "white", fontSize: "13px", lineHeight: "1.6", boxShadow: "0 4px 20px #0003", maxWidth: "calc(100vw - 32px)", textAlign: "center", pointerEvents: "none"});
      hint.style.pointerEvents = "auto";
      const title = document.createElement("span"); title.textContent = "Kéo để khoanh vùng";
      const full = style(document.createElement("button"), {marginLeft: "16px", padding: "7px 11px", borderRadius: "7px", border: "1px solid #8276cf", background: "#6555cf", color: "#fff", cursor: "pointer", font: "inherit"});
      full.type = "button"; full.textContent = "Chụp toàn vùng hiển thị";
      const close = style(document.createElement("button"), {marginLeft: "10px", border: "0", background: "transparent", color: "#d5dced", cursor: "pointer", font: "inherit"});
      close.type = "button"; close.textContent = "Hủy · Esc";
      hint.append(title, full, close);
      const box = style(document.createElement("div"), {position: "absolute", border: "2px solid #9b8cff", borderRadius: "3px", boxSizing: "border-box", background: "transparent", boxShadow: "0 0 0 100vmax rgba(15,20,34,.4)", pointerEvents: "none", display: "none"});
      const size = style(document.createElement("div"), {position: "absolute", left: "0", top: "100%", marginTop: "8px", background: "#171d2d", color: "white", padding: "4px 8px", borderRadius: "5px", whiteSpace: "nowrap", fontSize: "11px"});
      box.append(size); overlay.append(box, hint); root.append(overlay); document.documentElement.append(host);
      const controller = new AbortController(), options = {capture: true, signal: controller.signal};
      let viewport = {width: innerWidth, height: innerHeight, scrollX, scrollY};
      let start = null, rectangle = null, cleaned = false;
      function cleanup() {
        if (cleaned) return; cleaned = true; clearTimeout(timer); controller.abort(); host.remove(); finishCurrent = null;
      }
      function cancel(reason = "cancelled") { cleanup(); chrome.runtime.sendMessage({type: "REGION_CANCEL", nonce, reason: typeof reason === "string" ? reason : reason.type}).catch(() => {}); }
      finishCurrent = () => cancel("replaced");
      const timer = setTimeout(() => cancel("timeout"), 120000);
      function submit(selected) {
        if (cleaned) return;
        cleanup();
        const helpers = [...document.querySelectorAll("[data-phishlens-dock],[data-phishlens-mail],[data-phishlens-annotations]")].map(el => [el, el.style.visibility]);
        helpers.forEach(([el]) => { el.style.visibility = "hidden"; });
        const restore = () => helpers.forEach(([el, visibility]) => { el.style.visibility = visibility; });
        requestAnimationFrame(() => requestAnimationFrame(() => {
          if (innerWidth !== viewport.width || innerHeight !== viewport.height || scrollX !== viewport.scrollX || scrollY !== viewport.scrollY) {
            chrome.runtime.sendMessage({type: "REGION_CANCEL", nonce, reason: "viewport"}).catch(() => {}); restore(); return;
          }
          chrome.runtime.sendMessage({type: "REGION_SELECTED", nonce, rect: selected, viewport}).catch(() => {}).finally(restore);
        }));
      }
      function wholeViewport() { viewport = {width: innerWidth, height: innerHeight, scrollX, scrollY}; submit({x: 0, y: 0, width: innerWidth, height: innerHeight}); }
      full.addEventListener("click", event => { if (event.isTrusted) { event.stopPropagation(); wholeViewport(); } });
      close.addEventListener("click", event => { if (event.isTrusted) { event.stopPropagation(); cancel("escape"); } });
      hint.addEventListener("pointerdown", event => event.stopPropagation());
      function point(event) { return {x: Math.max(0, Math.min(innerWidth, event.clientX)), y: Math.max(0, Math.min(innerHeight, event.clientY))}; }
      function draw(event) {
        const end = point(event);
        rectangle = {x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(start.x - end.x), height: Math.abs(start.y - end.y)};
        style(box, {display: "block", left: rectangle.x + "px", top: rectangle.y + "px", width: rectangle.width + "px", height: rectangle.height + "px"});
        overlay.style.background = "transparent"; size.textContent = Math.round(rectangle.width) + " × " + Math.round(rectangle.height) + " · thả để đọc chữ";
      }
      overlay.addEventListener("pointerdown", event => {
        if (!event.isTrusted || event.button !== 0) return;
        event.preventDefault(); event.stopImmediatePropagation(); viewport = {width: innerWidth, height: innerHeight, scrollX, scrollY}; start = point(event); overlay.setPointerCapture(event.pointerId); draw(event);
      }, {signal: controller.signal});
      overlay.addEventListener("pointermove", event => { if (start && event.isTrusted) { event.preventDefault(); draw(event); } }, {signal: controller.signal});
      overlay.addEventListener("pointerup", event => {
        if (!start || !event.isTrusted) return;
        event.preventDefault(); event.stopImmediatePropagation(); draw(event); start = null;
        if (rectangle.width < 20 || rectangle.height < 20) { box.style.display = "none"; title.textContent = "Vùng quá nhỏ · chọn lại"; return; }
        submit({...rectangle});
      }, {signal: controller.signal});
      overlay.addEventListener("pointercancel", cancel, {signal: controller.signal});
      window.addEventListener("keydown", event => {
        if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); cancel("escape"); }
        else if (event.isTrusted && event.key.toLowerCase() === "a" && !start) { event.preventDefault(); wholeViewport(); }
        else if (["ArrowDown", "ArrowUp", "PageDown", "PageUp", "Home", "End", " "].includes(event.key)) event.preventDefault();
      }, options);
      window.addEventListener("wheel", event => event.preventDefault(), {...options, passive: false});
      window.addEventListener("touchmove", event => event.preventDefault(), {...options, passive: false});
      window.addEventListener("resize", () => { if (start) cancel("resize"); }, options);
      window.addEventListener("scroll", cancel, options);
      if (mode === "viewport") wholeViewport();
      return {started: true};
    }
  };
})();
