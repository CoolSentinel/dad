# Mô hình dữ liệu cho hệ thống giám sát

Kiến trúc đã chốt (xem `CLAUDE.md` ở gốc repo): một service Python nghe broker MQTT, ghi MongoDB (`telemetry` time series, `latest` và `incidents` là collection thường), gửi metric Datadog có tag `inrow`, `sensor`.

**Mọi object mẫu dưới đây được sinh từ đúng một frame (hoặc một nhóm frame) trong `data/`** bằng script [`src/tao_mau_du_lieu.py`](src/tao_mau_du_lieu.py). Script đọc thẳng file PCAP và so khớp từng giá trị với dòng CSV cùng frame; lệch là dừng. Bản đầy đủ ở [`samples/`](samples/). Mỗi object có trường `src` (file + frame) để mở ra kiểm.

Service Python gồm 3 khâu; tài liệu chia mục theo đúng ranh giới input/output của từng khâu:

| Khâu | Chạy khi | Input | Output | Mục |
|---|---|---|---|---|
| **A. Ingest** | mỗi bản tin | (1) bản tin MQTT | (2) `telemetry`, (3) `latest`, metric Datadog | A |
| **B. Phát hiện** | mỗi chu kỳ | `telemetry`, `latest` | (4) `incidents` | B |
| C. Phản ứng | khi `incidents` đổi (change stream) | `incidents` | cảnh báo, xử lý | chưa thiết kế |

```
                 ┌──────────── A. INGEST (mỗi bản tin) ────────────┐
(1) bản tin MQTT ─┤ tách tag inrow/sensor ─► (2) telemetry          │
                 │                         ─► (3) latest            │
                 │                         ─► Datadog dad.temp{…}   │
                 └──────────────────────────────────────────────────┘
                 ┌──────────── B. PHÁT HIỆN (mỗi chu kỳ) ──────────┐
(2), (3) ────────┤ độ tươi, bản tin đến sớm, lệch âm kéo dài ─► (4) incidents ──change stream──► C
                 └──────────────────────────────────────────────────┘
```

Tự kiểm một mẫu bất kỳ (chạy ở thư mục gốc repo):
```bash
python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap 2707   # in frame + dòng CSV
python monitoring/src/tao_mau_du_lieu.py                                              # sinh lại toàn bộ mẫu
```

---

# A. Ingest: input và output

## (1) Bản tin MQTT: input của ingest

### Trong dữ liệu gốc

| Trường | Ở đâu trong gói | Ví dụ (frame 2707, thứ Tư) |
|---|---|---|
| topic | MQTT PUBLISH | `IoT` (mọi cảm biến dùng chung) |
| payload | MQTT PUBLISH | `"18.02"` (chữ, °C) |
| qos | MQTT header | `1` |
| msgid | MQTT PUBLISH | `51` |
| IP nguồn, cổng nguồn | IP, TCP | `10.6.56.41:49152` |
| thời điểm nhận | thời gian gói (đồng hồ broker) | `2019-10-23T02:10:07.155Z` |
| clientId | **chỉ có ở gói CONNECT** của kết nối đó | `133` (frame 105, cùng file) |

Dòng CSV cùng frame: `2707;10.6.56.41;49152;133;51;1`.

### Khi phát lại vào hệ thống (đề xuất)

Topic phân cấp để subscriber biết ngay tủ và cảm biến; payload JSON mang giá trị, số thứ tự và thời điểm gốc:

```json
{
  "topic": "dc/citic/inrow13/TAS",
  "payload": { "value": 18.02, "seq": 51, "ts": "2019-10-23T02:10:07.155Z" },
  "qos": 1
}
```
Subscriber nghe `dc/citic/+/+`. Nguồn: frame 2707 ở trên (tủ 13 = IP `10.6.56.41`; `133` có chữ số cuối 3 = TAS).

---

## (2) `telemetry`: output của ingest (time series collection)

```javascript
db.createCollection("telemetry", {
  timeseries: { timeField: "ts", metaField: "meta", granularity: "minutes" }
  // ngoài đời thêm expireAfterSeconds (TTL); KHÔNG đặt khi nạp DAD vì dữ liệu năm 2019 sẽ bị xoá ngay
})
db.telemetry.createIndex({ "meta.inrow": 1, "meta.sensor": 1, ts: 1 })
db.telemetry.createIndex({ "src.file": 1, "src.frame": 1 })
```

