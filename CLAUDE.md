# CLAUDE.md

Repo `dad`: bộ dữ liệu DAD (Vigoya et al., Sensors 2020) và phân tích ở `monitoring/`.
Báo cáo phân tích: `monitoring/notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb`; kiểm chứng trên file gốc: `monitoring/KIEM_CHUNG_DU_LIEU_GOC.md`.

## Quyết định kiến trúc giám sát (đã chốt 2026-10-20)

```
16 cảm biến ──MQTT topic dc/citic/inrow{13,15,23,25}/{TFEU,TFSU,TAS,TAR}──► 1 broker MQTT
                                                    │ subscribe dc/citic/+/+
                                                    ▼
                                      subscriber/ingest (gắn tag inrow, sensor)
                                  │                    │                        │
                                  ▼                    ▼                        ▼
                MongoDB `telemetry`         MongoDB `latest`           Datadog: metric có tag
                (TIME SERIES)               (collection thường,        inrow, sensor
                                             1 doc / cảm biến)
                                  │
                                  └─ bộ phát hiện chạy theo chu kỳ (aggregation: độ tươi,
                                     bản tin đến sớm, lệch âm kéo dài) ──► MongoDB `incidents`
                                                                          (collection thường)
                                                                                 │
                                                       change stream trên `incidents` ──► cảnh báo / xử lý
```

- **Một broker** cho cả 4 tủ; tách theo tủ/cảm biến bằng **topic phân cấp và tag**, không tách broker.
- **`telemetry` là time series collection**: `timeField: "ts"`, `metaField: "meta"` (`{inrow, sensor, clientId}`), `granularity: "minutes"` (nhịp gửi 5 phút), TTL cho dữ liệu thô. Không sửa dữ liệu đã ghi.
- **MongoDB tự host trên máy (local), không dùng Atlas, không dùng Atlas Stream Processing** (chốt 2026-10-20; Atlas Stream Processing cũng không đọc được MQTT). Chạy dạng replica set 1 node để có change streams. Kết nối mặc định: `mongodb://127.0.0.1:27018/?replicaSet=rs0` (biến môi trường `MONGODB_URI`).
- **Change streams chỉ dùng trên collection thường** (`incidents`, `latest`): time series collection không hỗ trợ change streams. MongoDB phải là replica set (Atlas có sẵn; tự cài thì bật replica set kể cả 1 node).
- **Một service Python duy nhất** (chốt 2026-10-20): `paho-mqtt` nghe broker, `pymongo` ghi MongoDB, `datadog` (DogStatsD) gửi metric. Gồm 3 khâu tách bạch: **ingest** (mỗi bản tin → `telemetry`, `latest`, metric Datadog), **phát hiện** (mỗi chu kỳ, đọc `telemetry`/`latest` → `incidents`), **phản ứng** (change stream trên `incidents`). Ingest không tạo `incidents`. Không dùng Telegraf ở giai đoạn này; sau có thể thay riêng khâu nhận bằng Telegraf mà không phải viết lại khâu phát hiện/phản ứng.
- Mô hình dữ liệu và object mẫu (trích từ đúng frame trong `data/`): `monitoring/DATA_MODEL.md`.
- **Dữ liệu nạp MongoDB nằm trong repo ở `data/mongo/`** (`dad.archive.gz` cho `mongorestore`, và `*.ndjson.gz` cho `nap_mongo.py`); hướng dẫn: `data/mongo/README.md`. Kiểm tra sau khi nạp: `monitoring/src/kiem_tra_du_lieu.py`.
- **Datadog**: một dashboard có template variable `$inrow` (4 lựa chọn), monitor multi-alert theo `inrow`.
- Ngưỡng phát hiện và 6 metric: xem báo cáo, phần "Metrics" và "Bảng ngưỡng chốt".

## Quy ước làm việc

- Mọi thông số nghiệp vụ phải có nguồn đã mở và đối chiếu, ghi ngay dưới đoạn giải thích.
- Notebook báo cáo do người dùng sửa trực tiếp: sửa tại chỗ, không dựng lại từ nguồn sinh.
- Trước khi xoá nội dung, hỏi lại xem người dùng muốn bỏ nội dung hay chỉ bỏ nhãn/tiêu đề.
