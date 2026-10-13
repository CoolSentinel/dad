# Đặc tả monitor cho MUGVN Hackathon 2026 (MongoDB × Datadog)

Tài liệu này chốt **cái gì cần monitor, ngưỡng bao nhiêu, xử lý thế nào** cho hệ thống giám sát dựa trên dataset DAD. Mọi con số đều có căn cứ trong các notebook:

- `00`: hiểu dataset;
- `02`: data mining, chọn bộ phát hiện;
- `03`: kiểm chứng ngưỡng và so với nghiên cứu khác.

Đề bài và thể lệ: https://mini-hackathon-sep-2026.mugvn.com/ (đọc ngày 12/10/2026).

## 1. Câu chuyện của bài thi

> Data center CITIC (Đại học A Coruña, Tây Ban Nha) từng sập vì cảm biến cấu hình sai gửi nhiệt độ sai tới hệ thống làm mát, khiến máy chủ quá nhiệt và hỏng phần cứng. Chúng tôi xây hệ thống **phát hiện, điều tra và xử lý** đúng loại sự cố đó: cảm biến im lặng, gửi dồn bất thường, hoặc gửi giá trị bị sửa. Dữ liệu được phát lại từ dataset công khai DAD (Vigoya et al., Sensors 2020).

Cách câu chuyện này đáp ứng các tiêu chí chấm:

| Tiêu chí (trọng số) | Ăn điểm ở đâu |
|---|---|
| **Sáng tạo (30%)** | Sự cố thật và hậu quả vật lý (quá nhiệt). Phát hiện "trừ một số nguyên độ" của tấn công sửa giá trị. Chứng minh vì sao chọn quy tắc hành vi thay vì ML (notebook 03, mục 2: ML kiểu bài báo về F1 = 0 với ngày chưa thấy) |
| **Kỹ thuật (30%)** | Time Series Collection + TTL, phát hiện bằng `$setWindowFields`, Change Streams; Datadog metrics + logs + APM liên kết qua `incident_id` và `trace_id` |
| **Tác động (30%)** | Trọn vẹn phát hiện → điều tra (loại sự cố, mức độ, phạm vi) → xử lý (tự động hoặc có người duyệt) → chứng minh đã ổn bằng dữ liệu (3 chu kỳ sạch) |
| **Trình bày (10%)** | Video demo 3 sự cố ở tốc độ ×60, dashboard một màn hình, README + notebook giải thích dataset |

## 2. Checklist yêu cầu bắt buộc

| Yêu cầu | Cách đáp ứng |
|---|---|
| MongoDB là nền tảng dữ liệu vận hành chính | Mọi telemetry, trạng thái thiết bị, incident, hành động khắc phục nằm trong MongoDB |
| Mô hình dữ liệu hợp lý | Mục 4: `telemetry` / `telemetry_hist` (time series), `devices`, `inrows`, `mqtt_sessions`, `incidents`, `actions`, `gt_*`; dữ liệu ban đầu có sẵn trong `data/mongo/` |
| Aggregation Pipeline phục vụ bài toán | D1, D2, D4, bất biến vật lý và điều tra đều là pipeline (mục 4.2) |
| *(khuyến khích)* Time Series, window functions, `expireAfterSeconds`, Change Streams | Có cả bốn |
| Datadog: ≥ 1 dashboard | Mục 5.3 |
| Datadog: ≥ 1 monitor gắn với sự cố có ý nghĩa | Mục 5.2: 6 monitor chính |
| Datadog: ≥ 1 năng lực bổ sung | **Log Management + APM/Distributed Tracing**, thêm 1 monitor **Anomaly Detection** |
| Kết nối metrics, logs, traces | Mọi log và trace mang `inrow`, `client_id`, `incident_id`, `dd.trace_id` |
| Khai báo dataset ngoài, công cụ AI, thành phần có sẵn | Mục 9 |

## 3. Kiến trúc

