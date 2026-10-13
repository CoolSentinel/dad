# Hướng triển khai: từ dataset tới một hệ thống vận hành thật

Tài liệu cho đội chưa có kinh nghiệm vận hành (operations). Đọc theo thứ tự:
1. đổi cách nghĩ về bài toán;
2. ngoài đời người ta làm việc này thế nào;
3. bài toán của đội;
4. kế hoạch build từng ngày.

Chi tiết kỹ thuật (monitor, ngưỡng, pipeline) ở `MONITOR_SPEC.md`.

---

## 1. Đổi cách nghĩ: đây không phải bài phân tích dữ liệu

Có dataset trong tay thì dễ nghĩ tới việc "train mô hình rồi báo accuracy". Bài thi này **không chấm việc đó**. Đề yêu cầu *"trình diễn trọn vẹn một tình huống vận hành, từ lúc phát sinh đến lúc được xử lý"*.

| Cách nghĩ sai | Cách nghĩ đúng |
|---|---|
| Dataset là thứ để phân tích | Dataset là **nguồn phát lại** để giả lập 16 cảm biến đang chạy thật |
| Kết quả là một con số (accuracy, F1) | Kết quả là một **sự cố được xử lý xong**, có bằng chứng bằng dữ liệu |
| Càng nhiều mô hình càng tốt | Ít quy tắc, **giải thích được**, mỗi cảnh báo dẫn tới một hành động cụ thể |
| Làm xong phân tích rồi mới làm hệ thống | Làm **một đường đi xuyên suốt** (cảm biến → MongoDB → Datadog → cảnh báo) trước, rồi mới làm dày từng khúc |

Phần phân tích trong `notebooks/` đã xong và chỉ là **nguyên liệu**. Hai tuần build là để dựng **hệ thống chạy được**.

## 2. Ngoài đời, việc này được làm thế nào

### 2.1 Ai làm gì
Trong một data center thật có hai nhóm trông hệ thống, và bài của đội phục vụ cả hai:

| Vai trò | Họ trông cái gì | Họ cần gì từ hệ thống của đội |
|---|---|---|
| **Vận hành cơ điện / phòng máy** (facility, NOC) | nhiệt độ, làm mát, điện. Dùng DCIM/BMS; NetBotz trong Hình 1 của bài báo chính là loại thiết bị này | biết **tủ nào** đang có vấn đề, **nghiêm trọng cỡ nào**, **làm gì tiếp** |
| **Kỹ sư hệ thống** (SRE, IT ops) | đường đi dữ liệu: cảm biến → broker → ingest → database | biết lỗi nằm ở **hạ tầng dữ liệu** hay ở **thiết bị**, và khoanh vùng nhanh bằng metrics, logs, traces |

### 2.2 Vòng đời một sự cố

Đây là nghiệp vụ cốt lõi, và cũng chính là 3 bước đề thi chấm:

```
Phát hiện ─► Phân loại ─► Điều tra ─► Xử lý ─► Xác nhận ổn ─► Rút kinh nghiệm
(monitor)   (mức độ,    (nguyên    (tự động  (dữ liệu    (postmortem:
            ai trực)    nhân,      hoặc có   chứng minh  MTTD, MTTR,
                        phạm vi)   người     đã bình     sửa ngưỡng)
                                   duyệt)    thường)
```

**Các khái niệm cần nắm**, sẽ dùng khi thuyết trình:
- **SLI / SLO**: chỉ số đo được và mục tiêu cho chỉ số đó. Ví dụ: "99% bản tin cảm biến tới MongoDB trong 2 chu kỳ".
- **Mức độ (severity)**: P1 là nguy hiểm, phải xử lý ngay; P2 là cần xử lý trong ca trực; P3 là theo dõi. Không phải cảnh báo nào cũng gọi người dậy lúc 3 giờ sáng.
- **Alert fatigue**: báo giả nhiều thì người trực bỏ qua cả cảnh báo thật. Vì thế notebook 02 và 03 tốn công đưa báo giả về 0.
- **Runbook**: tài liệu "thấy cảnh báo X thì làm Y". Làm được tự động thì để máy làm; rủi ro cao thì cần người duyệt.
- **MTTD / MTTR**: thời gian từ lúc sự cố bắt đầu tới lúc phát hiện / tới lúc khắc phục. Đây là con số để chứng minh giá trị của hệ thống.
- **Postmortem**: tổng kết sau sự cố: chuyện gì xảy ra, phát hiện sau bao lâu, sửa gì để lần sau tốt hơn.

### 2.3 Sự cố "thật" trong bài của đội trông thế nào

