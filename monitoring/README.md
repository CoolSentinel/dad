# Phân tích bộ dữ liệu DAD

Phân tích bộ dữ liệu **DAD** (16 cảm biến nhiệt độ của 4 tủ làm mát trong data center, gửi qua MQTT; L. Vigoya et al., Sensors 2020): dữ liệu là gì, bình thường trông ra sao, bất thường để lại dấu vết gì, và từ dữ liệu thì nên giám sát những metric nào.

## Đọc gì

| File | Nội dung |
|---|---|
| [`notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb`](notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb) | **Báo cáo chính.** A bài toán và bài báo gốc · B giải phẫu file gốc · C hành vi bình thường · D bất thường · E đúc kết nghiệp vụ giám sát · F bộ metrics tối thiểu · G giới hạn, dàn ý slide, kiểm chứng tự động, nguồn. Mọi con số tính lại từ file gốc và được kiểm tự động; mỗi thông số lấy từ tài liệu ngoài có ghi nguồn (mục, bảng, trang) |
| [`KIEM_CHUNG_DU_LIEU_GOC.md`](KIEM_CHUNG_DU_LIEU_GOC.md) | Tự kiểm trên dữ liệu gốc: từng file của dataset là gì, cách mở bằng Wireshark và trình soạn thảo, các bản ghi cụ thể (tên file, số frame, nguyên văn dòng CSV) cho từng phát hiện |
| `notebooks/figures/khung/` | hình đã xuất cho slide |
| `notebooks/figures/paper/` | hình trích từ bài báo gốc (CC BY 4.0) |

Dữ liệu gốc (7 file `.pcap` + 7 file nhãn `.csv`/`.xml`) nằm ở thư mục gốc của repo `dad`; notebook đọc thẳng từ đó.

## Chạy lại

```bash
cd monitoring
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
jupyter lab notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb     # Run All
```
Lần đầu đọc PCAP mất khoảng 1 phút, sau đó dùng cache trong `data/processed/` (không commit).

Xem nhanh một gói tin trong dữ liệu gốc (chạy ở thư mục gốc repo `dad`):
```bash
python monitoring/src/xem_frame.py capture_1910230000_wed.pcap 2707     # in frame kèm dòng nhãn CSV
wireshark -r capture_1910230000_wed.pcap -g 2707 -t ud &                # mở bằng Wireshark, giờ UTC
```

## Cấu trúc

```
src/dad_loader.py    đọc PCAP (scapy), ghép nhãn CSV, tạo bảng bản tin nhiệt độ
src/dad_mining.py    tầng mạng/MQTT, baseline, ground truth, quy tắc phát hiện D1/D2/D4, chấm theo sự cố
src/dad_paper.py     số liệu lấy từ bài báo gốc (Table 1), đã đối chiếu
src/xem_frame.py     in nội dung một frame PCAP kèm dòng nhãn, để tự kiểm chứng
notebooks/           báo cáo và hình
data/processed/      cache, không commit
```

## Khai báo

- Dataset: L. Vigoya, D. Fernandez, V. Carneiro, F. Cacheda, *Annotated Dataset for Anomaly Detection in a Data Center with IoT Sensors*, Sensors 2020, 20(13), 3745, doi:10.3390/s20133745. Dữ liệu bán tổng hợp; repo gốc không có file LICENSE, khi dùng cần trích dẫn bài báo trên.
- Code và notebook được viết với sự hỗ trợ của Claude (Anthropic).