```
DAD PCAP ──► replayer (Python, tua ×60) ──MQTT QoS1──► Mosquitto ──► ingest (Python + ddtrace)
                 ▲  thêm seq, device_ts                                  │ ghi
                 │  nhận lệnh dc/{inrow}/cmd                              ▼
            remediator ◄── webhook Datadog / API ◄── incidents ◄── detector worker ◄── MongoDB Atlas
                 │                                     (Change Stream)   (aggregation mỗi P giây)
                 └──► MongoDB `actions`  ───────────────────────────────►  DogStatsD + logs + APM ──► Datadog
```

- **Replayer:** đọc PCAP, phát lại đúng thứ tự và khoảng cách (chia 60). Bản tin là JSON `{clientId, seq, value, device_ts}`; topic `dc/{inrow}/{sensor}/temp`.
- **Ingest:** nhận MQTT, ghi `telemetry`, đẩy metric và log, mỗi bản tin một span APM.
- **Detector worker:** mỗi `P` giây chạy các pipeline ở mục 4.2, ghi `node_slots` và mở/cập nhật `incidents`, đẩy metric phát hiện.
- **Remediator:** nghe Change Stream trên `incidents` và webhook từ Datadog; thực hiện hành động ở mục 6.
- **Tham số hoá chu kỳ `P`**: 300 giây khi chạy thời gian thật, 5 giây khi tua ×60. **Mọi ngưỡng thời gian tính theo bội số của `P`**.

## 4. MongoDB

### 4.1 Collections

Dữ liệu ban đầu xuất từ dataset gốc bằng `src/dad_export.py`, nạp bằng `src/dad_mongo_load.py`; chi tiết từng trường ở notebook 04.

| Collection | Loại | Số document ban đầu | Trường chính | Vòng đời / index |
|---|---|---|---|---|
| `telemetry_hist` | **Time Series** (`timeField: ts`, `metaField: meta`, `granularity: minutes`) | 32.288 | `ts`, `meta {site, inrow, sensor, clientId, ip}`, `value`, `seq`, `conn`, `puback_ms`, `src {day, frame}` | **không TTL** (dữ liệu 2019, TTL sẽ xoá ngay); index `{meta.clientId, ts}`, `{meta.inrow, ts}` |
| `telemetry` | **Time Series** (`granularity: seconds` cho replay ×60; `minutes` nếu chạy thời gian thật) | 0 (replay ghi vào) | như trên, thời gian đã dời về hiện tại | `expireAfterSeconds: 604800` |
| `devices` | thường, có validator | 16 | `sensor`, `valid_range_c`, `baseline_init`, `profile_dad`, `profile_real_paper`, `quality`, `rate_limited` | — |
| `inrows` | thường | 4 | `ip`, `netbotz`, `clients`, `ntp_seen_in_capture` | — |
| `mqtt_sessions` | thường | 112 | `conn`, `keepalive_s`, `n_publish`, `n_unacked`, `puback_p99_ms` | index `{clientId, connect_ts}` |
| `traffic_daily` | thường | 35 | số gói theo ngày × IP × loại | — |
| `incidents` | thường, có validator | 0 | `inrow`, `status` (`open`/`ack`/`mitigated`/`resolved`), `kinds[]`, `evidence {lost, extra, drop_c, sensors}`, `detected_at`, `resolved_at` | index `{status, inrow}`; **Change Stream** cho remediator |
| `actions` | thường, có validator | 0 | `incident_id`, `action`, `by`, `at`, `result` | — |
| `gt_labels`, `gt_incidents` | thường | 544, 11 | nhãn gốc và 11 cửa sổ sự cố kèm kết quả điều tra | chỉ dùng để chấm, **không** cho bộ phát hiện đọc |
| `detector_config`, `demo_scenarios` | thường | 1, 4 | ngưỡng; đoạn dữ liệu cho demo | — |

### 4.2 Pipeline phát hiện

Code ở `src/dad_mongo_pipelines.py`. **Đã chạy thật trên MongoDB 8.0.4 với toàn bộ `telemetry_hist`** (notebook 04): D1 = 64, D2 = 248, D4 theo InRow = 85 slot, D4 theo cảm biến = 497, vật lý = 0, dải = 0; tất cả **trùng khớp** pandas. Pipeline điều tra khớp cả 11 sự cố. Mỗi pipeline chạy dưới 1 giây.

