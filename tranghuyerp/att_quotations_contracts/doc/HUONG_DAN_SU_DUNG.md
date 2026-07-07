# HƯỚNG DẪN SỬ DỤNG — QUẢN LÝ BÁO GIÁ & HỢP ĐỒNG NGUYÊN TẮC

Module: `att_quotations_contracts` — Trang Huy Logistics
Phạm vi: Báo giá bán/mua → Hợp đồng nguyên tắc (HĐNT) → Phụ lục → Đơn thực thi (SO/PO)

---

## 1. THUẬT NGỮ

| Thuật ngữ | Nghĩa |
|---|---|
| **Báo giá bán** | Đơn SO nháp gửi khách hàng, số `QT/2026/xxxxx` |
| **Báo giá NCC (RFQ)** | Yêu cầu báo giá gửi nhà cung cấp vận tải, số `QTM/2026/xxxxx/mã NCC` |
| **HĐNT** | Hợp đồng nguyên tắc ký khung với KH hoặc NCC |
| **Phụ lục** | Phụ lục giá kèm HĐNT — **nguồn giá duy nhất** của mọi đơn thực thi |
| **SO/PO thực thi** | Đơn bán/mua thật sinh từ phụ lục, giá khóa theo phụ lục |

## 2. VỊ TRÍ MENU

- **Sales → Hợp đồng NT**: Hợp đồng bán · Phụ lục bán · SO thực thi
- **Purchase → Hợp đồng NT**: Hợp đồng mua · Phụ lục mua · PO theo hợp đồng
- **Sales → Configuration**: Thư viện điều khoản · Hình thức vận chuyển · Lý do thanh lý HĐ

## 3. CHUẨN BỊ TRƯỚC KHI DÙNG (admin làm 1 lần)

1. **Phân quyền** (Settings → Users): gán user vào đúng nhóm
   - *ATT Contracts: User* — nhân viên sale/purchase
   - *ATT Contracts: Managers Sale/Purchase* — duyệt giá, chốt thầu, tạo HĐ, duyệt phụ lục
   - *ATT Contracts: CEO / Giám đốc* — xác nhận hiệu lực HĐ, duyệt thanh lý
2. **Ảnh nhận diện trên PDF** (Settings → Companies): logo header, logo ESG, con dấu, chữ ký, người ký/chức danh. *Ảnh nên là PNG nền trong suốt, resize gần đúng cỡ hiển thị để bản in không bị viền mờ.*
3. **Ngưỡng báo giá NCC** (Settings → Technical → System Parameters): `attqc.min_purchase_rfq` — mặc định 5. Test nhanh thì hạ xuống 1–2.
4. **Danh mục**: nhập Hình thức vận chuyển, Thư viện điều khoản HĐ, Lý do thanh lý.
5. Muốn gửi **Zalo**: cài `att_zalo_connector`, kết nối Zalo OA; đối tác phải nhắn tin cho OA trước để có Zalo User ID.

---

## 4. FLOW BÁN — TỪNG BƯỚC

### Bước 1 — Tạo báo giá
Sales → Orders → New. Nhập KH, **hạn hiệu lực (Expiration)**, các dòng dịch vụ: điểm đi/đến, phương tiện, hình thức VC, mô tả hàng, đơn giá. Lưu → hệ thống đánh số `QT/2026/xxxxx`.

### Bước 2 — Yêu cầu duyệt giá
Bấm **[Yêu cầu duyệt giá]** → trạng thái *Chờ duyệt giá*, manager nhận thông báo.
> Chưa duyệt giá thì **không gửi được cho KH** — mọi kênh (Email/Zalo) đều chặn.

### Bước 3 — Manager duyệt
Manager mở báo giá → **[Duyệt giá]** (hoặc **[Trả về nháp]** kèm lý do để sales sửa).

### Bước 4 — Gửi báo giá cho KH
Bấm **[Gửi báo giá]** → popup chọn kênh:
- **Email**: mở form soạn mail với template Trang Huy, PDF báo giá đính kèm sẵn.
- **Zalo**: gửi 2 tin — tin chữ (số báo giá, tuyến, tổng tiền, hạn hiệu lực) + tin file PDF.

Muốn chỉnh cột hiển thị trên PDF: tab **"Cấu hình PDF báo giá"** ngay trên SO (tick/bỏ cột điểm đi, phương tiện, thuế...).

