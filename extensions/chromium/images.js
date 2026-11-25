"use strict";
window.PhishLensImages = function (app) {
  const $ = id => document.getElementById(id), canvas = $("image-canvas"), selection = $("crop-selection");
  let image = null, crop = null, start = null, revision = 0;
  function resetCrop() { crop = null; start = null; selection.hidden = true; }
  function clear() {
    revision++; if (image) image.close(); image = null; resetCrop();
    canvas.width = 0; canvas.height = 0; $("image-preview").hidden = true; $("drop-zone").hidden = false;
    $("image-file").value = ""; $("ocr-status").textContent = "Ảnh được đọc tại máy. Chưa gửi ảnh đến AI."; app.controls();
  }
  async function load(file, title = file.name || "Ảnh đã dán") {
    if (app.busy()) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Chọn ảnh PNG, JPG hoặc WebP. Chưa hỗ trợ PDF, GIF hoặc SVG.");
    if (file.size > 5 * 1024 * 1024) throw new Error("Ảnh tối đa 5 MB. Hãy cắt hoặc xuất ảnh nhỏ hơn.");
    if (app.canReplace && !app.canReplace()) return;
    const version = ++revision, editVersion = app.editVersion?.();
    let bitmap; try { bitmap = await createImageBitmap(file); } catch { throw new Error("Không mở được ảnh. Hãy xuất lại thành PNG hoặc JPEG."); }
    if (version !== revision) { bitmap.close(); return; }
    if (editVersion !== app.editVersion?.()) { bitmap.close(); return; }
    if (bitmap.width * bitmap.height > 12000000 || Math.min(bitmap.width, bitmap.height) < 20) {
      bitmap.close(); throw new Error("Ảnh cần ít nhất 20 px mỗi chiều và không quá 12 triệu điểm ảnh.");
    }
    if (image) image.close(); image = bitmap; resetCrop();
    app.selectImage(); app.clearInput();
    canvas.width = image.width; canvas.height = image.height;
    const ctx = canvas.getContext("2d"); ctx.fillStyle = "white"; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0);
    $("image-name").textContent = title + " · " + image.width + " × " + image.height;
    $("image-preview").hidden = false; $("drop-zone").hidden = true;
    $("ocr-status").textContent = "Chọn vùng chữ trên ảnh, rồi bấm Đọc chữ. Ảnh chưa được gửi đi.";
    app.controls();
  }
  function position(event) {
    const rect = canvas.getBoundingClientRect();
    return {x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)), y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))};
  }
  function paintCrop(point) {
    crop = {x: Math.min(start.x, point.x), y: Math.min(start.y, point.y), w: Math.abs(start.x - point.x), h: Math.abs(start.y - point.y)};
    selection.style.left = crop.x * 100 + "%"; selection.style.top = crop.y * 100 + "%";
    selection.style.width = crop.w * 100 + "%"; selection.style.height = crop.h * 100 + "%"; selection.hidden = false;
  }
  canvas.addEventListener("pointerdown", event => { if (!image || app.busy()) return; start = position(event); canvas.setPointerCapture(event.pointerId); event.preventDefault(); });
  canvas.addEventListener("pointermove", event => { if (start) paintCrop(position(event)); });
  canvas.addEventListener("pointerup", event => { if (!start) return; paintCrop(position(event)); start = null; if (crop.w * image.width < 20 || crop.h * image.height < 20) resetCrop(); });
  canvas.addEventListener("pointercancel", resetCrop);
  $("reset-crop").addEventListener("click", resetCrop);
  $("remove-image").addEventListener("click", () => { if (app.busy()) return; clear(); app.clearInput(); });
  $("drop-zone").addEventListener("click", () => { if (!app.busy()) $("image-file").click(); });
  $("drop-zone").addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); if (!app.busy()) $("image-file").click(); } });
  $("image-file").addEventListener("change", () => { const file = $("image-file").files[0]; if (file) load(file).catch(app.error); });
  const zone = $("input-area");
  zone.addEventListener("dragover", event => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); $("drop-zone").classList.add("dragging"); } });
  zone.addEventListener("dragleave", () => $("drop-zone").classList.remove("dragging"));
  zone.addEventListener("drop", event => {
    event.preventDefault(); $("drop-zone").classList.remove("dragging");
    if (event.dataTransfer.files.length !== 1) { app.error(new Error("Mỗi lượt chọn một ảnh để đọc chính xác hơn.")); return; }
    load(event.dataTransfer.files[0]).catch(app.error);
  });
  document.addEventListener("paste", event => {
    const files = [...(event.clipboardData?.items || [])].filter(item => item.kind === "file");
    if (!files.length) return;
    event.preventDefault(); if (files.length !== 1) { app.error(new Error("Dán một ảnh mỗi lần.")); return; }
    const file = files[0].getAsFile(); if (file) load(file, "Ảnh từ clipboard").catch(app.error);
  });
  async function read(ask = true) {
    if (!image) throw new Error("Chọn ảnh trước khi đọc chữ.");
    if (ask && app.input() && !confirm("Thay văn bản hiện tại bằng chữ đọc từ ảnh?")) return;
    const current = revision, box = crop || {x: 0, y: 0, w: 1, h: 1};
    const output = document.createElement("canvas");
    output.width = Math.max(20, Math.round(box.w * image.width)); output.height = Math.max(20, Math.round(box.h * image.height));
    output.getContext("2d").drawImage(canvas, Math.round(box.x * image.width), Math.round(box.y * image.height), output.width, output.height, 0, 0, output.width, output.height);
    const blob = await new Promise(resolve => output.toBlob(resolve, "image/png"));
    if (!blob || blob.size > 5 * 1024 * 1024) throw new Error("Vùng ảnh sau cắt còn quá lớn. Chọn vùng chữ nhỏ hơn.");
    $("ocr-status").textContent = "Đang đọc chữ tại máy… Ảnh không được lưu hoặc gửi tới AI.";
    const result = await app.request("image-text", blob);
    if (current !== revision) return;
    app.setInput(result.text); $("ocr-status").textContent = result.text ? result.notice : "Chưa nhận dạng được chữ. Thử cắt sát đoạn tin, dùng ảnh rõ hơn hoặc tự nhập nội dung.";
    if (result.text) { $("text-input").hidden = false; $("input-text").focus(); }
    return result.text;
  }
  $("read-image").addEventListener("click", () => app.perform(read, "Đang đọc chữ từ ảnh", "OCR chạy tại máy. Ảnh không được gửi đến nhà cung cấp AI."));
  return {clear, load, read, hasImage: () => Boolean(image), loadingVersion: () => revision};
};
