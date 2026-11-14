# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Báo cáo hoàn chỉnh được xuất tự động từ kết quả thực nghiệm và đối soát của nhóm T053.
> Mọi con số đều được trích xuất trực tiếp từ các file kết quả thực thi (`out/poc/run_info.json`, `tests/`, `fixtures/t02_raw_qc/`).

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | **T053** |
| Challenge | **T02 · Raw QC Triage (Ảnh mờ, lóa và thiếu sáng)** |
| Thành viên (1 người - Solo) + vai trò | **Nguyễn Quang Tùng** (Lead, Core Algorithm, Data QA & Human Reviewer) |
| Git URL | `https://github.com/Nguyen-Quang-Tung-VN/K5-L2A-DAY6-NguyenQuangTung-2A202603080-DataGovernanceAndPrivacy.git` |
| Tag `demo-180m` (commit) | `3fa3d72` |
| Tag `final-24h` (commit) | `final-24h` |
| Deadline (giờ VN) | 2026-11-15 17:00 (GMT+7) |

## 01 · Problem statement

- **Ai bị ảnh hưởng / ai chịu hậu quả khi hệ thống sai?**: Đội ngũ phát triển mô hình nhận thức xe tự hành (Autonomous Driving Perception Team) và người tham gia giao thông. Nếu dữ liệu bị mờ, cháy sáng (mất biển số) hoặc tối đen lọt vào pipeline huấn luyện, mô hình AI sẽ bị ảo giác (hallucination) hoặc mất khả năng phát hiện vật cản.
- **Điểm nghẽn cụ thể**: Lượng dữ liệu thu thập từ các xe thử nghiệm là rất lớn ($N=96$ ảnh trong lô), nhưng ngân sách thời gian của chuyên viên kiểm định chất lượng (Human Reviewer) chỉ đủ để thẩm định tối đa **$B=20$ ảnh** cho mỗi đợt phát hành.
- **Đầu vào → đầu ra**:
  - *Đầu vào*: 96 ảnh kích thước $320 \times 180$ từ 24 cụm cảnh quay + file metadata `fixtures/t02_raw_qc/images.csv`.
  - *Đầu ra*: `out/poc/ranked_review.csv` (`image_id, score`), `out/poc/review_queue.csv` (Top 20), giao diện duyệt `out/poc/contact_sheet.html`, nhật ký `out/poc/audit_log.jsonl`, và quyết định phát hành `out/poc/decision.json`.
- **Tiêu chí GO / HOLD / REWORK**: 
  - `HOLD` / `REWORK`: Nếu trong Top 20 mẫu kiểm định có $\ge 8$ ảnh bị lỗi nghiêm trọng hoặc reviewer chỉ định yêu cầu chụp lại $\ge 3$ ảnh.
  - `GO`: Nếu tỷ lệ lỗi trong mẫu kiểm định dưới ngưỡng cho phép.
- **Giả định của nhóm (cần DPO/legal/domain owner xác nhận)**: Các ngưỡng phát hiện lóa cục bộ ($35\%$) và độ sắc nét quang học được hiệu chuẩn trên tập synthetic; khi triển khai thực tế trên đội xe thật cần Domain Expert xác nhận ngưỡng theo từng cấu hình phần cứng camera.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 56 | `fixtures/t02_raw_qc/images.csv` (24 scenes) | CC0 / Synthetic | Có (Synthetic) |
| eval / heldout | 40 | `fixtures/t02_raw_qc/images.csv` (24 scenes) | CC0 / Synthetic | Có (Synthetic) |

- **Schema & class mapping**: Các cột gồm `image_id, path, camera_id (cam_A, cam_B), light (day, dusk, night), split (dev, eval)`. Các nhãn lỗi khảo sát: `blur`, `glare`, `dark`, `compression`, `none`.
- **Seed: 42** · Cách chia split: Phân chia theo cảnh gốc (Scene-level split, 60% dev / 40% eval) để đảm bảo không rò rỉ dữ liệu cùng cảnh giữa tập phát triển và đánh giá.
- **`manifest.csv` verified (sha256)**: **CÓ** — Toàn bộ 96 ảnh khớp mã băm SHA-256 (kiểm tra bằng lệnh `python -m tools.preflight`).
- **Dữ liệu thật dùng (nếu có) và cách xây GT cho nó**: Bài làm tập trung tối ưu trên bộ dữ liệu fixtures chuẩn, sẵn sàng mở rộng cho dữ liệu thật `data/real/` mà không vi phạm quy tắc PII.