**D1 im lặng và D2 gửi dồn**, theo từng cảm biến (`conn` nằm ngoài `meta`):

```js
db.telemetry.aggregate([
  { $setWindowFields: { partitionBy: "$meta.clientId", sortBy: { ts: 1 },
      output: { prevTs: { $shift: { output: "$ts", by: -1 } }, prevConn: { $shift: { output: "$conn", by: -1 } } } } },
  { $match: { prevTs: { $ne: null } } },
  { $set: { gapP: { $divide: [{ $dateDiff: { startDate: "$prevTs", endDate: "$ts", unit: "millisecond" } }, P * 1000] },
            sameConn: { $eq: ["$conn", "$prevConn"] } } },
  { $match: { $or: [ { gapP: { $gt: 1.5 } },                        // D1 (bắt khi bản tin kế tiếp tới)
                     { gapP: { $lt: 0.8 }, sameConn: true } ] } }   // D2
])
```

**D1 live** (`silence_now`): mỗi chu kỳ, lấy lần nhận cuối của từng cảm biến, tính `(now − lastTs) / P`, gom theo InRow. Đã thử ở tốc độ ×60: InRow 13 báo 4/4 cảm biến im lúc 1,6P, các InRow khác không báo.

**D4 giá trị thấp bất thường:** baseline = trung vị 288 bản tin trước của từng cảm biến; báo khi ≥ 3/6 chu kỳ gần nhất lệch dưới −0,8 °C. Pipeline `d4_node` / `d4_sensor` (`$median` trong `$setWindowFields` cần MongoDB ≥ 7.0). **Bắt buộc chặn `null` bằng `$isNumber`**: trong MQL `null` nhỏ hơn mọi số, thiếu điều kiện này D4 báo 176 slot thay vì 85. Chạy **hai mức**:
- theo từng cảm biến → **warning** (sớm hơn, trễ 3–25 phút, 1 báo giả/tuần);
- gộp theo InRow → **critical** (trễ 10–28 phút, 0 báo giả).

**INV bất biến vật lý:** trong cùng slot, `TFEU < TFSU < TAS < TAR`. Vi phạm là critical (0 vi phạm trong DAD bình thường).

**RANGE dải giá trị** (theo dữ liệu thật trong bài báo, nới 2 °C):

| Cảm biến | Dải hợp lệ (°C) |
|---|---|
| TAS | 15,9–23,2 |
| TAR | 23,1–30,1 |
| TFEU | 6,1–16,3 |
| TFSU | 10,8–19,8 |

**Điều tra** (chạy khi mở incident, ghi vào `incidents.evidence`):
- `lost` = Σ(round(gap/P) − 1) với các gap > 1,5P;
- `extra` = số bản tin có gap < 0,8P;
- `drop_c` = mode(round(−dev)) trên các chu kỳ lệch;
- `sensors` = số `clientId` bị ảnh hưởng (4/4 nghĩa là cả node, 1/4 nghĩa là nghi hỏng cảm biến);
- `kind` = chặn gói / chèn gói / sửa giá trị (notebook 03, mục 5).

### 4.3 Bẫy khi replay
- **Làm nóng baseline:** D4 cần 288 bản tin của mỗi cảm biến. Nạp trước **thứ Hai** (ngày sạch), rồi mới replay đoạn có sự cố. `dad_mongo_load.load_scenario()` làm sẵn việc này (dời thời gian về hiện tại, nén ×60) và đã thử: D2 báo sau 1,5 giây, D4 sau khoảng 15 giây, D1 live sau 8 giây.
- **TTL xoá dữ liệu lịch sử:** chép dữ liệu 2019 vào collection có `expireAfterSeconds` thì bị xoá ngay (đã thử: 500 document mất sau 2 giây). Dữ liệu lịch sử để ở `telemetry_hist` (không TTL); chỉ dữ liệu đã dời thời gian mới vào `telemetry`.
- Lưu mọi thời điểm theo **UTC**. File DAD chia theo giờ Tây Ban Nha, và ngày 27/10/2019 có đổi giờ.
- **Bỏ qua khung reconnect 00:00–00:02** mỗi ngày: có reconnect, RST, và vài bản tin của phiên cũ không được ACK.