### Bước 5 — KH đồng ý
Bấm **[KH chốt giá]** → trạng thái *KH đã chốt*. (Filter "KH đã chốt (chưa tạo HĐ)" trên list để lọc.)

### Bước 6 — Tạo HĐNT
Bấm **[Tạo hợp đồng NT]** — chỉ manager, chỉ báo giá đã chốt, và **báo giá còn hạn hiệu lực**.
- KH **đã có HĐ đang hiệu lực** → hệ thống chặn, dùng **[Tạo phụ lục]** trên báo giá để thêm giá mới vào HĐ cũ.

### Bước 7 — Phụ lục & SO thực thi
Xem mục 6 & 7 bên dưới. Khi phụ lục đã duyệt/ký → **[Tạo SO thực thi]** → SO nháp giá khóa theo phụ lục, nằm ở menu **Sales → Hợp đồng NT → SO thực thi**; user kiểm số lượng thực tế từng đợt rồi Confirm bằng nút native.

> **Ngoại lệ duy nhất**: đơn lẻ B2C không qua hợp đồng — manager bấm **[Xác nhận đơn lẻ (B2C)]**.

---

## 5. FLOW MUA — TỪNG BƯỚC

### Bước 1 — Phát sinh nhu cầu thuê ngoài
Trên SO: dòng nào **chưa gán xe nhà** = phải thuê NCC. Bấm smart button **[Dòng thiếu xe → RFQ NCC]** → mở RFQ mới tự đổ đúng các dòng thiếu xe, **giá để trống** (không lộ giá bán cho NCC).

### Bước 2 — Nhân bản cho đủ NCC
RFQ lưu xong (số `QTM/2026/xxxxx/mã NCC`) → **Duplicate** cho từng NCC khác, **giữ nguyên SO nguồn** để được tính chung nhóm. Cần tối thiểu **5 báo giá cùng SO nguồn** (theo System Parameter).

### Bước 3 — Gửi yêu cầu báo giá
Bấm **[Gửi báo giá]** → chọn kênh **Email / Zalo / Gọi điện** (gọi điện tạo cuộc gọi VoIP hoặc lịch hẹn gọi). PDF gửi NCC có cột "Đơn giá chào" để trống cho NCC điền.

### Bước 4 — Nhập giá & chốt thầu
NCC phản hồi → nhập giá vào từng RFQ → so sánh → mở RFQ thắng bấm **[Chốt NCC thắng thầu]** (manager). Thiếu ngưỡng 5 báo giá → hệ thống chặn kèm hướng dẫn.

### Bước 5 — Tạo HĐNT NCC
Trên RFQ thắng bấm **[Tạo hợp đồng NT]**. Hệ thống chặn nếu: chưa chốt NCC · NCC đã có HĐ đang chạy (→ dùng **[Tạo phụ lục]**) · RFQ quá hạn chốt (Order Deadline) · nhóm tụt dưới ngưỡng.

### Bước 6 — Phụ lục & PO thực thi
Phụ lục mua kéo giá từ RFQ thắng → duyệt/ký → **[Tạo PO thực thi]**. PO tự kế thừa từ QTM: SO nguồn, điều khoản thanh toán, người mua, mã NCC, Source Document. PO nằm ở **Purchase → Hợp đồng NT → PO theo hợp đồng**, confirm bằng nút native.

> **Ngoại lệ**: thuê chuyến lẻ gấp — manager bấm **[Xác nhận mua lẻ (gấp)]** trên RFQ.
> Sửa tay giá PO lệch phụ lục → cảnh báo ngay trên dòng (nếu NCC đổi giá, làm phụ lục mới thay vì sửa tay).

---

## 6. HỢP ĐỒNG NGUYÊN TẮC

**Vòng đời**: Nháp → Chờ duyệt → Đang hiệu lực → (Chờ duyệt thanh lý) → Đã thanh lý / Đã hủy

| Thao tác | Nút | Ai làm |
|---|---|---|
| Gửi bản nháp cho đối tác (Email/Zalo/Gọi) | **Gửi bản nháp** | User |
| Trình duyệt hiệu lực | **Yêu cầu xác nhận** | User |
| Xác nhận hiệu lực + gửi bản ký | **Xác nhận hiệu lực** | **CEO** |
| Tạo PO ngay trên HĐ mua (không cần phụ lục) | **Tạo PO** | User |
| Thanh lý (bắt buộc chọn Lý do thanh lý trước) | **Yêu cầu thanh lý** → **Duyệt thanh lý** | User → **CEO** |

