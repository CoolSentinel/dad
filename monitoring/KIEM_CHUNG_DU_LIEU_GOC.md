# Kiểm chứng trên dữ liệu gốc DAD

Tài liệu đi kèm notebook [`notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb`](notebooks/BAO_CAO_PHAN_TICH_DAD.ipynb). Mục đích: khi đọc báo cáo gặp một khẳng định (ví dụ "lúc 04:10 thứ Tư cả 4 cảm biến bị trừ 2 °C"), bạn **tự mở file gốc và thấy đúng bản ghi đó**, không cần tin code.

Cách dùng: trong notebook, cạnh mỗi phát hiện có dòng **"Tra file gốc: T*n*"**. Tìm bảng T*n* ở mục 4 dưới đây: bảng ghi tên file, số frame, giờ, và **nguyên văn** dòng CSV. Mở file theo hướng dẫn ở mục 2–3 là thấy.

Mọi bản ghi trong mục 4 đã được đọc lại **trực tiếp** từ file PCAP và file CSV gốc (không qua code phân tích) và so khớp từng giá trị (payload, `msgid`, `clientId`, nhãn) trước khi ghi vào đây.

---

## 1. Dataset gốc gồm những file nào

21 file nằm trong thư mục **`data/`** của repo `dad/` (cùng cấp với `monitoring/`), chia theo ngày:
- **`data/binh_thuong/`**: thứ Hai 21/10 và Chủ nhật 27/10, không có tấn công nào;
- **`data/bat_thuong/`**: thứ Ba 22/10 đến thứ Bảy 26/10, có ít nhất một đợt tấn công. Không phải mọi bản tin trong đó đều bất thường: 3 tủ còn lại vẫn bình thường, InRow 13 chỉ bị tấn công trong vài khung giờ.

Mỗi ngày 3 file, luôn nằm cùng một thư mục:

| Ngày | Thứ | Thư mục | PCAP (gói tin) | Nhãn CSV | Nhãn XML |
|---|---|---|---|---|---|
| 21/10/2019 | Hai | `binh_thuong/` | `capture_1910210000_mon.pcap` | `capture_1910210000_labels.csv` | `capture_1910210000_labels.xml` |
| 22/10/2019 | Ba | `bat_thuong/` | `capture_1910220000_tue.pcap` | `capture_1910220000_labels.csv` | `capture_1910220000_labels.xml` |
| 23/10/2019 | Tư | `bat_thuong/` | `capture_1910230000_wed.pcap` | `capture_1910230000_labels.csv` | `capture_1910230000_labels.xml` |
| 24/10/2019 | Năm | `bat_thuong/` | `capture_1910240000_thu.pcap` | `capture_1910240000_labels.csv` | `capture_1910240000_labels.xml` |
| 25/10/2019 | Sáu | `bat_thuong/` | `capture_1910250000_fri.pcap` | `capture_1910250000_labels.csv` | `capture_1910250000_labels.xml` |
| 26/10/2019 | Bảy | `bat_thuong/` | `capture_1910260000_sat.pcap` | `capture_1910260000_labels.csv` | `capture_1910260000_labels.xml` |
| 27/10/2019 | Chủ nhật | `binh_thuong/` | `capture_1910270000_sun.pcap` | `capture_1910270000_labels.csv` | `capture_1910270000_labels.xml` |

Tên file: `capture_YYMMDDhhmm_...`, ví dụ `1910230000` = năm 2019, tháng 10, ngày 23, 00:00 (giờ Tây Ban Nha).

### 1.1 File `.pcap`: toàn bộ gói tin mạng của một ngày
- Bắt bằng `tcpdump` trên máy broker MQTT (bài báo, mục 3.3). Mỗi file khoảng 14.500 gói.
- **Nhiệt độ chỉ có ở đây**, nằm trong payload của gói MQTT `PUBLISH` (dạng chữ, ví dụ `"12.12"`).
- Mở bằng **Wireshark** (mục 2) hoặc script `monitoring/src/xem_frame.py` (mục 3).
- Gói thứ *n* trong file gọi là **frame *n*** (cột `No.` trong Wireshark), đếm từ 1.

### 1.2 File `_labels.csv`: nhãn cho từng gói
- Mỗi gói trong PCAP cùng ngày là một dòng, **phân cách bằng dấu chấm phẩy `;`**, dòng 1 là tiêu đề:
  ```
  frame.number;ip.src;tcp.srcport;mqtt.clientid;mqtt.msgid;label
  ```
- **Frame *n* nằm ở dòng *n* + 1** của file CSV.
- `mqtt.clientid` và `mqtt.msgid` chỉ có giá trị ở dòng PUBLISH; các dòng khác để trống (`;;`).
- `label` = 1: bản tin PUBLISH của node đang bị can thiệp; 0: bình thường. **Gói bị chặn (interception) không có dòng nào**, vì gói đã biến mất khỏi PCAP.
- **Không có nhiệt độ** trong CSV.

### 1.3 File `_labels.xml`
- Chỉ có `frame.number` và `label`, mỗi gói một dòng `<packet>…</packet>`. Trùng hoàn toàn với CSV (notebook, mục “File nhãn”). Không cần dùng.

### 1.4 Định danh: đọc một dòng thế nào

| Thấy trong file | Nghĩa |
|---|---|
| IP `10.6.56.1`, cổng `1883` | broker MQTT (Mosquitto) |
| IP `10.6.56.41` | tủ **InRow 13**, node bị tấn công; `clientId` 131–134 |
| IP `10.6.56.36` | tủ InRow 15; `clientId` 151–154 |
| IP `10.6.56.50` | tủ InRow 23; `clientId` 231–234 |
| IP `10.6.56.34` | tủ InRow 25; `clientId` 251–254 |
| chữ số cuối của `clientId` | 1 = TFEU (nước vào ≈ 11 °C), 2 = TFSU (nước ra ≈ 15 °C), 3 = TAS (khí cấp ≈ 20 °C), 4 = TAR (khí hồi ≈ 27 °C) |
| UDP cổng 123 | đồng bộ giờ NTP |

Ánh xạ chữ số → loại cảm biến được suy ra **từ giá trị đo** (notebook, mục “Từ điển định danh”); chú thích Hình 1 của bài báo ghi ngược vị trí 3 và 4.

---

## 2. Mở PCAP bằng Wireshark

