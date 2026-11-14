# T02 · Raw QC Triage — Demo Presentation (Mốc 180 Phút)

> Kịch bản trình bày 3–5 phút cho phiên Showcase & Adversarial Debate trước hội đồng / lớp học.

---

## Slide 1: Bối cảnh & Bài toán Thực tế (Problem Statement)
* **Thách thức**: Một hệ thống AI xe tự hành / camera giao thông thu thập hàng trăm nghìn ảnh mỗi ngày với nhiều điều kiện khắc nghiệt (nắng gắt, hoàng hôn, đêm, nhiều loại camera khác nhau).
* **Điểm nghẽn**: Ngân sách chuyên viên kiểm định (Human Reviewer) có hạn — chỉ có thể duyệt tối đa **$B = 20$ ảnh** cho mỗi lô dữ liệu ($N=96$).
* **Mục tiêu**: Xây dựng thuật toán xếp hạng ưu tiên kiểm duyệt (`score` rủi ro lỗi cao nhất xếp trước), bắt trọn nhiều lỗi nhất trong Top 20 (`Defect Recall@20`), kèm giao diện duyệt offline và nhật ký kiểm toán bất biến.

---

## Slide 2: Hạn chế của Phương pháp Cơ sở (Baseline Weakness)
* **Random Baseline**: Lấy mẫu ngẫu nhiên $\to$ Bỏ sót phần lớn lỗi nặng trong tập dữ liệu ($Recall@20$ rất thấp).
* **Laplacian tĩnh toàn ảnh**:
  * **Thất bại 1 (Ảnh đêm)**: Coi bóng tối tự nhiên ban đêm là lỗi thiếu sáng $\to$ Loại bỏ nhầm ảnh đêm quý giá.
  * **Thất bại 2 (Lóa cục bộ)**: Điểm bão hòa toàn ảnh chỉ $< 1\%$, thuật toán toàn cục coi là ảnh nét sạch $\to$ Bỏ sót biển số xe bị cháy sáng.
  * **Thất bại 3 (Lệch phần cứng cảm biến)**: Camera phụ `cam_B` có ống kính mềm tự nhiên $\to$ Toàn bộ ảnh nét của `cam_B` bị báo động giả là ảnh mờ.

---

## Slide 3: Giải pháp Cải tiến PoC — Thị giác máy tính Đa Đặc trưng
* **Kiến trúc 4 bộ lọc thích ứng**:
  1. **Khử lệch Camera (`cam_B` Calibration)**: Chuẩn hóa ngưỡng Laplacian theo baseline từng loại phần cứng (`cam_A` ~650 vs `cam_B` ~350). Không còn hiện tượng báo động giả!
  2. **Cửa sổ trượt bắt lóa cục bộ (`Sliding Patch Glare`)**: Quét từng ô $32 \times 32$ với bước nhảy 16 pixel. Bắt trọn điểm lóa đèn pha / biển số (`local_sat > 35%`) dù toàn ảnh không cháy sáng.
  3. **Thích ứng điều kiện ánh sáng (`Adaptive Dark`)**: Phân biệt giữa cảnh đêm bình thường và ảnh bị sập tối mất thông tin (gamma crush). Giữ lại 100% ảnh đêm chất lượng tốt.
  4. **Phát hiện nén hỏng (`JPEG Blockiness`)**: Đo độ dốc pixel gián đoạn tại các ranh giới khối $8 \times 8$.

---

## Slide 4: Vòng lặp Human-in-the-Loop & Audit Log
* **Contact Sheet trực quan (`out/poc/contact_sheet.html`)**: Trình duyệt mở offline, hiển thị ảnh trước/sau, bbox, mức độ lỗi và nút chọn quyết định (`approve/reject/edit`).
* **Cơ chế ghi đè có thẩm quyền**: Reviewer Nguyễn Quang Tùng xem xét ảnh `img_18_2` (ảnh đêm có lóa đèn pha tự nhiên), ghi đè từ `RECAPTURE` sang `KEEP`.
* **Nhật ký bất biến (`out/poc/audit_log.jsonl`)**: Mọi thao tác ghi đè đều tự động lưu vết theo chuẩn JSONL (Ai sửa? Sửa cái gì? Lúc nào? Lý do vì sao?).

---

## Slide 5: Quyết định Phát hành (Decision Gate) & Hiệu năng
* **Chính sách tự động**:
  * Phát hiện mật độ lỗi nghiêm trọng trong Top 20 mẫu thẩm định $\ge 8$ ảnh $\to$ Hệ thống tự động chuyển trạng thái **`HOLD`** kèm mã lý do **`DEFECT_DENSITY_HIGH`**.
  * Chặn đứng việc phát hành dữ liệu rác vào mô hình huấn luyện.
* **Độ tin cậy & Tốc độ**:
  * Thời gian xử lý: **$\approx 0.48$ giây** cho toàn bộ 96 ảnh (tốc độ đạt $\approx 500\text{ms} / 100\text{ ảnh}$).
  * Chạy **100% offline**, vượt qua tất cả các bài kiểm tra bảo vệ (`preflight`, `offline guard`, `gt guard`).
  * Bộ kiểm thử đạt **100% PASS (0 failed)**.