- Ngày hết hạn phải **sau** ngày hiệu lực — nhập sai hệ thống chặn.
- Hệ thống **tự cảnh báo HĐ sắp hết hạn trước 30 ngày** (cron hàng ngày).
- Smart buttons trên HĐ: xem Báo giá thuộc HĐ · Phụ lục · PO thực thi.

## 7. PHỤ LỤC — NGUỒN GIÁ DUY NHẤT

**Vòng đời**: Nháp → Gửi nháp → Yêu cầu duyệt → Duyệt (manager) → Gửi bản đã ký → Done

1. Tạo phụ lục từ HĐ (hoặc từ nút **[Tạo phụ lục]** trên báo giá đã chốt).
2. Bấm **[Nạp dòng từ báo giá]** — kéo 1-click toàn bộ dòng + giá từ SO báo giá / RFQ thắng. *Báo giá nguồn hết hạn → chặn.*
3. Tab **"Cấu hình PDF phụ lục"**: tick chọn dòng nào **in vào PDF** (độc lập với cờ "Tạo SO/PO"); tổng tiền trên bản in tính theo dòng được in.
4. Phụ lục bán có tab **Điều chỉnh giá dầu**: giá dầu DO tham chiếu + công thức điều chỉnh in vào PDF.
5. **[Duyệt phụ lục]** (manager) → phụ lục mới tự đánh dấu phụ lục cũ *"Đã thay thế"* — đây là flow **đổi giá**: không sửa phụ lục cũ, làm phụ lục mới.
6. **[Tạo SO thực thi]** / **[Tạo PO thực thi]** — mỗi đợt hàng một đơn, giá tự điền từ phụ lục.

**Ràng buộc ngày**: hết hạn PL > hiệu lực PL; hiệu lực PL phải **nằm trong thời hạn HĐ** (HĐ hết hạn → gia hạn HĐ trước); riêng hết hạn PL được vượt HĐ (phụ lục gia hạn hợp lệ).

## 8. GỬI CHỨNG TỪ & IN ẤN

- **Một popup gửi chung** cho Báo giá/RFQ/HĐNT/Phụ lục: Email · Zalo · Gọi điện (gọi điện chỉ chiều mua). Gửi kênh nào trạng thái chứng từ cũng chuyển như gửi email, có log trong chatter.
- **Menu Print thông minh**: giai đoạn báo giá chỉ thấy mẫu báo giá Trang Huy; đơn đã confirm/thực thi thấy mẫu native + **"Đơn đặt hàng vận chuyển (TH)"** (mẫu theo hợp đồng khung: số HĐ kèm theo, địa chỉ bốc-hạ, tiền bằng chữ, 2 khối ký).
- 5 mẫu PDF nhận diện Trang Huy: Báo giá bán · Yêu cầu báo giá NCC · HĐNT · Phụ lục · Đơn đặt hàng.

## 9. CÁC THÔNG BÁO CHẶN THƯỜNG GẶP

| Thông báo | Nguyên nhân | Cách xử lý |
|---|---|---|
| "Báo giá chưa được duyệt giá nội bộ..." | Gửi KH khi chưa duyệt | Bấm Yêu cầu duyệt giá → manager duyệt |
| "Cần tối thiểu 5 báo giá NCC..." | Chốt thầu khi nhóm chưa đủ RFQ | Duplicate RFQ cho thêm NCC (giữ SO nguồn) |
| "Báo giá đã hết hiệu lực từ..." | Tạo HĐ/nạp phụ lục từ báo giá quá hạn | Cập nhật hạn hiệu lực hoặc làm báo giá mới |
| "RFQ ... là báo giá mời thầu — không xác nhận trực tiếp" | Confirm RFQ không qua flow | Đi đúng flow chốt NCC → HĐ → PL → PO; gấp thì nhờ manager |
| "Phụ lục ... TRƯỚC ngày hiệu lực của hợp đồng" | Ngày PL nằm ngoài thời hạn HĐ | Sửa ngày PL hoặc gia hạn HĐ |
| "NCC ... đã có hợp đồng nguyên tắc đang hiệu lực" | Tạo HĐ trùng | Tạo phụ lục trên HĐ đang chạy |
| "Chỉ Quản lý Sale/Purchase mới được..." | Thiếu quyền | Nhờ manager hoặc xin cấp quyền |
| "Đối tác ... chưa liên kết Zalo" | Thiếu Zalo User ID | Đối tác nhắn tin cho OA Trang Huy trước |
