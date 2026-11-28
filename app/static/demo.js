"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let samples = [], current = null, timer;
  function notify(message) {
    clearTimeout(timer); $("notice").textContent = message; $("notice").hidden = false;
    timer = setTimeout(() => { $("notice").hidden = true; }, 5000);
  }
  function text(sample) {
    return `Tiêu đề: ${sample.subject}\nNgười gửi hiển thị: ${sample.sender} <${sample.address}>\n\n${sample.paragraphs.join("\n\n")}`;
  }
  function select(id) {
    const image = id === "image"; current = image ? null : samples.find(sample => sample.id === id);
    if (!image && !current) return;
    document.querySelectorAll(".scenario").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.id === id || image && button.id === "image-sample")));
    $("mail").hidden = image; $("image-panel").hidden = !image;
    $("copy-sample").hidden = image; $("open-check").hidden = image;
    $("sample-kind").textContent = image ? "ẢNH MINH HỌA" : "EMAIL MINH HỌA";
    $("focus").textContent = image ? "Khoanh phần chữ cần kiểm tra. Đọc lại kết quả OCR trước khi gửi AI." : current.focus;
    if (image) return;
    $("subject").textContent = current.subject; $("sender").textContent = current.sender;
    $("address").textContent = current.address; $("avatar").textContent = id === "promotion" ? "AG" : id === "workshop" ? "CLB" : "TB";
    $("mail-body").replaceChildren();
    for (const paragraph of current.paragraphs) {
      const p = document.createElement("p"); let start = 0;
      for (const match of paragraph.matchAll(/https?:\/\/[^\s]+/g)) {
        p.append(document.createTextNode(paragraph.slice(start, match.index)));
        const link = document.createElement("a"); link.href = match[0]; link.textContent = match[0];
        link.addEventListener("click", event => { event.preventDefault(); notify("Đường dẫn minh họa. Dùng PhishLens để kiểm tra mà không mở trang đích."); });
        p.append(link); start = match.index + match[0].length;
      }
      p.append(document.createTextNode(paragraph.slice(start))); $("mail-body").append(p);
    }
    history.replaceState(null, "", "#" + id);
  }
  $("copy-sample").addEventListener("click", async () => {
    if (!current) return;
    try { await navigator.clipboard.writeText(text(current)); notify("Đã sao chép. Dán vào PhishLens để kiểm tra."); }
    catch { const selection = getSelection(), range = document.createRange(); range.selectNodeContents($("mail")); selection.removeAllRanges(); selection.addRange(range); notify("Dùng Ctrl+C để sao chép phần đang chọn."); }
  });
  $("open-check").addEventListener("click", () => {
    if (!current) return;
    try { sessionStorage.setItem("phishlens-demo-draft", JSON.stringify({mode: "text", text: text(current)})); location.assign("/check"); }
    catch { notify("Chưa chuyển được nội dung. Hãy sao chép rồi mở ứng dụng."); }
  });
  $("image-sample").addEventListener("click", () => { select("image"); history.replaceState(null, "", "#image"); });
  $("download-image").addEventListener("click", async () => {
    try {
      const image = $("ocr-card"); await image.decode();
      const canvas = document.createElement("canvas"); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
      canvas.getContext("2d").drawImage(image, 0, 0);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png")); if (!blob) throw new Error();
      const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url; anchor.download = "phishlens-uu-dai-demo.png";
      anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { notify("Chưa tải được ảnh. Bạn có thể khoanh trực tiếp ảnh trên trang."); }
  });
  fetch("/static/demo-samples.json").then(response => { if (!response.ok) throw new Error(); return response.json(); }).then(data => {
    samples = data;
    for (const [index, sample] of samples.entries()) {
      const button = document.createElement("button"); button.type = "button"; button.className = "scenario"; button.dataset.id = sample.id;
      const number = document.createElement("span"); number.className = "scenario-number"; number.textContent = String(index + 1).padStart(2, "0");
      const copy = document.createElement("span"), title = document.createElement("strong"), preview = document.createElement("small"), arrow = document.createElement("span");
      title.textContent = sample.title; preview.textContent = sample.preview; arrow.textContent = "›"; arrow.setAttribute("aria-hidden", "true");
      copy.append(title, preview); button.append(number, copy, arrow); button.addEventListener("click", () => select(sample.id)); $("samples").append(button);
    }
    const hash = location.hash.slice(1); select(hash === "image" || samples.some(sample => sample.id === hash) ? hash : samples[0].id);
  }).catch(() => { $("copy-sample").disabled = true; $("open-check").disabled = true; notify("Chưa tải được mẫu. Tải lại trang để thử lại."); });
  fetch("/api/health").then(response => response.ok ? response.json() : Promise.reject()).then(data => {
    if (data.application !== "PhishLens" || !data.ready) throw new Error();
    $("server-status").textContent = "Ứng dụng đã kết nối"; $("server-status").classList.add("ready");
  }).catch(() => { $("server-status").textContent = "Kiểm tra kết nối ứng dụng"; });
})();