Wireshark là phần mềm có giao diện, đã cài sẵn trên máy (bản 4.2.2). Cách nhanh nhất là mở từ terminal ở thư mục gốc repo `dad/`, nhảy thẳng tới một frame, giờ hiển thị theo UTC:
```bash
wireshark -r data/bat_thuong/capture_1910230000_wed.pcap -g 2707 -t ud &
```
`-r` là file cần mở, `-g` là số frame cần nhảy tới, `-t ud` là hiển thị ngày giờ theo UTC. Cũng có thể mở Wireshark từ menu ứng dụng rồi chọn *File → Open*.

### 2.1 Bước bắt buộc: hiển thị giờ theo UTC
Mặc định Wireshark hiển thị giờ theo **múi giờ của máy bạn** (Việt Nam là UTC+7), nên sẽ lệch với báo cáo. Chọn:

**View → Time Display Format → UTC Date and Time of Day**

Báo cáo ghi cả giờ UTC và giờ Madrid. Giờ Madrid = UTC + 2 (từ 03:00 ngày 27/10 trở đi là UTC + 1).

### 2.2 Đi tới một frame
**Go → Go to Packet…** (`Ctrl+G`), gõ số frame. Hoặc gõ bộ lọc `frame.number == 2707` vào ô lọc phía trên.

