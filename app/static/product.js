"use strict";
(() => {
  const app = window.PhishLensWorkspace, n = app.node;
  const kinds = {false_alarm: "Có thể cảnh báo nhầm", missed_risk: "Có thể bỏ sót rủi ro", unclear: "Kết quả chưa rõ", other: "Góp ý khác"};
  const statuses = {pending: "Chờ xem xét", reviewed: "Đã xem xét", dismissed: "Đã đóng"};
  const button = (text, action) => {
    const el = n("button", "secondary-button", text); el.type = "button";
    el.addEventListener("click", async () => { el.disabled = true; try { await action(); } catch (e) { app.notify(e.message, true); } finally { el.disabled = false; } });
    return el;
  };
  const label = (text, control) => { const el = n("label", "product-field", text); el.append(control); return el; };
  const select = values => { const el = n("select"); for (const [value, text] of Object.entries(values)) { const o = n("option", "", text); o.value = value; el.append(o); } return el; };
  function feedbackForm(id, contentSaved) {
    const box = n("details", "feedback-box"), form = n("form", "product-form");
    box.append(n("summary", "", "Gửi phản hồi về kết quả này"));
    const kind = select(kinds), comment = n("textarea"), share = n("input"); comment.maxLength = 2000; comment.rows = 3; share.type = "checkbox"; share.disabled = !contentSaved;
    const privacy = n("label", "product-check"); privacy.append(share, document.createTextNode("Cho phép quản trị viên xem bản nội dung đã che và kết quả đã lưu"));
    const send = n("button", "primary-button", "Gửi phản hồi"); send.type = "submit";
    form.append(label("Loại phản hồi", kind), label("Mô tả thêm (tự bỏ thông tin riêng tư)", comment), privacy,
      n("p", "portal-muted", contentSaved ? "Mặc định chỉ gửi mức nhận định và góp ý của bạn. Nội dung chỉ được chia sẻ nếu bạn chọn ô trên." : "Lượt này chỉ lưu thông tin tổng quát nên phản hồi không kèm nội dung. Bạn vẫn có thể nêu điều cần xem xét."), send);
    form.addEventListener("submit", async event => {
      event.preventDefault(); send.disabled = true;
      try {
        await app.request("/api/feedback", {method: "POST", body: {history_id: id, kind: kind.value, comment: comment.value, share_content: share.checked}});
        form.replaceChildren(n("p", "", "Đã gửi. Bạn có thể theo dõi hoặc xóa phản hồi trong mục Phản hồi."));
        app.notify("Đã gửi phản hồi.");
      } catch (e) { app.notify(e.message, true); send.disabled = false; }
    });
    box.append(form); return box;
  }
  async function connectionsPanel() {
    const panel = n("section", "portal-panel product-panel"); panel.append(n("h2", "", "Extension trình duyệt"),
      n("p", "portal-muted", "Mở extension để kiểm tra URL, đọc ảnh hoặc dùng AI. Tự kết nối với PhishLens trên máy, không cần mã ghép nối hoặc đăng nhập."));
    const download = n("a", "secondary-button", "Tải extension (.zip)"); download.href = "/api/browser/download";
    const guide = n("p", "portal-muted", "Giải nén → chrome://extensions → Chế độ nhà phát triển → Tải tiện ích đã giải nén. Mở biểu tượng PhishLens để dùng ngay. Nếu dùng cổng riêng, nhập địa chỉ ứng dụng trong Kết nối.");
    const address = n("code", "connection-address", location.origin);
    panel.append(download, guide, address, n("p", "portal-muted", "Chế độ khách không lưu lịch sử. Các kết nối tài khoản từ bản cũ vẫn có thể thu hồi bên dưới."));
    const list = n("div", "device-list"); panel.append(list);
    async function load() {
      const data = await app.request("/api/browser/devices"); list.replaceChildren(n("h3", "", "Kết nối đang có hiệu lực"));
      if (!data.items.length) list.append(n("p", "portal-muted", "Chưa có extension được ghép nối."));
      for (const item of data.items) {
        const row = n("div", "device-row"); row.append(n("p", "portal-muted", item.origin + (item.remembered ? " · Ghi nhớ 30 ngày" : " · Phiên đăng nhập web") + " · Hết hạn: " + app.date(item.expires_at * 1000)), button("Thu hồi kết nối", async () => {
          await app.request("/api/browser/devices/" + item.id, {method: "DELETE"}); await load(); app.notify("Đã thu hồi kết nối.");
        })); list.append(row);
      }
    }
    panel.append(button("Làm mới danh sách kết nối", load)); await load(); return panel;
  }
  async function feedbackPage(root, admin = false, page = 1, status = "") {
    const path = admin ? "/api/admin/feedback" : "/api/feedback";
    const data = await app.request(path + "?" + new URLSearchParams({page, ...(admin ? {status} : {})}));
    const section = n("section", "portal-panel feedback-list"); section.id = admin ? "admin-feedback" : "my-feedback";
    section.append(n("h2", "", admin ? "Phản hồi cần xem xét" : "Phản hồi của bạn"), n("p", "portal-muted", "Góp ý phục vụ rà soát sản phẩm; việc xử lý phản hồi không tạo nhãn chuẩn hoặc tự huấn luyện model."));
    if (admin) {
      const filter = select({"": "Tất cả trạng thái", ...statuses}); filter.value = status;
      filter.setAttribute("aria-label", "Lọc trạng thái phản hồi"); filter.addEventListener("change", () => feedbackPage(root, true, 1, filter.value).catch(e => app.notify(e.message, true))); section.append(filter);
    }
    section.append(n("p", "portal-muted", data.total + " phản hồi"));
    if (!data.items.length) section.append(n("p", "", "Chưa có phản hồi phù hợp. Bạn có thể gửi góp ý từ kết quả kiểm tra hoặc lịch sử."));
    for (const item of data.items) {
      const card = n("article", "feedback-card"); card.dataset.feedbackId = item.id;
      card.append(n("h3", "", kinds[item.kind]), n("p", "portal-muted", app.date(item.created_at) + " · " + statuses[item.status]), n("p", "", item.comment || "Không có mô tả thêm."));
      const shared = item.shared_snapshot;
      card.append(n("p", "portal-muted", `Nhận định: ${app.risks[shared.risk]} · ${shared.url_count} URL · ${shared.result ? "Có chia sẻ nội dung đã che" : "Không chia sẻ nội dung"}`));
      if (admin && shared.result) {
        const detail = n("details"); detail.append(n("summary", "", "Xem nội dung và kết quả được cho phép chia sẻ"), n("pre", "", JSON.stringify(shared.result, null, 2))); card.append(detail);
      }
      if (item.review_note) card.append(n("p", "", "Phản hồi từ quản trị viên: " + item.review_note));
      if (admin) {
        const form = n("form", "product-form"), reviewStatus = select(statuses), note = n("textarea"); note.rows = 2; note.maxLength = 2000; note.value = item.review_note; reviewStatus.value = item.status;
        const save = n("button", "primary-button", "Lưu xử lý"); save.type = "submit";
        form.append(label("Trạng thái xử lý", reviewStatus), label("Ghi chú trả lời người gửi", note), save);
        form.addEventListener("submit", async event => { event.preventDefault(); save.disabled = true; try {
          await app.request(path + "/" + item.id, {method: "PATCH", body: {status: reviewStatus.value, review_note: note.value}});
          await feedbackPage(root, admin, page, status); app.notify("Đã cập nhật phản hồi.");
        } catch (e) { app.notify(e.message, true); save.disabled = false; } }); card.append(form);
      } else card.append(button("Xóa phản hồi", async () => { if (!confirm("Xóa phản hồi và phần nội dung đã chia sẻ kèm theo?")) return; await app.request(path + "/" + item.id, {method: "DELETE"}); await feedbackPage(root, admin, page, status); }));
      section.append(card);
    }
    const pages = n("div", "pagination");
    if (page > 1) pages.append(button("← Trang trước", () => feedbackPage(root, admin, page - 1, status)));
    if (page * data.page_size < data.total) pages.append(button("Trang sau →", () => feedbackPage(root, admin, page + 1, status)));
    section.append(pages);
    const previous = root.querySelector("#" + section.id); if (previous) previous.replaceWith(section); else root.append(section);
  }
  window.PhishLensProduct = {feedbackForm, connectionsPanel, feedbackPage};
})();