## 5. Datadog

### 5.1 Metrics (DogStatsD)

Tag chung: `env`, `site`, `inrow`, `sensor`, `client_id`.

| Metric | Loại | Nguồn | Ý nghĩa |
|---|---|---|---|
| `dad.temp` | gauge | ingest | nhiệt độ từng bản tin |
| `dad.temp.dev` | gauge | ingest | value − baseline |
| `dad.msg.count` | count | ingest | số bản tin nhận |
| `dad.msg.gap_periods` | gauge | ingest | khoảng cách tới bản tin trước **tính theo chu kỳ** (bình thường = 1,0); không phụ thuộc tốc độ tua |
| `dad.node.silence_periods` | gauge | worker | (now − last_seen) / P, lấy max theo InRow |
| `dad.node.burst_count` | count | worker | số bản tin có gap < 0,8P |
| `dad.node.neg_count6` | gauge | worker | đặc trưng D4 theo InRow |
| `dad.sensor.neg_count6` | gauge | worker | đặc trưng D4 theo cảm biến |
| `dad.invariant.violations` | count | worker | vi phạm TFEU < TFSU < TAS < TAR |
| `dad.range.violations` | count | worker | vi phạm RANGE |
| `dad.ingest.lag_seconds` | gauge | ingest | thời điểm ghi MongoDB − `device_ts` |
| `dad.ingest.dropped` | count | ingest | bản tin bị lọc khi node đang `rate_limited` |
| `mqtt.puback_latency_ms` | distribution | replayer | baseline từ DAD: p50 0,17 ms, p99 0,6 ms |
| `dad.incident.open` | gauge | worker | số incident đang mở, theo `kind` |

### 5.2 Monitors (chốt)

| # | Monitor | Truy vấn (gợi ý, cần thử lại trên Datadog) | Ngưỡng | Mức | Căn cứ |
|---|---|---|---|---|---|
| M1 | **Node im lặng** | `max(last_1m):max:dad.node.silence_periods{*} by {inrow}` | warn > 1,2; **alert > 1,5** | P2 | 02 §1.4, §5; bắt 5/5 lần chặn gói, 0 báo giả |
| M2 | **Gửi dồn / chèn bản tin** | `sum(last_2m):sum:dad.node.burst_count{*} by {inrow}.as_count()` | alert ≥ 2 | P2 | 02 §3.1; bắt 3/3, trễ 1–1,5 phút |
| M3 | **Giá trị thấp bất thường (node)** | `max(last_1m):max:dad.node.neg_count6{*} by {inrow}` | warn ≥ 2; **alert ≥ 3** | **P1, cần người duyệt** | 02 §5, 03 §3; bắt 6/6, 0 báo giả |
| M4 | Giá trị thấp bất thường (cảm biến) | `max(last_1m):max:dad.sensor.neg_count6{*} by {client_id}` | alert ≥ 3 | P3 (cảnh báo sớm) | 03 §4 |
| M5 | **Vi phạm vật lý** | `sum(last_5m):sum:dad.invariant.violations{*} by {inrow}.as_count()` + `dad.range.violations` | > 0 | P1 | 02 §2, §7.2 |
| M6 | **Ingest chậm / pipeline lỗi** | `avg(last_5m):avg:dad.ingest.lag_seconds{*}` hoặc log `service:ingest status:error` | lag > 2P; lỗi > 0 | P2 | để phân biệt sự cố hạ tầng với sự cố dữ liệu |
| M7 | *(năng lực bổ sung)* **Anomaly Detection** | `avg(last_15m):anomalies(sum:dad.msg.count{*}.as_count(), 'basic', 2)` | theo mô hình Datadog | P3 | lưu lượng bản tin toàn site lệch khỏi mẫu |
| M8 | **Khí cấp ngoài vùng ASHRAE** | `min(last_30m):avg:dad.temp{sensor:tas} by {inrow}` < 18 hoặc `max(...)` > 27 | ngoài 18–27 °C → warn; ngoài 15–32 °C → alert | P1/P2 | ASHRAE TC 9.9; `NGHIEP_VU_GIAM_SAT.md` §2.1 |

