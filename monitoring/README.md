# DAD: EDA và thiết kế hệ thống giám sát IoT real-time

Phân tích bộ dữ liệu **DAD** (cảm biến làm mát data center gửi qua MQTT) để làm nền cho hệ thống giám sát IoT trong MUGVN Hackathon 2026 (MongoDB × Datadog, *IoT Real-time Operations*).

Notebook (đã chạy sẵn, có đủ bảng và biểu đồ), đọc theo thứ tự:
- [`notebooks/00_hieu_dataset_DAD.ipynb`](notebooks/00_hieu_dataset_DAD.ipynb): **bắt đầu ở đây nếu chưa biết DAD**. Giải thích bối cảnh data center, 4 loại cảm biến, cách tạo dữ liệu, từng loại file (PCAP, CSV, XML), MQTT, ý nghĩa từng cột, 3 kiểu tấn công và những chỗ dễ hiểu nhầm.
- [`notebooks/01_dad_eda_va_thiet_ke_monitoring.ipynb`](notebooks/01_dad_eda_va_thiet_ke_monitoring.ipynb): EDA và đề xuất thiết kế ban đầu.
- [`notebooks/02_data_mining_cho_monitor.ipynb`](notebooks/02_data_mining_cho_monitor.ipynb): khai thác sâu tầng mạng/MQTT, dấu vân tay từng loại tấn công, so sánh bộ phát hiện ở mức sự cố, xuất cấu hình cho pipeline.
- [`notebooks/03_dao_sau_va_kiem_chung.ipynb`](notebooks/03_dao_sau_va_kiem_chung.ipynb): nghiên cứu khác đã làm gì với DAD; kiểm chứng kết quả ML của bài *Electronics* 2021 (rò nhãn); độ ổn định của ngưỡng D4; tự động điều tra sự cố; thời gian khi replay.

- [`notebooks/04_tu_dataset_goc_den_mongodb.ipynb`](notebooks/04_tu_dataset_goc_den_mongodb.ipynb): xuất dataset gốc thành 9 collection MongoDB, từ điển dữ liệu từng collection, nạp vào MongoDB, chạy bộ phát hiện bằng Aggregation Pipeline và đối chiếu với pandas (khớp 100%), thử kịch bản demo tua ×60.

**Đặc tả monitor chốt cho cuộc thi:** [`MONITOR_SPEC.md`](MONITOR_SPEC.md).

**Cái gì đáng monitor từ cảm biến, ngưỡng bao nhiêu, dashboard cho ai:** [`NGHIEP_VU_GIAM_SAT.md`](NGHIEP_VU_GIAM_SAT.md).

**Chưa có kinh nghiệm vận hành? Đọc trước:** [`HUONG_TRIEN_KHAI.md`](HUONG_TRIEN_KHAI.md): cách nghĩ về bài toán, nghiệp vụ xử lý sự cố ngoài đời, kế hoạch build 17–31/10, chia việc, rủi ro.

## Đưa dữ liệu vào MongoDB

Dữ liệu đã xuất sẵn ở `data/mongo/*.ndjson.gz` (9 collection, khoảng 490 KB). Cần MongoDB ≥ 7.0.
```bash
pip install -r requirements.txt
python src/dad_export.py                                     # (tuỳ chọn) tạo lại từ PCAP + CSV gốc
MONGODB_URI="mongodb+srv://<user>:<pass>@<cluster>/" python src/dad_mongo_load.py --db dad
```
| Collection | Số document | Nội dung |
|---|---|---|
| `telemetry_hist` | 32.288 | Time Series, mỗi bản tin nhiệt độ một document (không TTL) |
| `telemetry` | 0 | Time Series live, TTL 7 ngày, cho replay |
| `devices` / `inrows` | 16 / 4 | hồ sơ cảm biến và tủ làm mát |
| `mqtt_sessions` | 112 | kết nối MQTT theo ngày |
| `traffic_daily` | 35 | số gói theo ngày × IP × loại |
| `gt_labels` / `gt_incidents` | 544 / 11 | nhãn và sự cố chuẩn (chỉ để chấm) |
| `detector_config` / `demo_scenarios` | 1 / 4 | ngưỡng; đoạn dữ liệu cho demo |
| `incidents` / `actions` | 0 / 0 | do hệ thống ghi khi chạy (có validator) |

