# Dữ liệu DAD cho MongoDB

Dữ liệu trong thư mục này được sinh từ 7 file PCAP ở `data/binh_thuong/` và `data/bat_thuong/` bằng `monitoring/src/xuat_mongo.py`, theo mô hình ở [`monitoring/DATA_MODEL.md`](../../monitoring/DATA_MODEL.md). Mỗi bản tin giữ `src` (file + frame) để truy về gói gốc.

| File | Nội dung |
|---|---|
| `dad.archive.gz` | bản `mongodump` của database `dad` (cả 3 collection, cấu hình time series và index). **Cách nạp nhanh nhất** |
| `telemetry.ndjson.gz` | 32.288 document, 1 document / bản tin nhiệt độ (MongoDB Extended JSON, mỗi dòng 1 document) |
| `latest.ndjson.gz` | 16 document, trạng thái cuối của từng cảm biến |
| `incidents.ndjson.gz` | 18 document, sự cố do bộ quy tắc D1, D2, D4 phát hiện |
| `manifest.json` | số document và sha256 của từng file NDJSON (trước khi nén) |

Yêu cầu: MongoDB ≥ 7.0 (time series, `$median`). Muốn dùng change streams (trên `incidents`, `latest`) thì MongoDB phải chạy dạng replica set.

## Cách 1: `mongorestore` (giữ nguyên mọi cấu hình)

```bash
mongorestore --uri "mongodb://<host>:<port>/?replicaSet=rs0" --archive=data/mongo/dad.archive.gz --gzip
# đổi tên database khi nạp, ví dụ thành dad_test:
mongorestore --uri "..." --archive=data/mongo/dad.archive.gz --gzip --nsFrom 'dad.*' --nsTo 'dad_test.*'
```

## Cách 2: script Python (tạo collection, index rồi nạp NDJSON)

```bash
MONGODB_URI="mongodb://<host>:<port>/?replicaSet=rs0" MONGODB_DB=dad \
    monitoring/.venv/bin/python monitoring/src/nap_mongo.py
```
Chạy lại là xoá và nạp lại từ đầu. Script không đặt TTL cho `telemetry` vì dữ liệu là năm 2019 (TTL sẽ xoá ngay khi nạp).

## Kiểm tra sau khi nạp

```bash
MONGODB_URI="mongodb://<host>:<port>/?replicaSet=rs0" MONGODB_DB=dad \
    monitoring/.venv/bin/python monitoring/src/kiem_tra_du_lieu.py
```
So từng document với file PCAP và CSV gốc (đọc PCAP bằng bộ giải mã riêng, không dùng scapy). Kết quả mong đợi: **27/27 kiểm tra đạt** (33/33 nếu đã chạy thêm bước Datadog). Đã thử cả hai cách nạp trên vào database mới và đều đạt.

## Sinh lại từ file gốc

```bash
monitoring/.venv/bin/python monitoring/src/xuat_mongo.py     # ghi lại *.ndjson.gz + manifest.json (sha256 giống hệt khi chạy lại)
monitoring/.venv/bin/python monitoring/src/nap_mongo.py
mongodump --uri "mongodb://127.0.0.1:27018/?replicaSet=rs0" --db dad --archive=data/mongo/dad.archive.gz --gzip
```