### 2.3 Bộ lọc hay dùng
Tên trường MQTT theo tài liệu tham chiếu chính thức của Wireshark ([Display Filter Reference: MQTT](https://www.wireshark.org/docs/dfref/m/mqtt.html), áp dụng cho các phiên bản 1.12 đến 4.6).

| Muốn xem | Bộ lọc |
|---|---|
| một frame | `frame.number == 2707` |
| một đoạn frame | `frame.number >= 2650 && frame.number <= 2720` |
| mọi bản tin nhiệt độ | `mqtt.msgtype == 3` |
| bản tin nhiệt độ của InRow 13 | `mqtt.msgtype == 3 && ip.src == 10.6.56.41` |
| một cảm biến (theo cổng của ngày đó, xem bảng T9) | `mqtt.msgtype == 3 && tcp.srcport == 49150` |
| gói CONNECT (xem `clientId`, keepalive) | `mqtt.msgtype == 1` |
| gói DISCONNECT | `mqtt.msgtype == 14` |
| gói NTP của InRow 25 | `ntp && ip.src == 10.6.56.34` |

Payload nhiệt độ nằm ở dòng **Message** của lớp *MQ Telemetry Transport Protocol* trong khung chi tiết gói (cột `mqtt.msg`, hiển thị dạng hex; Wireshark mới hiển thị thêm dạng chữ).

### 2.4 Con số bạn sẽ thấy khi lọc (thanh trạng thái "Displayed: …")

| File | `mqtt` | `mqtt.msgtype == 3` | `mqtt.msgtype == 4` | `mqtt.msgtype == 1` | `mqtt.msgtype == 14` | `udp` | `mqtt.msgtype == 3 && ip.src == 10.6.56.41` | `ntp && ip.src == 10.6.56.34` |
|---|---|---|---|---|---|---|---|---|
| `capture_1910210000_mon.pcap` | 9,248 | 4,608 | 4,608 | 16 | 0 | 495 | 1,152 | 0 |
| `capture_1910220000_tue.pcap` | 9,184 | 4,568 | 4,568 | 16 | 16 | 490 | 1,112 | 0 |
| `capture_1910230000_wed.pcap` | 9,264 | 4,608 | 4,608 | 16 | 16 | 492 | 1,152 | 0 |
| `capture_1910240000_thu.pcap` | 9,268 | 4,608 | 4,608 | 16 | 20 | 490 | 1,152 | 0 |
| `capture_1910250000_fri.pcap` | 9,292 | 4,624 | 4,624 | 16 | 12 | 490 | 1,168 | 0 |
| `capture_1910260000_sat.pcap` | 9,339 | 4,648 | 4,644 | 16 | 15 | 492 | 1,192 | 0 |
| `capture_1910270000_sun.pcap` | 9,277 | 4,624 | 4,608 | 16 | 13 | 492 | 1,156 | 0 |

Cột `mqtt` và `udp` khớp **Table 5** của bài báo từng ngày (notebook, mục “Tầng mạng”).

---

## 3. Mở CSV và dùng script

### 3.1 CSV
- **LibreOffice Calc / Excel:** khi mở chọn dấu phân cách là `;`. Số dòng hiển thị = frame + 1.
- **Terminal** (chạy ở thư mục gốc repo `dad/`; file dữ liệu nằm trong `data/binh_thuong/` hoặc `data/bat_thuong/`):
  ```bash
  sed -n '2708p' data/bat_thuong/capture_1910230000_labels.csv          # dòng của frame 2707
  grep -n '^2707;' data/bat_thuong/capture_1910230000_labels.csv        # tìm theo số frame
  grep -c ';1$' data/bat_thuong/capture_1910230000_labels.csv           # đếm số nhãn 1 trong file
  grep ';1$' data/bat_thuong/capture_1910230000_labels.csv | head       # xem các dòng nhãn 1
  ```

### 3.2 Script `xem_frame.py`
In nội dung frame (giờ UTC, giờ Madrid, IP, cổng, loại MQTT, `clientId`, `msgid`, payload nhiệt độ) **kèm dòng CSV cùng frame**. Đọc thẳng file gốc bằng `scapy`, không dùng code phân tích:
```bash
# chạy ở thư mục gốc repo dad/, môi trường monitoring/.venv
python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap 2707
python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap --tu 2700 --den 2716
```
Ví dụ kết quả:
```
frame 2707 | UTC 2019-10-23 02:10:07.155 | Madrid 2019-10-23 04:10:07 +0200 | TCP 10.6.56.41:49152 → 10.6.56.1:1883 | cờ TCP PA
    MQTT type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=51, payload=18.02
    CSV dòng 2708: 2707;10.6.56.41;49152;133;51;1
```

---

## 4. Bảng bằng chứng

Mỗi bảng gắn với một mục của notebook. Cột "dòng CSV" là **nguyên văn** dòng trong file `_labels.csv` cùng ngày. Cột "cách bản tin trước" là khoảng thời gian tới bản tin trước của **cùng cảm biến** (bình thường ≈ 300 s).

### T1. Một phiên MQTT bình thường (notebook mục “MQTT”)
File `capture_1910210000_mon.pcap`. Cảm biến 131 kết nối lúc 00:00:02, gửi bản tin đầu tiên, broker xác nhận; 5 phút sau gửi bản tin thứ hai.

| frame (No.) | giờ Madrid | gói | nội dung | dòng CSV (nguyên văn) |
|---|---|---|---|---|
| **125** | 00:00:02 | 10.6.56.41:49134 → 10.6.56.1:1883 | type=CONNECT, clientId=131, keepalive=300, clean_session=1 | `125;10.6.56.41;49134;;;0` |
| **133** | 00:00:02 | 10.6.56.1:1883 → 10.6.56.41:49134 | type=CONNACK | `133;10.6.56.1;1883;;;0` |
| **143** | 00:00:02 | 10.6.56.41:49134 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=1, payload=12.12 | `143;10.6.56.41;49134;131;1;0` |
| **144** | 00:00:02 | 10.6.56.1:1883 → 10.6.56.41:49134 | type=PUBACK, msgid=1 | `144;10.6.56.1;1883;;;0` |
| **199** | 00:05:02 | 10.6.56.41:49134 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=2, payload=12.12 | `199;10.6.56.41;49134;131;2;0` |
| **200** | 00:05:02 | 10.6.56.1:1883 → 10.6.56.41:49134 | type=PUBACK, msgid=2 | `200;10.6.56.1;1883;;;0` |

Thấy được: `clientId` chỉ xuất hiện ở gói CONNECT (frame 125); các gói PUBLISH sau đó chỉ có IP + cổng `49134`, nên phải nhớ cổng ↔ `clientId`. Dòng CSV của PUBLISH thì có điền sẵn `clientId` (131) và `msgid`.

### T2. 16 cảm biến gửi gần như cùng lúc (notebook mục “Nhịp gửi”)
Mọi bản tin lúc 00:10 thứ Hai. Cả 16 cảm biến đều gửi trong cùng giây 00:10:02.

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910210000_mon.pcap` | **213** | 00:10:02 | 22:10:02 | 152 (TFSU) | 3 | 15.74 | 300 s | `213;10.6.56.36;47590;152;3;0` |
| `capture_1910210000_mon.pcap` | **214** | 00:10:02 | 22:10:02 | 151 (TFEU) | 3 | 12.06 | 300 s | `214;10.6.56.36;47588;151;3;0` |
| `capture_1910210000_mon.pcap` | **217** | 00:10:02 | 22:10:02 | 153 (TAS) | 3 | 20.27 | 300 s | `217;10.6.56.36;47592;153;3;0` |
| `capture_1910210000_mon.pcap` | **218** | 00:10:02 | 22:10:02 | 154 (TAR) | 3 | 27.48 | 300 s | `218;10.6.56.36;47594;154;3;0` |
| `capture_1910210000_mon.pcap` | **225** | 00:10:02 | 22:10:02 | 253 (TAS) | 3 | 19.91 | 300 s | `225;10.6.56.34;40816;253;3;0` |
| `capture_1910210000_mon.pcap` | **226** | 00:10:02 | 22:10:02 | 251 (TFEU) | 3 | 11.23 | 300 s | `226;10.6.56.34;40818;251;3;0` |
| `capture_1910210000_mon.pcap` | **229** | 00:10:02 | 22:10:02 | 254 (TAR) | 3 | 26.69 | 300 s | `229;10.6.56.34;40822;254;3;0` |
| `capture_1910210000_mon.pcap` | **231** | 00:10:02 | 22:10:02 | 252 (TFSU) | 3 | 15.34 | 300 s | `231;10.6.56.34;40820;252;3;0` |
| `capture_1910210000_mon.pcap` | **237** | 00:10:02 | 22:10:02 | 231 (TFEU) | 3 | 11.58 | 300 s | `237;10.6.56.50;44488;231;3;0` |
| `capture_1910210000_mon.pcap` | **239** | 00:10:02 | 22:10:02 | 234 (TAR) | 3 | 26.53 | 300 s | `239;10.6.56.50;44490;234;3;0` |
| `capture_1910210000_mon.pcap` | **243** | 00:10:02 | 22:10:02 | 232 (TFSU) | 3 | 15.34 | 300 s | `243;10.6.56.50;44486;232;3;0` |
| `capture_1910210000_mon.pcap` | **246** | 00:10:02 | 22:10:02 | 233 (TAS) | 3 | 20.27 | 300 s | `246;10.6.56.50;44492;233;3;0` |
| `capture_1910210000_mon.pcap` | **249** | 00:10:02 | 22:10:02 | 131 (TFEU) | 3 | 12.31 | 300 s | `249;10.6.56.41;49134;131;3;0` |
| `capture_1910210000_mon.pcap` | **251** | 00:10:02 | 22:10:02 | 133 (TAS) | 3 | 20.25 | 300 s | `251;10.6.56.41;49136;133;3;0` |
| `capture_1910210000_mon.pcap` | **255** | 00:10:02 | 22:10:02 | 134 (TAR) | 3 | 27.64 | 300 s | `255;10.6.56.41;49138;134;3;0` |
| `capture_1910210000_mon.pcap` | **258** | 00:10:02 | 22:10:02 | 132 (TFSU) | 3 | 16.24 | 300 s | `258;10.6.56.41;49140;132;3;0` |

### T3. Sửa giá trị: cả tủ bị trừ cùng lúc (notebook mục “Sửa giá trị”)
File `capture_1910230000_wed.pcap`, InRow 13. **04:05** bình thường, **04:10** bị trừ khoảng 2 °C ở cả 4 cảm biến, **04:25** mang nhãn 1 nhưng giá trị **không đổi**.

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910230000_wed.pcap` | **2657** | 04:05:07 | 02:05:07 | 132 (TFSU) | 50 | 15.76 | 300 s | `2657;10.6.56.41;49154;132;50;0` |
| `capture_1910230000_wed.pcap` | **2659** | 04:05:07 | 02:05:07 | 134 (TAR) | 50 | 27.21 | 300 s | `2659;10.6.56.41;49156;134;50;0` |
| `capture_1910230000_wed.pcap` | **2660** | 04:05:07 | 02:05:07 | 131 (TFEU) | 50 | 11.78 | 300 s | `2660;10.6.56.41;49150;131;50;0` |
| `capture_1910230000_wed.pcap` | **2661** | 04:05:07 | 02:05:07 | 133 (TAS) | 50 | 19.91 | 300 s | `2661;10.6.56.41;49152;133;50;0` |
| `capture_1910230000_wed.pcap` | **2707** | 04:10:07 | 02:10:07 | 133 (TAS) | 51 | 18.02 | 300 s | `2707;10.6.56.41;49152;133;51;1` |
| `capture_1910230000_wed.pcap` | **2708** | 04:10:07 | 02:10:07 | 131 (TFEU) | 51 | 9.96 | 300 s | `2708;10.6.56.41;49150;131;51;1` |
| `capture_1910230000_wed.pcap` | **2711** | 04:10:07 | 02:10:07 | 132 (TFSU) | 51 | 13.89 | 300 s | `2711;10.6.56.41;49154;132;51;1` |
| `capture_1910230000_wed.pcap` | **2716** | 04:10:07 | 02:10:07 | 134 (TAR) | 51 | 25.29 | 300 s | `2716;10.6.56.41;49156;134;51;1` |
| `capture_1910230000_wed.pcap` | **2855** | 04:25:07 | 02:25:07 | 132 (TFSU) | 54 | 15.96 | 300 s | `2855;10.6.56.41;49154;132;54;1` |
| `capture_1910230000_wed.pcap` | **2857** | 04:25:07 | 02:25:07 | 133 (TAS) | 54 | 19.97 | 300 s | `2857;10.6.56.41;49152;133;54;1` |
| `capture_1910230000_wed.pcap` | **2861** | 04:25:07 | 02:25:07 | 134 (TAR) | 54 | 27.39 | 300 s | `2861;10.6.56.41;49156;134;54;1` |
| `capture_1910230000_wed.pcap` | **2863** | 04:25:07 | 02:25:07 | 131 (TFEU) | 54 | 11.96 | 300 s | `2863;10.6.56.41;49150;131;54;1` |

Thấy được:
- 04:05 → 04:10: TFEU 11,78 → 9,96; TFSU 15,76 → 13,89; TAS 19,91 → 18,02; TAR 27,21 → 25,29. Cả 4 cùng giảm khoảng 1,9 °C, khoảng cách TAR − TAS vẫn ≈ 7,3 °C.
- 04:25 có `label = 1` nhưng giá trị (11,96; 15,96; 19,97; 27,39) như lúc bình thường: một slot "bị trừ 0 °C". Đây là lý do chấm theo từng bản tin không thể đạt 100%.
- Nhịp gửi vẫn đúng 300 s: sửa giá trị **không** để lại dấu vết thời gian.
- Trong Wireshark: `frame.number >= 2650 && frame.number <= 2870 && mqtt.msgtype == 3 && ip.src == 10.6.56.41`.

### T4. Chèn bản tin (notebook mục “Chèn bản tin”)
File `capture_1910240000_thu.pcap`, cảm biến 131, 03:00–03:30 thứ Năm.

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910240000_thu.pcap` | **1998** | 03:00:06 | 01:00:06 | 131 (TFEU) | 37 | 11.29 | 300 s | `1998;10.6.56.41;49158;131;37;0` |
| `capture_1910240000_thu.pcap` | **2059** | 03:05:06 | 01:05:06 | 131 (TFEU) | 38 | 11.05 | 300 s | `2059;10.6.56.41;49158;131;38;1` |
| `capture_1910240000_thu.pcap` | **2102** | 03:06:37 | 01:06:37 | 131 (TFEU) | 39 | 9.08 | 91 s | `2102;10.6.56.41;49158;131;39;1` |
| `capture_1910240000_thu.pcap` | **2116** | 03:07:57 | 01:07:57 | 131 (TFEU) | 40 | 12.23 | 80 s | `2116;10.6.56.41;49158;131;40;1` |
| `capture_1910240000_thu.pcap` | **2121** | 03:09:25 | 01:09:25 | 131 (TFEU) | 41 | 12.28 | 88 s | `2121;10.6.56.41;49158;131;41;1` |
| `capture_1910240000_thu.pcap` | **2172** | 03:11:09 | 01:11:09 | 131 (TFEU) | 42 | 10.23 | 104 s | `2172;10.6.56.41;49158;131;42;1` |
| `capture_1910240000_thu.pcap` | **2181** | 03:12:38 | 01:12:38 | 131 (TFEU) | 43 | 12.22 | 89 s | `2181;10.6.56.41;49158;131;43;1` |
| `capture_1910240000_thu.pcap` | **2197** | 03:13:59 | 01:13:59 | 131 (TFEU) | 44 | 9.21 | 81 s | `2197;10.6.56.41;49158;131;44;1` |
| `capture_1910240000_thu.pcap` | **2248** | 03:15:33 | 01:15:33 | 131 (TFEU) | 45 | 9.19 | 94 s | `2248;10.6.56.41;49158;131;45;1` |
| `capture_1910240000_thu.pcap` | **2259** | 03:16:13 | 01:16:13 | 131 (TFEU) | 46 | 11.22 | 40 s | `2259;10.6.56.41;49158;131;46;1` |
| `capture_1910240000_thu.pcap` | **2268** | 03:17:32 | 01:17:32 | 131 (TFEU) | 47 | 10.12 | 78 s | `2268;10.6.56.41;49158;131;47;1` |
| `capture_1910240000_thu.pcap` | **2281** | 03:18:31 | 01:18:31 | 131 (TFEU) | 48 | 12.01 | 59 s | `2281;10.6.56.41;49158;131;48;1` |
| `capture_1910240000_thu.pcap` | **2292** | 03:19:53 | 01:19:53 | 131 (TFEU) | 49 | 8.96 | 82 s | `2292;10.6.56.41;49158;131;49;1` |
| `capture_1910240000_thu.pcap` | **2341** | 03:20:54 | 01:20:54 | 131 (TFEU) | 50 | 11.05 | 61 s | `2341;10.6.56.41;49158;131;50;1` |
| `capture_1910240000_thu.pcap` | **2354** | 03:22:20 | 01:22:20 | 131 (TFEU) | 51 | 11.08 | 86 s | `2354;10.6.56.41;49158;131;51;1` |
| `capture_1910240000_thu.pcap` | **2367** | 03:23:32 | 01:23:32 | 131 (TFEU) | 52 | 12.23 | 72 s | `2367;10.6.56.41;49158;131;52;0` |
| `capture_1910240000_thu.pcap` | **2416** | 03:28:32 | 01:28:32 | 131 (TFEU) | 53 | 12.18 | 300 s | `2416;10.6.56.41;49158;131;53;0` |

Thấy được:
- 03:05:06 có nhãn nhưng đến đúng nhịp (300 s): bản tin mở đầu đợt.
- Từ 03:06:37, bản tin đến cách nhau **40–104 giây** thay vì 300, đều mang nhãn 1, giá trị dao động mạnh (8,96–12,28).
- 03:23:32 đến sớm 72 giây nhưng **nhãn 0**: bản tin bình thường đầu tiên sau đợt chèn, pha gửi đã bị xô. Từ đó nhịp quay lại 300 s nhưng lệch pha (giây :32 thay vì :06).
- `msgid` tăng liền 37 → 53: bản tin chèn cũng được đánh số liên tục.

### T5. Một đợt chèn: 4 cảm biến gửi cùng lúc (notebook mục “Chèn bản tin”)

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910240000_thu.pcap` | **2102** | 03:06:37 | 01:06:37 | 131 (TFEU) | 39 | 9.08 | 91 s | `2102;10.6.56.41;49158;131;39;1` |
| `capture_1910240000_thu.pcap` | **2099** | 03:06:37 | 01:06:37 | 132 (TFSU) | 39 | 12.99 | 91 s | `2099;10.6.56.41;49160;132;39;1` |
| `capture_1910240000_thu.pcap` | **2095** | 03:06:37 | 01:06:37 | 133 (TAS) | 39 | 16.97 | 91 s | `2095;10.6.56.41;49162;133;39;1` |
| `capture_1910240000_thu.pcap` | **2098** | 03:06:37 | 01:06:37 | 134 (TAR) | 39 | 24.29 | 91 s | `2098;10.6.56.41;49164;134;39;1` |

Cả 4 cảm biến của InRow 13 gửi trong cùng giây 03:06:37, đều cách bản tin trước 91 giây, đều nhãn 1. Giá trị đều thấp hơn bình thường (16,97 °C ở TAS so với ≈ 20).

### T6. Chặn gói: khoảng hở, `msgid` vẫn liên tục (notebook mục “Mất bản tin”, mục “MQTT”)
File `capture_1910220000_tue.pcap`, cảm biến 131, 00:00–00:45 thứ Ba.

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910220000_tue.pcap` | **124** | 00:00:02 | 22:00:02 | 131 (TFEU) | 1 | 11.98 | 271 s | `124;10.6.56.41;49146;131;1;0` |
| `capture_1910220000_tue.pcap` | **285** | 00:05:02 | 22:05:02 | 131 (TFEU) | 2 | 12.17 | 300 s | `285;10.6.56.41;49146;131;2;0` |
| `capture_1910220000_tue.pcap` | **330** | 00:10:02 | 22:10:02 | 131 (TFEU) | 3 | 12.12 | 300 s | `330;10.6.56.41;49146;131;3;0` |
| `capture_1910220000_tue.pcap` | **386** | 00:15:03 | 22:15:03 | 131 (TFEU) | 4 | 12.09 | 300 s | `386;10.6.56.41;49146;131;4;0` |
| `capture_1910220000_tue.pcap` | **488** | 00:30:03 | 22:30:03 | 131 (TFEU) | 5 | 12.00 | 900 s | `488;10.6.56.41;49146;131;5;0` |
| `capture_1910220000_tue.pcap` | **531** | 00:35:03 | 22:35:03 | 131 (TFEU) | 6 | 11.95 | 300 s | `531;10.6.56.41;49146;131;6;0` |
| `capture_1910220000_tue.pcap` | **581** | 00:40:03 | 22:40:03 | 131 (TFEU) | 7 | 12.02 | 300 s | `581;10.6.56.41;49146;131;7;0` |

Thấy được:
- Từ 00:15:03 tới 00:30:03 không có bản tin nào: **hở 900 s** (3 chu kỳ), mất 2 bản tin (00:20, 00:25).
- `msgid` đi 4 → 5, **không nhảy cóc**: số thứ tự đã được đánh lại sau khi xoá gói, nên không thể đếm bản tin mất bằng `msgid`.
- CSV không có dòng nào cho 2 bản tin bị mất, và cũng không có nhãn 1 nào: chặn gói không có nhãn.
- Kiểm thêm: lọc `mqtt.msgtype == 3 && ip.src == 10.6.56.41 && frame.number < 600` để thấy cả 4 cảm biến của InRow 13 cùng hở ở cùng chỗ.

### T7. Đêm thứ Năm: node tự ngắt kết nối, không phải chặn gói (notebook mục “Mất bản tin”)
File `capture_1910240000_thu.pcap`, mọi gói từ/tới InRow 13 sau 23:03 (bỏ các gói TCP ACK/FIN thuần).

| frame (No.) | giờ Madrid | gói | nội dung | dòng CSV (nguyên văn) |
|---|---|---|---|---|
| **14095** | 23:03:11 | 10.6.56.41:123 → 10.6.56.1:123 | UDP cổng 123 (NTP) | `14095;10.6.56.41;123;;;0` |
| **14097** | 23:03:56 | 10.6.56.41:49162 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=288, payload=19.91 | `14097;10.6.56.41;49162;133;288;0` |
| **14098** | 23:03:56 | 10.6.56.41:49158 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=288, payload=12.01 | `14098;10.6.56.41;49158;131;288;0` |
| **14099** | 23:03:56 | 10.6.56.41:49160 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=288, payload=15.96 | `14099;10.6.56.41;49160;132;288;0` |
| **14100** | 23:03:56 | 10.6.56.41:49164 → 10.6.56.1:1883 | type=PUBLISH, qos=1, dup=0, topic=IoT, msgid=288, payload=27.31 | `14100;10.6.56.41;49164;134;288;0` |
| **14101** | 23:03:56 | 10.6.56.1:1883 → 10.6.56.41:49158 | type=PUBACK, msgid=288 | `14101;10.6.56.1;1883;;;0` |
| **14102** | 23:03:56 | 10.6.56.1:1883 → 10.6.56.41:49162 | type=PUBACK, msgid=288 | `14102;10.6.56.1;1883;;;0` |
| **14103** | 23:03:56 | 10.6.56.1:1883 → 10.6.56.41:49160 | type=PUBACK, msgid=288 | `14103;10.6.56.1;1883;;;0` |
| **14104** | 23:03:56 | 10.6.56.1:1883 → 10.6.56.41:49164 | type=PUBACK, msgid=288 | `14104;10.6.56.1;1883;;;0` |
| **14145** | 23:08:56 | 10.6.56.41:49162 → 10.6.56.1:1883 | type=DISCONNECT | `14145;10.6.56.41;49162;;;0` |
| **14147** | 23:08:56 | 10.6.56.41:49158 → 10.6.56.1:1883 | type=DISCONNECT | `14147;10.6.56.41;49158;;;0` |
| **14151** | 23:08:56 | 10.6.56.41:49160 → 10.6.56.1:1883 | type=DISCONNECT | `14151;10.6.56.41;49160;;;0` |
| **14153** | 23:08:56 | 10.6.56.41:49164 → 10.6.56.1:1883 | type=DISCONNECT | `14153;10.6.56.41;49164;;;0` |
| **14273** | 23:20:32 | 10.6.56.41:123 → 10.6.56.1:123 | UDP cổng 123 (NTP) | `14273;10.6.56.41;123;;;0` |
| **14387** | 23:37:47 | 10.6.56.41:123 → 10.6.56.1:123 | UDP cổng 123 (NTP) | `14387;10.6.56.41;123;;;0` |
| **14501** | 23:55:20 | 10.6.56.41:123 → 10.6.56.1:123 | UDP cổng 123 (NTP) | `14501;10.6.56.41;123;;;0` |

Thấy được:
- 23:03:56: bản tin `msgid = 288` của cả 4 cảm biến, tức bản tin thứ 288 của phiên, và được PUBACK bình thường.
- 23:08:56: cả 4 cảm biến **chủ động gửi DISCONNECT**.
- Sau đó InRow 13 vẫn gửi NTP lúc 23:20, 23:37, 23:55: máy còn sống, chỉ thôi gửi nhiệt độ.
- So sánh: lọc `mqtt.msgtype == 14` trong file thứ Năm sẽ thấy 20 gói DISCONNECT: 4 gói lúc 23:08:56 của InRow 13 và 16 gói lúc 00:00:31 (các phiên của ngày thứ Tư đóng khi chuyển ngày).

### T8. 20 bản tin không được xác nhận PUBACK (notebook mục “Sức khoẻ tầng mạng”, mục “Trông như bất thường nhưng không phải”)
Đều là bản tin của **phiên hôm trước** đến sau nửa đêm.

| file | frame (No.) | giờ Madrid | giờ UTC | clientId (cảm biến) | msgid | payload (°C) | cách bản tin trước | dòng CSV (nguyên văn) |
|---|---|---|---|---|---|---|---|---|
| `capture_1910260000_sat.pcap` | **243** | 00:02:25 | 22:02:25 | 134 (TAR) | 293 | 25.26 | 142 s | `243;10.6.56.41;49172;134;293;0` |
| `capture_1910260000_sat.pcap` | **245** | 00:02:25 | 22:02:25 | 131 (TFEU) | 293 | 9.68 | 142 s | `245;10.6.56.41;49166;131;293;0` |
| `capture_1910260000_sat.pcap` | **249** | 00:02:25 | 22:02:25 | 133 (TAS) | 293 | 17.92 | 142 s | `249;10.6.56.41;49170;133;293;0` |
| `capture_1910260000_sat.pcap` | **253** | 00:02:25 | 22:02:25 | 132 (TFSU) | 293 | 13.64 | 142 s | `253;10.6.56.41;49168;132;293;0` |
| `capture_1910270000_sun.pcap` | **193** | 00:00:32 | 22:00:32 | 233 (TAS) | 289 | 20.01 | 30 s | `193;10.6.56.50;44530;233;289;0` |
| `capture_1910270000_sun.pcap` | **194** | 00:00:32 | 22:00:32 | 231 (TFEU) | 289 | 10.93 | 30 s | `194;10.6.56.50;44532;231;289;0` |
| `capture_1910270000_sun.pcap` | **201** | 00:00:32 | 22:00:32 | 234 (TAR) | 289 | 26.34 | 30 s | `201;10.6.56.50;44526;234;289;0` |
| `capture_1910270000_sun.pcap` | **205** | 00:00:32 | 22:00:32 | 232 (TFSU) | 289 | 14.79 | 30 s | `205;10.6.56.50;44528;232;289;0` |
| `capture_1910270000_sun.pcap` | **209** | 00:00:32 | 22:00:32 | 153 (TAS) | 289 | 20.03 | 30 s | `209;10.6.56.36;47634;153;289;0` |
| `capture_1910270000_sun.pcap` | **211** | 00:00:32 | 22:00:32 | 151 (TFEU) | 289 | 11.53 | 30 s | `211;10.6.56.36;47630;151;289;0` |
| `capture_1910270000_sun.pcap` | **215** | 00:00:32 | 22:00:32 | 152 (TFSU) | 289 | 15.20 | 30 s | `215;10.6.56.36;47632;152;289;0` |
| `capture_1910270000_sun.pcap` | **217** | 00:00:32 | 22:00:32 | 154 (TAR) | 289 | 27.22 | 30 s | `217;10.6.56.36;47636;154;289;0` |
| `capture_1910270000_sun.pcap` | **221** | 00:00:32 | 22:00:32 | 251 (TFEU) | 289 | 11.03 | 30 s | `221;10.6.56.34;40856;251;289;0` |
| `capture_1910270000_sun.pcap` | **222** | 00:00:32 | 22:00:32 | 253 (TAS) | 289 | 19.94 | 30 s | `222;10.6.56.34;40860;253;289;0` |
| `capture_1910270000_sun.pcap` | **227** | 00:00:32 | 22:00:32 | 252 (TFSU) | 289 | 15.13 | 30 s | `227;10.6.56.34;40858;252;289;0` |
| `capture_1910270000_sun.pcap` | **231** | 00:00:32 | 22:00:32 | 254 (TAR) | 289 | 26.72 | 30 s | `231;10.6.56.34;40862;254;289;0` |
| `capture_1910270000_sun.pcap` | **235** | 00:01:37 | 22:01:37 | 131 (TFEU) | 298 | 11.81 | 95 s | `235;10.6.56.41;49174;131;298;0` |
| `capture_1910270000_sun.pcap` | **239** | 00:01:37 | 22:01:37 | 132 (TFSU) | 298 | 15.79 | 95 s | `239;10.6.56.41;49180;132;298;0` |
| `capture_1910270000_sun.pcap` | **243** | 00:01:37 | 22:01:37 | 133 (TAS) | 298 | 20.01 | 95 s | `243;10.6.56.41;49176;133;298;0` |
| `capture_1910270000_sun.pcap` | **247** | 00:01:37 | 22:01:37 | 134 (TAR) | 298 | 27.36 | 95 s | `247;10.6.56.41;49178;134;298;0` |

Thấy được: `msgid` 289/293/298 vượt quá 288 là bản tin của phiên ngày hôm trước (phiên mới bắt đầu lại từ `msgid` 1 lúc 00:00:02). Lọc `frame.number <= 260 && mqtt.msgtype == 4` trong file thứ Bảy hoặc Chủ nhật: không có PUBACK nào cho các `msgid` này.

### T9. `keepalive` đổi theo ngày (notebook mục “MQTT”, mục “Trông như bất thường nhưng không phải”)
Gói CONNECT của cảm biến 131 mỗi ngày. Cột cổng TCP trong dòng CSV cũng là cổng của cảm biến 131 trong ngày đó, dùng cho bộ lọc `tcp.srcport == …`.

| file | frame (No.) | giờ Madrid | clientId | keepalive (s) | clean session | dòng CSV |
|---|---|---|---|---|---|---|
| `capture_1910210000_mon.pcap` | **125** | 00:00:02 | 131 | 300 | 1 | `125;10.6.56.41;49134;;;0` |
| `capture_1910220000_tue.pcap` | **119** | 00:00:02 | 131 | 18000 | 0 | `119;10.6.56.41;49146;;;0` |
| `capture_1910230000_wed.pcap` | **106** | 00:00:02 | 131 | 300 | 1 | `106;10.6.56.41;49150;;;0` |
| `capture_1910240000_thu.pcap` | **82** | 00:00:02 | 131 | 300 | 1 | `82;10.6.56.41;49158;;;0` |
| `capture_1910250000_fri.pcap` | **157** | 00:00:02 | 131 | 18000 | 0 | `157;10.6.56.41;49166;;;0` |
| `capture_1910260000_sat.pcap` | **105** | 00:00:02 | 131 | 18000 | 0 | `105;10.6.56.41;49174;;;0` |
| `capture_1910270000_sun.pcap` | **49** | 00:00:02 | 131 | 300 | 1 | `49;10.6.56.41;49182;;;0` |

Thứ Ba, thứ Sáu, thứ Bảy (3 ngày có chặn gói giữa phiên) dùng keepalive 18.000 s và clean session 0; các ngày khác 300 s và 1. Lọc `mqtt.msgtype == 1` trong file bất kỳ: cả 16 cảm biến (mọi tủ, kể cả tủ sạch) dùng cùng một giá trị, nên đây là cấu hình chung của phiên thu dữ liệu ngày đó, không phải dấu hiệu tấn công.

### T10. Đếm nhãn trong file CSV gốc (notebook mục “Nhãn”)
Đếm trực tiếp các dòng kết thúc bằng `;1` (tương đương `grep -c ';1$' <file>`).

| file nhãn | số dòng dữ liệu | số dòng kết thúc bằng `;1` | nhãn 1 đầu tiên (nguyên văn) | nhãn 1 cuối cùng (nguyên văn) |
|---|---|---|---|---|
| `capture_1910210000_labels.csv` | 14,431 | 0 | — | — |
| `capture_1910220000_labels.csv` | 14,398 | 0 | — | — |
| `capture_1910230000_labels.csv` | 14,524 | 104 | `2707;10.6.56.41;49152;133;51;1` | `3959;10.6.56.41;49154;132;76;1` |
| `capture_1910240000_labels.csv` | 14,538 | 56 | `2047;10.6.56.41;49162;133;38;1` | `2356;10.6.56.41;49164;134;51;1` |
| `capture_1910250000_labels.csv` | 14,544 | 192 | `3583;10.6.56.41;49166;131;58;1` | `10013;10.6.56.41;49170;133;201;1` |
| `capture_1910260000_labels.csv` | 14,630 | 192 | `3667;10.6.56.41;49174;131;63;1` | `10098;10.6.56.41;49178;134;206;1` |
| `capture_1910270000_labels.csv` | 14,518 | 0 | — | — |

Tổng 104 + 56 + 192 + 192 = **544**. Bài báo ghi 1.088 gói bất thường = 544 PUBLISH + 544 PUBACK đi kèm.

### T11. Ranh giới thời gian của mỗi file (notebook mục “Kiểm kê file”)

| file | gói | frame đầu: giờ UTC | giờ Madrid | frame cuối: giờ UTC | giờ Madrid |
|---|---|---|---|---|---|
| `capture_1910210000_mon.pcap` | 14,431 | 2019-10-20 22:00:02.449 | 2019-10-21 00:00:02 +0200 | 2019-10-21 21:59:58.876 | 2019-10-21 23:59:58 +0200 |
| `capture_1910220000_tue.pcap` | 14,398 | 2019-10-21 22:00:02.650 | 2019-10-22 00:00:02 +0200 | 2019-10-22 21:56:46.119 | 2019-10-22 23:56:46 +0200 |
| `capture_1910230000_wed.pcap` | 14,524 | 2019-10-22 22:00:01.966 | 2019-10-23 00:00:01 +0200 | 2019-10-23 21:59:50.119 | 2019-10-23 23:59:50 +0200 |
| `capture_1910240000_thu.pcap` | 14,538 | 2019-10-23 22:00:02.259 | 2019-10-24 00:00:02 +0200 | 2019-10-24 21:55:31.792 | 2019-10-24 23:55:31 +0200 |
| `capture_1910250000_fri.pcap` | 14,544 | 2019-10-24 22:00:02.474 | 2019-10-25 00:00:02 +0200 | 2019-10-25 21:57:25.221 | 2019-10-25 23:57:25 +0200 |
| `capture_1910260000_sat.pcap` | 14,630 | 2019-10-25 22:00:02.846 | 2019-10-26 00:00:02 +0200 | 2019-10-26 21:56:37.039 | 2019-10-26 23:56:37 +0200 |
| `capture_1910270000_sun.pcap` | 14,518 | 2019-10-26 22:00:02.108 | 2019-10-27 00:00:02 +0200 | 2019-10-27 21:55:31.656 | 2019-10-27 22:55:31 +0100 |

Thấy được: mỗi file bắt đầu lúc 22:00 UTC hôm trước = 00:00 giờ Madrid; file Chủ nhật kết thúc lúc 22:55 giờ Madrid (+0100) vì 27/10/2019 đổi sang giờ mùa đông.

---

## 5. Ánh xạ: mục notebook → bằng chứng

| Mục notebook | Khẳng định | Bảng |
|---|---|---|
| mục “Kiểm kê file” | file chia theo nửa đêm giờ Madrid; Chủ nhật đổi giờ | T11 |
| mục “File nhãn”, mục “Nhãn” | CSV: frame *n* ở dòng *n* + 1; 544 nhãn 1, chỉ InRow 13 | T3, T10 |
| mục “Tầng mạng” | số gói MQTT, UDP khớp Table 5 bài báo | mục 2.4 |
| mục “MQTT” | `clientId` chỉ ở CONNECT; QoS 1; `msgid` liên tục; keepalive đổi theo ngày | T1, T6, T9 |
| mục “Từ điển định danh” | IP ↔ tủ, chữ số cuối ↔ loại cảm biến; InRow 25 không có NTP | mục 1.4, mục 2.4 |
| mục “Nhịp gửi” | 16 cảm biến gửi cùng lúc, chu kỳ 300 s | T2 |
| mục “Sức khoẻ tầng mạng” | 20 PUBLISH không được PUBACK, đều lúc chuyển ngày | T8 |
| mục “Mất bản tin” | chặn gói = khoảng hở, cả 4 cảm biến, không nhãn | T6 |
| mục “Mất bản tin” | đêm thứ Năm là node tự ngắt kết nối | T7 |
| mục “Chèn bản tin” | chèn bản tin: 4 cảm biến cùng gửi, 30–104 s; bản tin 03:23:32 nhãn 0 | T4, T5 |
| mục “Sửa giá trị” | sửa giá trị: trừ cả tủ; có slot nhãn 1 không đổi giá trị | T3 |
| mục “Trông như bất thường nhưng không phải” | bản tin phiên cũ sau nửa đêm; keepalive | T8, T9 |

---

## 6. Nguồn tham khảo (đã đối chiếu nguyên văn)

Các thông số nghiệp vụ và chi tiết về dataset trong notebook đều lấy từ các nguồn dưới đây. Cột "chỗ cụ thể" ghi mục, bảng hoặc trang để mở ra đối chiếu.

| # | Nguồn | Dùng cho | Chỗ cụ thể |
|---|---|---|---|
| [1] | L. Vigoya, D. Fernandez, V. Carneiro, F. Cacheda, *Annotated Dataset for Anomaly Detection in a Data Center with IoT Sensors*, Sensors 2020, 20(13), 3745. https://pmc.ncbi.nlm.nih.gov/articles/PMC7374380/ | bối cảnh, môi trường thu dữ liệu, tấn công, số liệu | sự cố CITIC: mục 1.1; cảm biến NFC, NetBotz, 4 cảm biến InRow: mục 3.1; 14 ngày đo: mục 3.2; môi trường thu (Mosquitto, tcpdump, Scapy): mục 3.3; 3 kiểu tấn công, MQTT không xác thực, đổi thời gian chờ khi có chặn gói: mục 4.1; lịch tấn công theo ngày: mục 5; tổng số gói, flow 30 s, node có card mạng thứ hai: mục 5.1; Table 1 (thống kê dữ liệu thật): mục 3.2; Table 5: mục 5.1 |
| [2] | Repo dữ liệu gốc: https://github.com/dad-repository/dad | file dữ liệu, README lịch tấn công | `README.md` |
| [3] | B. Saridou, G. Bendiab, S. N. Shiaeles, B. K. Papadopoulos, *Thermal Management in Large Data Centers: Security Threats and Mitigation*, SSCC 2020, CCIS 1364, Springer. https://arxiv.org/abs/2108.13261 | tấn công vào hệ thống đo nhiệt là mối đe doạ có thật | tóm tắt (abstract) |
| [4] | ASHRAE TC 9.9, *2021 Equipment Thermal Guidelines for Data Processing Environments*, Reference Card (5th ed.). https://www.ashrae.org/file%20library/technical%20resources/bookstore/supplemental%20files/therm-gdlns-5th-r-e-refcard.pdf | vùng khuyến nghị 18–27 °C; cho phép A1 15–32 °C; biến thiên ≤ 5 °C/15 phút, ≤ 20 °C/giờ | Table 2.1 và chú thích f |
| [5] | M. K. Herrlin, *Data Center Air Management Research*, PG&E Emerging Technologies, Application Assessment Report #0912, 2010. https://datacenters.lbl.gov/sites/default/files/AirManagement_Herrlin2010.pdf | công thức RCI_HI, RCI_LO; thang: 100% lý tưởng, ~95% tốt, < 90% kém | trang 8/53 |
| [6] | K. VanCamp (Emerson), *Alarm Management By the Numbers*, Chemical Engineering, 3/2016 (bản in lại). https://www.emerson.com/is/content/emerson/en/corporate/news-and-events/articles/documents/alarm-management-by-the-numbers.pdf | chỉ tiêu cảnh báo theo EEMUA-191 / ISA-18.2 / IEC 62682: < 288 cảnh báo/ngày, 1–2 cảnh báo/10 phút, lụt = hơn 10 cảnh báo mới trong 10 phút | Table 1; đoạn định nghĩa alarm flood |
| [7] | Google, *Site Reliability Engineering*, chương *Monitoring Distributed Systems*. https://sre.google/sre-book/monitoring-distributed-systems/ | 4 tín hiệu vàng: latency, traffic, errors, saturation | mục *The Four Golden Signals* |
| [8] | I. Seaton, *The 4 Delta T's of Data Center Cooling: What You're Missing*, Upsite Technologies, 24/6/2015. https://www.upsite.com/blog/the-4-delta-ts-of-data-center-cooling-what-youre-missing | ΔT của tủ làm mát = chênh lệch khí cấp và khí hồi | đoạn "cooling unit ΔT" |
| [9] | N. Kroman, *Data Centers and Correct ΔT Control*, FlowCon International, 4/2025. https://flowcon.com/articles/data-centers-and-correct-dt-control | ΔT nước = chênh lệch nước cấp và nước hồi; "low ΔT syndrome" | đoạn định nghĩa ΔT |
| [10] | Exaflop LLC (Google), bằng sáng chế US8209993B2 *Warm water cooling*. https://patents.google.com/patent/US8209993B2/en | approach = nhiệt độ khí ra khỏi dàn trừ nhiệt độ nước vào dàn | phần mô tả (description) |
| [11] | Litmus, *How to Measure Industrial Data Quality: SLOs for Latency, Completeness and Freshness*. https://litmus.io/blog/how-to-measure-industrial-data-quality-slos-for-latency-completeness-and-freshness | định nghĩa độ tươi (freshness), độ đầy đủ (completeness), độ trễ (latency) | các mục định nghĩa |
| [12] | Wireshark, *Display Filter Reference: MQTT*. https://www.wireshark.org/docs/dfref/m/mqtt.html | tên trường lọc MQTT | toàn trang |

Những gì **không** có trong nguồn mà là kết luận của dự án (tính từ dữ liệu trong notebook): mọi ngưỡng phát hiện (1,5 P; 0,8 P; 3/6 chu kỳ; 0,8 °C), danh mục tín hiệu mục “Danh mục tín hiệu”, ánh xạ chữ số cuối `clientId` → loại cảm biến, phát hiện "node tự ngắt kết nối" đêm thứ Năm, và các đặc điểm dễ gây hiểu nhầm ở mục “Trông như bất thường nhưng không phải”.