- Nội dung cảnh báo nên chứa `{{inrow.name}}`, link dashboard lọc sẵn theo InRow, và `incident_id`. Worker gửi Datadog **Event** khi mở/đóng incident, để event hiện trên dashboard.
- **Cảnh báo gộp theo tủ thành sự cố**, không bắn theo từng bản tin. Trên DAD, bắn thô cho tới 41 cảnh báo trong 10 phút ("lụt" theo EEMUA 191); gộp lại còn 2,6 sự cố/ngày. Danh mục cảnh báo đầy đủ (nguyên nhân, hậu quả, hành động, thời gian phản ứng, điều kiện phục hồi) ở `NGHIEP_VU_GIAM_SAT.md` §4.3.
- **Không** dùng làm monitor: thay đổi `keepalive` theo ngày, độ lệch của InRow 13 so với InRow 15/23, `msgid`. Đây là dấu vết của bộ sinh dữ liệu (02 §1.2, §7.3), không phải tín hiệu tấn công.

### 5.3 Dashboard (một màn hình)

| Hàng | Widget |
|---|---|
| 1. Tổng quan | trạng thái M1–M6 · số incident đang mở · MTTD / MTTR gần nhất · số bản tin mỗi phút |
| 2. Nhiệt độ | `dad.temp` theo InRow, 4 đường mỗi cảm biến · overlay Event incident |
| 3. Phát hiện | `silence_periods`, `burst_count`, `neg_count6` theo InRow, có vạch ngưỡng |
| 4. Điều tra | bảng incident (kind, lost, extra, drop_c, sensors) · log stream lọc `incident_id` · top trace chậm của ingest |
| 5. Hạ tầng | `ingest.lag_seconds` · `mqtt.puback_latency_ms` p99 · lỗi log theo service |

### 5.4 Logs và APM
- Log JSON từ `replayer`, `ingest`, `detector`, `remediator`, có trường `inrow`, `client_id`, `incident_id`, `rule`, `dd.trace_id`, `dd.span_id`.
- `ddtrace`: span `mqtt.receive` → `mongo.insert` → `detector.evaluate` → `remediator.action`. Từ một cảnh báo có thể nhảy sang log, sang trace của đúng bản tin.

## 6. Xử lý sự cố (runbook)

| Loại (phát hiện bởi) | Kết luận | Hành động | Tự động? | Xác nhận đã ổn |
|---|---|---|---|---|
| **Chặn gói** (M1, cả 4 cảm biến cùng im) | node mất kết nối hoặc gói bị chặn | gửi `reconnect` tới `dc/{inrow}/cmd`; đánh dấu khoảng thiếu dữ liệu; nội suy có gắn cờ | tự động; báo người nếu kéo dài > 3P | bản tin quay lại, `silence_periods` < 1,2 trong 3 chu kỳ |
| **Chèn gói** (M2) | node gửi lặp hoặc bị chèn | bật `rate_limited` cho node (ingest lọc bản tin đến sớm hơn 0,8P) | tự động | `burst_count` = 0 trong 3 chu kỳ; `ingest.dropped` ngừng tăng |
| **Sửa giá trị** (M3, 4/4 cảm biến) | dữ liệu node không đáng tin | đặt `quality=suspect`; **ngừng dùng InRow này cho điều khiển làm mát**; dùng giá trị cuối đáng tin + cảnh báo vận hành | **cần người duyệt** (D4 có thể báo giả ngoài DAD) | `neg_count6` về 0 trong 3 chu kỳ → `quality=ok`, đóng incident |
| **Một cảm biến lệch** (M4 / M5, chỉ 1/4) | nghi hỏng cảm biến | gắn cờ cảm biến, mở ticket bảo trì | tự động | — |
| **Ingest chậm** (M6) | sự cố hạ tầng, không phải dữ liệu | khởi động lại consumer / scale | người | lag < 2P |