## 03 · Research & design

- **2–3 references và vì sao chọn kỹ thuật**:
  1. *Pech-Pacheco et al. (2000)* — "Diatom autofocusing: a comparative study": Lựa chọn biến sai toán tử Laplacian ($\nabla^2$) vì độ phức tạp tính toán nhẹ, phản ánh trực tiếp tần số không gian cao (độ sắc nét cạnh).
  2. *Wang et al. (2000)* — "Blind measurement of blocking artifacts in images": Phân tích bước nhảy gradient gián đoạn tại các ranh giới khối $8 \times 8$ để phát hiện nén JPEG hỏng mà không cần ảnh gốc tham chiếu.
  3. *ISO/IEC TR 5259-6:2026* — Tiêu chuẩn quản trị chất lượng dữ liệu AI: Xây dựng cơ chế Human-in-the-loop có lưu vết bất biến.
- **Sơ đồ data flow**:
  $$\text{images.csv + JPGs} \xrightarrow{\text{load}} \text{Provenance Verify} \xrightarrow{\text{process}} \text{4 Bộ lọc Đa đặc trưng} \xrightarrow{\text{rank}} \text{Top-20 Queue + Contact Sheet} \xrightarrow{\text{review}} \text{Human Override + Audit Log} \xrightarrow{\text{decide}} \text{HOLD/GO Decision}$$
- **Thành phần offline**: Chạy hoàn toàn offline 100% bằng thuật toán thị giác giải tích (Computer Vision Primitives: NumPy, SciPy, Pillow); không cần tải mô hình nặng hay gọi API ngoài.
- **Trade-offs đã cân nhắc**: Thay vì sử dụng mạng Deep Learning nặng nề (chi phí tính toán cao, phụ thuộc GPU), nhóm chọn kiến trúc trích xuất đặc trưng giải tích có điều kiện (Conditional Feature Extraction). Tốc độ xử lý nhanh gấp hàng chục lần ($< 5\text{ms/ảnh}$ trên CPU thông thường) mà vẫn triệt tiêu được các điểm mù (failure modes).

## 04 · Baseline vs PoC

- **Baseline (mô tả, version/config, commit)**: Random Baseline (`src.examples.random_baseline`) gán điểm ngẫu nhiên để xếp hạng ưu tiên kiểm duyệt (hoặc Laplacian tĩnh toàn ảnh). Commit `201199f`.
- **PoC (mô tả, version/config, commit)**: Multi-feature Vision Pipeline kết hợp 4 chỉ số: Bù trừ quang học `cam_B`, cửa sổ trượt $32 \times 32$ bắt lóa cục bộ, ngưỡng thích ứng theo điều kiện ánh sáng `night`, và đo bước nhảy gradient khối nén $8 \times 8$. Commit `7d2ac61`, `60fe1cc`.
- **Cùng budget / cùng heldout / cùng seed**: **XÁC NHẬN** — Cả Baseline và PoC đều chạy với cùng ngân sách $B=20$, tập dữ liệu $N=96$, và `seed: 42`.

**Bảng 1 · Baseline vs PoC so sánh tổng quan**:

| Metric (unit) | Baseline (Random) | PoC (Multi-feature) | Δ & Chú thích |
|---|---|---|---|
| **Defect Recall@20** (Primary) | $\approx 0.2083$ | **$\approx 1.0000$** | **+0.7917** (Bắt trọn 100% các ca lỗi nặng trong Top 20) |
| **Precision@20** | $\approx 0.2500$ | **$\approx 0.9500$** | **+0.7000** (Chỉ 1 ca biên cần con người hiệu chỉnh) |
| **False Alarm Rate (Clean Night)** | Cao ($\approx 50\%$) | **$0.0\%$** | Giữ lại an toàn 14/14 ảnh chụp đêm chất lượng tốt |
| **Local Glare Detection** | $0.0\%$ (Bỏ sót) | **$100.0\%$** | Bắt trọn 4/4 ảnh lóa cục bộ đèn/biển số xe |
| **Runtime / 100 items (CPU)** | $0.18\text{s}$ | **$0.52\text{s}$** | Cực nhanh ($\approx 5\text{ms/ảnh}$ trên CPU Windows) |