| Tình huống ngoài đời | Dữ liệu DAD nào mô phỏng | Ai phải biết | Hành động |
|---|---|---|---|
| Cảm biến hoặc đường truyền chết, tủ "im lặng" | interception (chặn gói) | phòng máy + SRE | kết nối lại; nếu kéo dài thì cử người kiểm tra tủ |
| Thiết bị lỗi firmware hoặc bị chèn dữ liệu, gửi dồn dập | duplication (chèn gói) | SRE | giới hạn tốc độ, lọc trùng ở ingest |
| **Dữ liệu nhiệt độ bị sai hoặc bị sửa** (chính sự cố ở CITIC) | modification (sửa giá trị) | phòng máy, **khẩn** | **không cho hệ thống làm mát dùng dữ liệu đó**, người xác nhận, kiểm tra tại chỗ |
| Hệ thống giám sát tự nó bị chậm hoặc lỗi | không có trong DAD; đội tự tạo (tắt ingest) | SRE | khởi động lại, scale; **không** đổ lỗi cho thiết bị |

Tình huống cuối không có trong dataset nhưng **rất nên có**: nó chứng minh hệ thống phân biệt được "thiết bị hỏng" với "hệ thống giám sát hỏng". Đây là năng lực mà ban giám khảo bên Datadog sẽ để ý.

## 3. Bài toán của đội (chốt một câu)

> **"Hệ thống phát hiện, điều tra và cách ly dữ liệu cảm biến làm mát bất thường trong data center, trước khi hệ thống làm mát hành động sai."**

- **Người dùng:** kỹ sư vận hành phòng máy và kỹ sư hệ thống đang trực.
- **Giá trị:** tránh lặp lại sự cố CITIC (cảm biến sai → làm mát sai → quá nhiệt → sập). Đo bằng MTTD, MTTR, và số sự cố bắt được trên tổng số sự cố.
- **Phạm vi (không làm quá tay):** 4 tủ làm mát, 16 cảm biến, 3 loại sự cố thiết bị + 1 sự cố hạ tầng. **Không** làm điều khiển làm mát thật; chỉ cần cờ `quality=suspect` và một dòng log "đã ngừng dùng dữ liệu tủ 13 cho điều khiển".

User story để định hướng khi build:
1. *Là kỹ sư phòng máy, tôi muốn được báo khi một tủ ngừng gửi dữ liệu quá 1,5 chu kỳ, để kịp kiểm tra trước khi nhiệt độ thật vượt ngưỡng.*
2. *Là kỹ sư phòng máy, khi dữ liệu một tủ có dấu hiệu bị sửa, tôi muốn thấy bằng chứng (4/4 cảm biến, bị trừ khoảng 2 °C) và một nút duyệt cách ly.*
3. *Là SRE, tôi muốn từ một cảnh báo nhảy thẳng tới log và trace liên quan, để biết lỗi ở ingest hay ở thiết bị.*
4. *Là trưởng nhóm, tôi muốn xem sau mỗi sự cố: phát hiện sau bao lâu, xử lý mất bao lâu, ai làm gì.*

## 4. Kiến trúc tối thiểu

```
[replayer] ──MQTT──► [Mosquitto] ──► [ingest] ──► MongoDB Atlas ◄── [detector worker]
  phát lại DAD                         │ metrics/logs/traces        │ incidents (Change Stream)
  tua ×60                              ▼                            ▼
                                    Datadog ──── monitor ──webhook──► [remediator] ──lệnh──► replayer
```

- **Một ngôn ngữ cho tất cả:** Python, vì phân tích đã viết bằng Python (`src/` dùng lại được) và `ddtrace`, `pymongo`, `paho-mqtt` đều sẵn.
- **Chạy bằng `docker compose`:** gồm Mosquitto, replayer, ingest, detector, remediator, Datadog Agent. MongoDB dùng **Atlas**. Ngày đầu kiểm tra cluster miễn phí có đủ ba thứ cần dùng không: Time Series, `$median` (cần MongoDB ≥ 7.0) và Change Streams. Thiếu thì dùng gói trả phí nhỏ nhất hoặc credit cuộc thi (nếu có).
- **Dữ liệu ban đầu:** `python src/dad_mongo_load.py` nạp 9 collection có sẵn trong `data/mongo/`.

## 5. Kế hoạch build 17/10 – 31/10

Nguyên tắc: **cuối mỗi mốc phải có thứ chạy được để demo**, dù còn thô.

| Ngày | Mục tiêu | Xong khi |
|---|---|---|
| **Trước 17/10** | Đăng ký đội (hạn 12/10); xem 2 buổi workshop; chuẩn bị email công việc cho Datadog trial; đọc notebook 00 và `MONITOR_SPEC.md` | cả đội hiểu dataset và 3 loại sự cố |
| **17–18/10** | **Đường đi xuyên suốt:** tạo Atlas + Datadog trial; nạp `data/mongo`; replayer đọc `telemetry_hist`, phát MQTT tua ×60; ingest ghi vào `telemetry` và gửi metric `dad.temp` | thấy đường nhiệt độ chạy trên Datadog **và** document mới trong MongoDB |
| **19–21/10** | **Phát hiện:** detector worker chạy `dad_mongo_pipelines.py` mỗi chu kỳ, đẩy `dad.node.*`; tạo monitor M1, M2, M3, M6 | replay thứ Tư thì M3 đỏ; replay thứ Năm thì M2 đỏ |
| **22–24/10** | **Sự cố và xử lý:** ghi `incidents` + `evidence`; remediator nghe Change Stream và webhook Datadog; làm 3 hành động: reconnect, rate-limit, quarantine (cần duyệt); đóng sự cố sau 3 chu kỳ sạch | một sự cố đi trọn vòng: open → mitigated → resolved, có MTTD và MTTR |
| **25–27/10** | **Quan sát và điều tra:** dashboard một màn hình; log JSON có `incident_id` và `dd.trace_id`; APM trace ingest → Mongo; sự cố hạ tầng (tắt ingest) | từ cảnh báo bấm sang log và trace của đúng bản tin |
| **28–29/10** | **Demo:** kịch bản 5 phút (`MONITOR_SPEC.md` mục 7), quay video, so kết quả với `gt_incidents` | video lần 1 |
| **30–31/10** | README (cài đặt, chạy, kiểm thử), slide, khai báo dataset/AI/phần làm trước; **không** để lộ khoá bí mật; dự phòng lỗi | nộp trước 23:59 ngày 31/10 |