| Trường | Kiểu | Ý nghĩa | Lấy từ |
|---|---|---|---|
| `ts` | Date (UTC, mili giây) | thời điểm broker nhận | thời gian gói PUBLISH |
| `ts_us` | Int64 | cùng thời điểm, **micro giây**, đúng bằng thời gian ghi trong file PCAP | thời gian gói PUBLISH |
| `meta.inrow` | int | tủ: 13, 15, 23, 25 | topic (gốc: IP nguồn) |
| `meta.sensor` | string | `TFEU`, `TFSU`, `TAS`, `TAR` | topic (gốc: chữ số cuối clientId) |
| `meta.clientId` | string | mã cảm biến, ví dụ `"133"` | gói CONNECT |
| `value` | double | nhiệt độ °C | payload |
| `seq` | int | số thứ tự bản tin trong phiên (`msgid`) | payload / MQTT |
| `conn` | string | `ip:cổng` của phiên | IP, TCP. **Chỉ có khi phát lại DAD**; ngoài đời subscriber không thấy IP. Thay bằng: `seq` về 1 nghĩa là phiên mới |
| `src` | object | `{file, frame}` để truy về gói gốc | chỉ có khi phát lại DAD |

**Không lưu nhãn** (`label`) trong `telemetry`: nhãn chỉ dùng để chấm, không được lọt vào đầu vào của bộ phát hiện. Time series collection không cho sửa `value` sau khi ghi (chỉ sửa được `meta`).

Mẫu (3 trong [`samples/telemetry.json`](samples/telemetry.json)):

| Tình huống | ts (UTC) | meta | value | seq | src |
|---|---|---|---|---|---|
| bình thường | 2019-10-20T22:10:02.753Z | 15 / TAS / 153 | 20.27 | 3 | `binh_thuong/…_mon.pcap` frame **217** |
| sửa giá trị | 2019-10-23T02:10:07.155Z | 13 / TAS / 133 | 18.02 | 51 | `bat_thuong/…_wed.pcap` frame **2707** |
| chèn bản tin | 2019-10-24T01:06:37.218Z | 13 / TFEU / 131 | 9.08 | 39 | `bat_thuong/…_thu.pcap` frame **2102** |

```json
{
  "ts": { "$date": "2019-10-23T02:10:07.155Z" },
  "ts_us": 1571796607155520,
  "meta": { "inrow": 13, "sensor": "TAS", "clientId": "133" },
  "value": 18.02,
  "seq": 51,
  "conn": "10.6.56.41:49152",
  "src": { "file": "data/bat_thuong/capture_1910230000_wed.pcap", "frame": 2707 }
}
```

---

## (3) `latest`: output của ingest (một document cho mỗi cảm biến)

Ingest cập nhật (upsert theo `_id`) mỗi khi nhận bản tin. Dùng cho: độ tươi (bây giờ − `ts`), khoảng cách tới bản tin trước (`gap_s`), và trạng thái hiện tại trên dashboard. Bản nạp sẵn chứa trạng thái sau bản tin cuối cùng của tuần (16 document).

| Trường | Ý nghĩa |
|---|---|
| `_id` | clientId |
| `inrow`, `sensor` | tủ, loại cảm biến |
| `ts`, `ts_us`, `value`, `seq`, `conn` | bản tin mới nhất |
| `gap_s`, `gap_P` | khoảng cách tới bản tin trước của cùng cảm biến, theo giây (6 chữ số thập phân) và theo chu kỳ P = 300,1 s |
| `src`, `prev_src` | frame của bản tin này và bản tin trước |

Mẫu ([`samples/latest.json`](samples/latest.json), trạng thái ngay sau bản tin ghi ở `src`):

| Tình huống | `_id` | value | gap_s | gap_P | src ← prev_src |
|---|---|---|---|---|---|
| bình thường | 153 | 20.27 | 300.101986 | 1.0 | mon **217** ← 165 |
| ngay sau khoảng hở (chặn gói, thứ Ba 00:30) | 131 | 12.00 | 900.102142 | 2.9993 | tue **488** ← 386 |
| bản tin đến sớm (chèn, thứ Năm 03:06:37) | 131 | 9.08 | 91.101102 | 0.3036 | thu **2102** ← 2059 |

---

# B. Phát hiện: output

Khâu này **không** do ingest tạo ra. Nó chạy theo chu kỳ, đọc `telemetry` và `latest`, áp các quy tắc D1, D2, D4 (xem báo cáo; không dùng nhãn), gộp cảnh báo cùng tủ cách nhau dưới 20 phút thành **một sự cố**, và chỉ ghi khi có sự cố. Trên DAD: **18 sự cố**, đều ở InRow 13, phủ đủ 11 cửa sổ sự cố chuẩn, không có sự cố nào ngoài cửa sổ.

## (4) `incidents`: output của khâu phát hiện (collection thường, nghe bằng change stream)