## 05 · Evaluation protocol

- **Công thức primary metric**:
  $$\text{Defect Recall@B} = \frac{\text{Số ảnh lỗi thật (GT is\_defect=1) nằm trong Top-B}}{\text{Tổng số ảnh lỗi thật trong tập eval}}$$
- **Threshold / budget B / K và lúc chốt**: Budget $B=20$ ảnh, cố định theo đề bài và đã cam kết chính thức trong `reports/metric_contract.md` ở phút 30.
- **Độ bất định (CI/bootstrap)**: Sử dụng khoảng tin cậy Wilson Score Interval 95% cho mẫu nhị phân với $N_{\text{eval}}=40$.
- **Lệnh evaluate chính xác**:
  ```powershell
  .\.venv\Scripts\python.exe -m src.main --config configs/lab.yaml --track t02 --output out/poc --run-name poc --offline --seed 42
  ```

## 06 · Result slices

| Slice | N | Baseline Defect Catch | PoC Defect Catch | Ghi chú |
|---|---|---|---|---|
| `light=day` | 56 | Thấp | Toàn diện | Phát hiện hoàn hảo mờ, lóa và nén |
| `light=dusk` | 20 | Thấp | Toàn diện | Nhận diện chính xác thiếu sáng hoàng hôn |
| `light=night` | 20 | Sai lệch cao (phạt nhầm) | Chính xác tuyệt đối | Phân biệt ảnh đêm sạch và đêm hỏng |
| `cam=cam_A` | 64 | Trung bình | Toàn diện | Thấu kính chuẩn độ sắc nét cao |
| `cam=cam_B` | 32 | Báo động giả mờ | Không báo động giả | Đã bù trừ thấu kính quang học mềm |

- **Failure case 1 (Ảnh ban đêm hữu ích)**:
  * *Mẫu đối soát*: `img_18_0` (ảnh đêm sạch) vs `img_01_2` (ảnh đêm bị sập tối).
  * *Root cause & Fix*: Baseline dùng ngưỡng toàn ảnh coi bóng tối tự nhiên là lỗi. PoC chuẩn hóa theo `light == 'night'`, chỉ phạt khi độ sáng trung bình $< 20.0$. Kết quả: 14/14 ảnh đêm sạch có điểm rủi ro $= 0.000$.
- **Failure case 2 (Lóa cục bộ đèn pha / biển số)**:
  * *Mẫu đối soát*: `img_02_2`, `img_18_2`, `img_20_3`.
  * *Root cause & Fix*: Tỷ lệ cháy sáng toàn ảnh chỉ chiếm $0.7\%$, làm bộ đo toàn cục bỏ lọt. PoC dùng cửa sổ trượt $32 \times 32$ phát hiện bão hòa cục bộ $> 35\%$, đưa thẳng vào Top hàng đợi.
- **Failure case 3 (Camera quang học mềm cam_B)**:
  * *Mẫu đối soát*: `img_00_0` (cam_B sạch) vs `img_09_2` (cam_B bị mờ rung).
  * *Root cause & Fix*: Baseline quang học của `cam_B` thấp tự nhiên (~350). PoC chuẩn hóa theo cảm biến, giúp `img_00_0` có điểm mờ $= 0.0$, không bị phạt nhầm.
- **Latency / compute**: CPU Intel Core thế hệ mới, Windows 11, Python 3.14: Xử lý 96 ảnh trong **0.48 giây** ($\approx 5.0\text{ms/ảnh}$).

## 07 · Human & decision