**Nếu thiếu thời gian, cắt theo thứ tự:** M4 → M7 → sự cố hạ tầng → giao diện duyệt (thay bằng gọi API). **Không cắt** vòng phát hiện → điều tra → xử lý → chứng minh, vì đó là 30% điểm "Tác động".

## 6. Chia việc (1–3 người)

| Người | Phụ trách | Đầu ra |
|---|---|---|
| A: dữ liệu | replayer, ingest, MongoDB (collections, pipeline, Change Stream) | dữ liệu chảy đúng, pipeline chạy mỗi chu kỳ |
| B: quan sát | Datadog: metric, monitor, dashboard, log, APM, webhook | dashboard + monitor + liên kết log/trace |
| C: sự cố và demo | detector → incidents, remediator, runbook, kịch bản demo, slide, video | một sự cố đi trọn vòng, video, slide |

Đội 1 người: làm theo đúng thứ tự ở mục 5, giữ phạm vi **3 monitor** (M1, M2, M3) và **1 sự cố trình diễn chính** (sửa giá trị thứ Tư).

## 7. Quyết định cần chốt ngay ngày đầu

| Câu hỏi | Đề xuất |
|---|---|
| Tốc độ replay | ×60 (P = 5 giây); mọi ngưỡng tính theo bội số P |
| MQTT broker | Mosquitto trong docker compose; không cần cloud |
| Detector chạy đâu | worker Python gọi Aggregation Pipeline mỗi P giây; MongoDB làm phần tính toán |
| Duyệt cách ly | API `POST /incidents/{id}/approve` (thêm trang web nhỏ nếu còn thời gian) |
| Demo truy cập được | chạy cục bộ và quay video; nếu cần link thì đẩy lên một VM nhỏ |

## 8. Rủi ro hay gặp

| Rủi ro | Cách tránh |
|---|---|
| Datadog trial có hạn, kích hoạt trong thời gian build | tạo tài khoản ngay 17/10; chụp dashboard và monitor sớm làm bằng chứng |
| Dữ liệu 2019 bị TTL xoá | dữ liệu gốc để `telemetry_hist`; replayer ghi thời gian **hiện tại** vào `telemetry` (notebook 04, mục 3.1) |
| D4 không báo khi demo | phải phát lại **thứ Hai làm nóng baseline** trước (notebook 03, mục 6) |
| Pipeline báo giả vì so sánh với `null` | dùng đúng `src/dad_mongo_pipelines.py` (đã có `$isNumber`) |
| Lộ chuỗi kết nối hoặc API key | dùng `.env`, thêm vào `.gitignore`; kiểm tra video trước khi nộp |
| Làm quá nhiều, không xong vòng sự cố | ưu tiên mục 5; cắt theo danh sách ở cuối mục 5 |
| Không giải thích được phần AI làm | mỗi người tự chạy lại notebook 00 và 04; khai báo công cụ AI trong bài nộp |

## 9. Câu chuyện khi thuyết trình (khoảng 5 phút)

1. **Vấn đề (30 giây):** sự cố CITIC: cảm biến sai → làm mát sai → quá nhiệt → sập.
2. **Dữ liệu (30 giây):** dataset DAD; dữ liệu đã được kiểm tra kỹ (notebook 00–04); chỉ ra lỗi rò nhãn của nghiên cứu trước (notebook 03).
3. **Kiến trúc (45 giây):** sơ đồ mục 4; vì sao dùng Time Series, Change Streams, Aggregation; vì sao dùng quy tắc thay vì ML.
4. **Demo (2,5 phút):** sửa giá trị → phát hiện sau khoảng 15 giây → điều tra (4/4 cảm biến, bị trừ khoảng 2 °C) → người duyệt cách ly → hệ thống trở lại bình thường, có MTTR. Thêm nhanh chèn gói (tự xử lý) và sự cố hạ tầng.
5. **Kết quả và giới hạn (45 giây):** bắt 11/11 sự cố, 0 báo giả trên DAD; nói thẳng giới hạn (dữ liệu bán tổng hợp, một kẻ tấn công) và hướng mở rộng.