| Trường | Ý nghĩa |
|---|---|
| `_id` | `inrow<n>-<thời điểm phát hiện UTC>-<loại đầu tiên>` |
| `inrow` | tủ (một sự cố = một tủ) |
| `kinds` | loại sự cố: `mat_ban_tin` (D1), `chen_ban_tin` (D2), `sua_gia_tri` (D4) |
| `rules` | quy tắc đã báo: `D1`, `D2`, `D4` |
| `status` | `open`, `resolved` |
| `detected_at`, `detected_us` | cảnh báo đầu tiên. Truy ngược được về bản tin gốc: D2 = đúng `ts_us` của bản tin đến sớm; D1 = bản tin cuối trước khoảng hở + 1,5 P; D4 = mốc cuối của slot 5 phút |
| `last_alarm_at`, `last_alarm_us` | cảnh báo cuối cùng của sự cố |
| `n_alarms` | số cảnh báo thô đã gộp |
| `evidence.sensors` | số cảm biến của tủ có dữ liệu trong sự cố |
| `evidence.ban_tin_mat` | số bản tin mất (khoảng hở > 1,5 P thuộc sự cố này) |
| `evidence.ban_tin_den_som` | số bản tin đến sớm < 0,8 P cùng kết nối |
| `evidence.slot_lech_am`, `evidence.muc_tru_C` | số slot có trung bình (giá trị − baseline) < −0,8 °C; mức bị trừ hay gặp nhất (°C) |
| `src_frames` | tối đa 40 frame làm bằng chứng (bản tin sau khoảng hở, bản tin đến sớm, các bản tin của slot lệch âm đầu tiên) |

Tổng trên 18 sự cố: **180 bản tin mất**, **248 bản tin đến sớm**, đúng bằng số đếm trực tiếp từ PCAP.

Mẫu ([`samples/incidents.json`](samples/incidents.json)):

| Sự cố | detected_at (UTC) | quy tắc | bằng chứng | frame bằng chứng (đầu) |
|---|---|---|---|---|
| mất bản tin, thứ Ba 00:15 | 2019-10-21T22:22:33.225Z | D1 | 4 cảm biến, mất 8 bản tin | tue 488, 485, 479, 481 |
| sửa giá trị, thứ Tư 04:10 | 2019-10-23T02:25:00.000Z (sau 3 slot lệch âm, trễ 14,9 phút) | D4 | 17 slot lệch âm, trừ 2 °C | wed **2707**, 2708, 2711, 2716 |
| chèn bản tin, thứ Năm 03:06 | 2019-10-24T01:06:37.217Z (= bản tin frame 2095, cảm biến 133) | D2, D4 | 56 bản tin đến sớm, 4 slot lệch âm, trừ 2 °C | thu 2102, 2116, 2121… |
| node ngừng gửi, đêm thứ Năm | 2019-10-24T21:11:26.674Z (= bản tin `msgid` 288 lúc 21:03:56 + 1,5 P) | D1 | mất 40 bản tin (10 / cảm biến) | fri 161, 167, 173, 179 (bản tin đầu phiên thứ Sáu) |

```json
{
  "_id": "inrow13-20191023T022500Z-sua_gia_tri",
  "inrow": 13, "kinds": ["sua_gia_tri"], "rules": ["D4"], "status": "resolved",
  "detected_at": { "$date": "2019-10-23T02:25:00.000Z" }, "detected_us": 1571797500000000,
  "last_alarm_at": { "$date": "2019-10-23T04:10:00.000Z" }, "last_alarm_us": 1571803800000000,
  "n_alarms": 22,
  "evidence": { "sensors": 4, "ban_tin_mat": 0, "ban_tin_den_som": 0, "slot_lech_am": 17, "muc_tru_C": 2 },
  "src_frames": [ { "file": "data/bat_thuong/capture_1910230000_wed.pcap", "frame": 2708 }, "…" ]
}
```

---

# C. Đẩy sang Datadog

[`src/day_datadog.py`](src/day_datadog.py) đọc `telemetry` từ MongoDB và gửi metric qua API v2 (`POST /api/v2/series`).

| Metric (gauge) | Giá trị | Tag |
|---|---|---|
| `dad.temp` | `value` của bản tin | `inrow`, `sensor` (chữ thường), `client_id`, `source:dad_replay` |
| `dad.gap_p` | khoảng cách tới bản tin trước của cùng cảm biến / P | như trên |