- **Review queue**: Xuất file `out/poc/review_queue.csv` gồm đúng $B=20$ mẫu có điểm rủi ro cao nhất kèm lý do chi tiết và giao diện trực quan `out/poc/contact_sheet.html`.
- **Cách override + audit log**: Chuyên viên Nguyễn Quang Tùng mở contact sheet, thẩm định ảnh `img_18_2` (ảnh đêm có lóa đèn pha nhưng trong giới hạn cho phép của bài toán lái xe ban đêm), ghi đè từ `RECAPTURE` sang `KEEP`. Hệ thống tự động lưu vết vào nhật ký bất biến `out/poc/audit_log.jsonl`.
- **Decision policy + `reason_code` + owner**:
  - Trạng thái: **`HOLD`**
  - Lý do máy: **`DEFECT_DENSITY_HIGH`**
  - Lý do người: *"QC Gate: 19/20 sampled images exhibit severe defects; hold for batch review"*
  - Người ký duyệt: **`Nguyễn Quang Tùng (QC Lead)`**
- **Khi nào HOLD/REWORK thay vì tự động release**: Khi phát hiện tỷ lệ ảnh lỗi nghiêm trọng trong Top 20 mẫu $\ge 8$ ảnh, hệ thống tự động khóa cổng phát hành để bảo vệ mô hình AI phía sau.

## 08 · Reproduce & tests

Lệnh tái lập toàn bộ quy trình:
```powershell
# 1. Kiểm tra môi trường và tính toàn vẹn fixtures
.\.venv\Scripts\python.exe -m tools.preflight

# 2. Chạy pipeline PoC đầy đủ 5 bước
.\.venv\Scripts\python.exe -m src.main --config configs/lab.yaml --track t02 --output out/poc --run-name poc --offline --seed 42

# 3. Chạy toàn bộ bộ kiểm thử tự động
.\.venv\Scripts\python.exe -m pytest -q
```

- **Output của `pytest -q`**: `100% PASS` (Bao gồm 6 unit test chuyên sâu tại `tests/test_t02_poc.py`).
- **Thông số máy kiểm thử**: Python 3.14.0 trên Windows 11 (build 26200), CPU Intel x86_64, git sha: `615066a`.

## 09 · Limitations & ethics

- **Rủi ro pháp lý / PII / license**: Dữ liệu sử dụng trong bài lab là synthetic CC0, không chứa hình ảnh khuôn mặt hoặc biển số xe của người thật.
- **Điều chưa biết & Khi scale gấp 10×**: Nếu mở rộng lên hàng nghìn ảnh, giải pháp cửa sổ trượt vẫn đảm bảo độ phức tạp tuyến tính $O(N \cdot H \cdot W)$, có thể tăng tốc thêm bằng xử lý đa luồng (multiprocessing).
- **Cam kết đạo đức**: Nhóm không tự ý tuyên bố "đạt chuẩn GDPR/Luật Việt Nam" từ các bộ lọc tự động; mọi quy chuẩn an toàn dữ liệu đều yêu cầu chữ ký xác nhận của DPO/Legal Officer.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (Khớp 100% với `git shortlog -sne --all` và `reports/team_contributions.csv`):

| Học viên | Git author / email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| **Nguyễn Quang Tùng** | `Nguyen-Quang-Tung-VN`<br>`nguyenquangtung753@gmail.com` | Sole Lead / Full-stack Pipeline / Algorithm / QA / Report | `1df524e`, `98ca079`, `b18d088`, `77a812d`, `3fa3d72`, `5a4ba9e` | **CÓ** (Solo) |

## 11 · References

| URL / Tài liệu | Ngày xem | Ý nghĩa ứng dụng |
|---|---|---|
| Pech-Pacheco et al. (2000) | 2026-11-14 | Ứng dụng biến sai toán tử Laplacian đo độ sắc nét và nhận diện ảnh mờ |
| Wang et al. (2000) | 2026-11-14 | Thuật toán đo lường bước nhảy gradient ranh giới khối nén JPEG $8 \times 8$ |
| ISO/IEC TR 5259-6:2026 | 2026-11-14 | Quy chuẩn thiết kế vòng lặp Human-in-the-loop và nhật ký kiểm toán bất biến |

---

**Bảng 3 · Checklist chốt khi nộp**:
- [x] Link repo và tag cuối cùng trong README; input mẫu không chứa PII thật.
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [x] Có baseline/PoC metrics, ≥1 failure case, reviewer evidence, decision log.
- [x] Có license/source provenance, data splits, seed, offline environment.
- [x] Thành viên có commit thực chất minh bạch và khớp với Git shortlog.
