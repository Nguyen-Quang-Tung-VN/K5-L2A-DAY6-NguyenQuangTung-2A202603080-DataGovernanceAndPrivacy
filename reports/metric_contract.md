# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | **T02 · Raw QC Triage (Ảnh mờ, lóa và thiếu sáng)** |
| Primary metric (tên đúng như evaluator in ra) | `Defect Recall@B` (với budget $B=20$) |
| Tăng tốt hay giảm tốt? | `higher` (càng cao càng tốt, tiệm cận 1.0) |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | `image` (từng ảnh riêng biệt) |
| Công thức + numerator / denominator | $\text{Defect Recall@B} = \frac{\text{Numerator: Số ảnh lỗi thật sự (GT is\_defect=1) nằm trong Top-B}}{\text{Denominator: Tổng số ảnh lỗi thật sự (GT is\_defect=1) trong tập eval}}$ |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | Khớp chính xác theo khóa `image_id` (`pred.image_id.isin(gt.image_id)`), sắp xếp giảm dần theo cột `score` |
| Candidate pool cố định | 96 ảnh synthetic trong `fixtures/t02_raw_qc/images.csv` (được xác thực sha256 qua `manifest.csv`) |
| Review budget B / K | $B = 20$ (số lượng ảnh nghi lỗi tối đa được trích xuất cho chuyên gia review) |
| Seed | `42` (cố định trong toàn bộ các lệnh chạy `--seed 42`) |
| Threshold policy (chọn trên dev như thế nào) | Chỉ khảo sát phân phối và căn chỉnh các ngưỡng (độ sắc nét Laplacian, độ sáng trung bình, tỷ lệ bão hòa pixel) trên tập `split == 'dev'` (56 ảnh); tuyệt đối không nhìn hoặc tối ưu ngưỡng trên tập `eval` |
| Eval split (không dùng để tune) | 40 ảnh thuộc `split == 'eval'` (được phân chia theo cụm cảnh gốc 24 scenes để chống data leakage) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | 1. `False alarm in top-B`: Tỷ lệ ảnh sạch bị đưa nhầm vào top-B ($\frac{\text{clean in top-B}}{\text{total clean}}$)<br>2. `Miss rate`: Tỷ lệ ảnh lỗi bị bỏ sót ngoài top-B ($1 - \text{Recall@B}$) |
| Slices sẽ báo cáo (≥2) | 1. `light` (`day`, `dusk`, `night`) — đánh giá độ nhạy trước điều kiện sáng tối<br>2. `camera_id` (`cam_A`, `cam_B`) — đánh giá hiện tượng lệch phân phối do cảm biến quang học<br>3. `defect_type` (`blur`, `glare`, `dark`, `compression`) — phân rã theo từng dạng khuyết tật |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson Score Interval 95% cho tỷ lệ nhị phân với $N=40$ ($N_{\text{eval}}$) |
| Ngày giờ chốt + người chốt | 2026-11-14 15:45 (GMT+7) · Nguyen Quang Tung (QC Lead) |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.