Dữ liệu (PCAP + nhãn) nằm sẵn ở thư mục gốc của repo `dad`; notebook đọc thẳng từ đó.

## Chạy lại

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
jupyter lab notebooks/          # notebook 04 cần MongoDB (biến MONGODB_URI, mặc định localhost)
```

Lần chạy đầu đọc PCAP mất khoảng 1 phút, sau đó dùng cache trong `data/processed`.

## Cấu trúc

```
src/dad_download.py   tải dữ liệu gốc
src/dad_loader.py     đọc PCAP (scapy), ghép nhãn CSV, tạo bảng telemetry
src/dad_mining.py     tầng mạng/MQTT, baseline, ground truth, bộ phát hiện D1/D2/D3/D4, chấm mức sự cố
src/dad_export.py     xuất dataset gốc thành 9 collection MongoDB (data/mongo/*.ndjson.gz)
src/dad_mongo_load.py nạp vào MongoDB: Time Series, TTL, validator, index; nạp kịch bản demo dời thời gian
src/dad_mongo_pipelines.py  D1/D2/D4, kiểm tra vật lý, dải giá trị, điều tra bằng Aggregation Pipeline
data/mongo/           dữ liệu MongoDB đã xuất sẵn + manifest.csv
MONITOR_SPEC.md       đặc tả monitor, data model, runbook, kịch bản demo cho cuộc thi
notebooks/            EDA, data mining, thông số thiết kế hệ thống
outputs/              sensor_profile.csv, ground_truth_incidents.csv, detector_config.json
data/processed/       cache, không commit
```

## Kết quả chính (tính lại từ file gốc)

- Khớp bài báo: 101.583 packet, 98.142 TCP, 3.441 UDP, 64.872 frame MQTT, 112 kết nối TCP.
- CSV có **544 dòng nhãn 1**, đều là bản tin PUBLISH của InRow 13 (bài báo ghi 1.088 packet anomaly).
- Bản tin gửi lên topic chung `IoT`, payload là số dạng text, QoS 1, chu kỳ 300,1 s.
- Vị trí trong `clientId` ứng với loại cảm biến **suy ra từ giá trị**: 1 = TFEU, 2 = TFSU, 3 = TAS, 4 = TAR.
- 4 cảm biến của một InRow gần như là một chuỗi chung cộng độ lệch cố định; bất thường luôn tác động cả 4 cảm biến của InRow 13.
- Mất gói và gửi dồn bắt được gần như hoàn hảo bằng quy tắc nhịp gửi.
- Modification = trừ một số nguyên độ (0–3 °C) cùng lúc trên cả 4 cảm biến, độ lệch giữa cảm biến giữ nguyên. Quy tắc mới D4 "lệch âm > 0,8 °C ở ≥ 3/6 chu kỳ" bắt 6/6 cửa sổ có nhãn, 0 báo giả (quy tắc biến động cũ: 9 báo giả).
- D1 + D2 + D4 bắt 11/11 cửa sổ sự cố, 0 báo giả trong tuần (ngưỡng chọn và chấm trên cùng dữ liệu, xem hạn chế trong notebook 02).
- Tín hiệu hạ tầng: PUBACK p99 ≈ 0,6 ms; 20 PUBLISH không được ACK lúc reconnect 00:00; msgid luôn liên tục (đã đánh số lại) nên chỉ phát hiện mất gói bằng thời gian. (InRow 25 không có NTP trong capture vì sync qua card mạng khác, theo bài báo.)
- Đối chiếu bài báo (notebook 02, mục 7): 1.088 packet bất thường = 544 PUBLISH + 544 PUBACK (Table 5 gấp đúng 2 lần CSV); tái tạo được 544 flow bất thường theo định nghĩa flow một chiều, timeout 30 s. Dữ liệu thật dao động khác dữ liệu tổng hợp (TFEU std ≈ 1,0 so với 0,36), và trong thực tế TAR gần như độc lập với các cảm biến khác.

## Khai báo

- Dataset: L. Vigoya, D. Fernandez, V. Carneiro, F. Cacheda, *Annotated Dataset for Anomaly Detection in a Data Center with IoT Sensors*, Sensors 2020, 20(13), 3745, doi:10.3390/s20133745. Dữ liệu bán tổng hợp; repo gốc không có file LICENSE; khi nộp bài cần trích dẫn và khai báo là dataset bên ngoài.
- Code và notebook được viết với sự hỗ trợ của Claude (Anthropic).