Mỗi incident ghi `detected_at`, `ack_at`, `mitigated_at`, `resolved_at`, từ đó tính **MTTD** và **MTTR**.

## 7. Kịch bản demo (video khoảng 5 phút, tua ×60)

| Bước | Dữ liệu replay | Diễn ra trong demo | Chứng minh |
|---|---|---|---|
| 0 | nạp trước thứ Hai | dashboard xanh, baseline sẵn sàng | hệ thống bình thường |
| 1 | thứ Năm 03:00–03:30 | M2 báo sau khoảng 1–2 giây → remediator tự bật rate-limit → đóng sau 3 chu kỳ sạch | phát hiện + xử lý tự động |
| 2 | thứ Tư 03:45–06:30 | M3 báo sau khoảng 15 giây → điều tra hiện "4/4 cảm biến, bị trừ khoảng 2 °C" → người duyệt → `quality=suspect` → D4 về 0 → đóng | điều tra + người trong vòng lặp |
| 3 | thứ Sáu 03:20–05:05 | M1 báo cả 4 cảm biến **thành một** incident → `reconnect` → bản tin quay lại | gộp cảnh báo theo node |
| 4 *(tuỳ chọn)* | dừng consumer ingest 20 giây | M6 báo; log/trace chỉ ra lỗi | phân biệt hạ tầng và dữ liệu |
| Kết | — | so incident với `ground_truth`: bắt đủ, trễ bao nhiêu, MTTR | "chứng minh bằng dữ liệu" |

Kết quả kỳ vọng tính trên DAD (03 §6): ở ×60, D2 báo sau ≈ 1 giây, D1 sau ≈ 7,5 giây, D4 sau ≈ 15 giây; sự cố thứ Tư kéo dài khoảng 2 phút.

## 8. Lịch và việc cần làm

- **Đăng ký đội: hạn 23:59 ngày 12/10/2026.** Đăng ký sau sẽ không nhận được link nộp bài.
- Workshop: Datadog 12/10, MongoDB 13/10 (12:00–13:00).
- **Build 17/10–31/10.** Thể lệ yêu cầu **phần giải pháp cốt lõi** (replayer, ingest, detector, remediator, dashboard/monitor) phải được làm trong thời gian này. Phần phân tích dữ liệu trong repo này là chuẩn bị trước, cần khai báo rõ.
- **Nộp bài: 23:59 ngày 31/10/2026.** Không được sửa repo sau hạn nộp.

## 9. Khai báo khi nộp bài

- **Dataset:** DAD, L. Vigoya, D. Fernandez, V. Carneiro, F. Cacheda, *Annotated Dataset for Anomaly Detection in a Data Center with IoT Sensors*, Sensors 2020, 20(13), 3745, doi:10.3390/s20133745. Dữ liệu bán tổng hợp; repo gốc không có file LICENSE. Hình trích từ bài báo theo giấy phép CC BY 4.0.
- **Thành phần có sẵn:** phần phân tích trong `monitoring/` (notebook 00–03, `src/`) được làm **trước** thời gian build.
- **Công cụ AI:** ghi rõ công cụ đã dùng cho phân tích và code.

## 10. Giới hạn cần nói thẳng khi thuyết trình

- DAD có 7 ngày, một kẻ tấn công (InRow 13) và 6 cửa sổ có nhãn. Ngưỡng có căn cứ và đã kiểm tra trên ngày chưa thấy (03 §3.2), nhưng chưa chứng minh hiệu năng tổng quát.
- Dữ liệu thật dao động mạnh hơn và các cảm biến ít tương quan hơn DAD (02 §7.2). Ngoài thực tế cần chạy D4 theo từng cảm biến, và cân nhắc K = 4, T = 0,6 (ổn định hơn, chậm hơn khoảng 7 phút).
- Interception không có nhãn gốc, nên kết quả "D1 bắt đủ" là hiển nhiên theo cách định nghĩa cửa sổ.