- **Phát lại với thời gian dời về hiện tại:** Datadog không nhận điểm cũ quá 1 giờ hay sớm quá 10 phút ([Submit metrics](https://docs.datadoghq.com/api/latest/metrics/submit-metrics.md)). Thời điểm phát lại = `t0 + (ts_us − ts_us đầu tiên) // (speed × 10⁶)`, số nguyên giây.
- **Không để mất điểm do trùng giây:** Datadog lưu theo giây, nên script dừng nếu tốc độ phát lại làm hai bản tin của cùng cảm biến rơi vào cùng một giây.
- Mỗi điểm được ghi vào **sổ gửi** `data/datadog_out/journal.ndjson.gz` kèm `src` (file, frame) gốc.
- Toàn tuần: 32.288 document → **64.560 điểm** (32.288 `dad.temp` + 32.272 `dad.gap_p`; bản tin đầu tiên của mỗi cảm biến chưa có khoảng cách).

---

# D. Kiểm tra dữ liệu khớp tuyệt đối

[`src/kiem_tra_du_lieu.py`](src/kiem_tra_du_lieu.py) đọc PCAP bằng **bộ giải mã viết tay** (pcap / Ethernet / IPv4 / TCP / MQTT, không dùng scapy), độc lập với bộ xuất, rồi đối chiếu:

| Nhóm | Đối chiếu |
|---|---|
| A | PCAP ⇄ CSV nhãn: số gói = số dòng; mọi PUBLISH khớp frame, IP, cổng, clientId, msgid |
| B | PCAP ⇄ `telemetry`: đủ 32.288, không thừa, không trùng; từng bản tin khớp `ts_us`, `ts`, `value`, `seq`, `meta`, `conn`; không chứa nhãn |
| C | PCAP ⇄ `latest`: bản tin cuối và khoảng cách tới bản tin trước của từng cảm biến |
| D | PCAP ⇄ `incidents`: bằng chứng của từng sự cố tính lại từ PCAP (baseline tính lại độc lập); thời điểm phát hiện truy ngược về đúng bản tin; phủ đủ 11 cửa sổ chuẩn (đối chiếu nhãn CSV), 0 sự cố ngoài cửa sổ |
| E | `telemetry` ⇄ Datadog: từng điểm trong sổ gửi và trong payload khớp bản tin gốc (metric, tag, thời điểm phát lại, giá trị); không trùng giây; mỗi payload < 512.000 byte |
| F | (tuỳ chọn, `--datadog`) đọc lại từ Datadog và so với sổ gửi; cần `DD_API_KEY`, `DD_APP_KEY` |

Đã thử cố tình làm sai: sửa một giá trị 0,01 °C trong MongoDB, xoá một document, sửa một điểm trong sổ gửi. Cả ba đều bị bắt.

---

## Chạy toàn bộ (từ thư mục gốc repo)

```bash
# 0. MongoDB tự host, replica set 1 node (cần cho change streams)
mkdir -p ~/dad-mongo && mongod --dbpath ~/dad-mongo --port 27018 --replSet rs0 --bind_ip 127.0.0.1 --fork --logpath ~/dad-mongo/mongod.log
mongosh --port 27018 --eval 'rs.initiate({_id:"rs0",members:[{_id:0,host:"127.0.0.1:27018"}]})'

PY=monitoring/.venv/bin/python
$PY monitoring/src/xuat_mongo.py            # 1. data/*.pcap -> data/mongo/ (khoảng 2 phút)
$PY monitoring/src/nap_mongo.py             # 2. nạp vào MongoDB (MONGODB_URI, mặc định 127.0.0.1:27018)
#    hoặc: mongorestore --uri "$MONGODB_URI" --archive=data/mongo/dad.archive.gz --gzip   (xem data/mongo/README.md)
$PY monitoring/src/day_datadog.py           # 3a. chạy thử: ghi sổ gửi + payload, không gửi
$PY monitoring/src/kiem_tra_du_lieu.py      # 4. kiểm tra A–E, thoát mã 1 nếu lệch
DD_API_KEY=... DD_SITE=datadoghq.com $PY monitoring/src/day_datadog.py --speed 60 \
    --tu 2019-10-23T01:30:00Z --den 2019-10-23T05:00:00Z --live         # 3b. gửi thật (ví dụ: sự cố thứ Tư)
DD_API_KEY=... DD_APP_KEY=... $PY monitoring/src/kiem_tra_du_lieu.py --datadog   # 4b. đọc lại từ Datadog
```

## Ghi chú

- `ts` luôn là **UTC**. File dữ liệu chia theo nửa đêm giờ Madrid (22:00 UTC hôm trước). Đọc Date từ MongoDB bằng pymongo phải bật `tz_aware=True`, nếu không sẽ bị hiểu theo giờ máy.
- Ground truth (nhãn) không có trong mô hình vận hành; khi cần chấm thì đọc từ file CSV (nhóm kiểm tra A, D).
