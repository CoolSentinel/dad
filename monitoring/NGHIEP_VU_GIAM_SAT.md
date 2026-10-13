# Nghiệp vụ giám sát: từ 4 cảm biến, cái gì đáng theo dõi

Tài liệu này trả lời: cảm biến gửi bao lâu một lần, theo dõi những chỉ số nào, mỗi chỉ số nói lên điều gì ngoài đời, ngưỡng bao nhiêu, và đặt lên dashboard ra sao. Các số liệu được tính trên dữ liệu DAD; pipeline MongoDB tương ứng nằm ở `src/dad_mongo_pipelines.py`.

## 1. Cảm biến gửi bao lâu một lần

| Thông số | Giá trị | Nguồn |
|---|---|---|
| Chu kỳ gửi của mỗi cảm biến | **5 phút** (đo được 300,1 giây; ở các tủ không bị tấn công, 99,95% khoảng cách giữa hai bản tin lệch dưới 2 ms) | PCAP; bài báo mục 3.1 |
| Số bản tin mỗi cảm biến mỗi ngày | **288** | |
| Toàn hệ thống (16 cảm biến) | 4.608 bản tin/ngày, khoảng **3,2 bản tin/phút** | |
| Khi tua ×60 cho demo | mỗi cảm biến **5 giây** một lần | |

**Hệ quả với việc giám sát** (điều người mới hay bỏ qua):
- **Không thể phát hiện nhanh hơn một chu kỳ.** Với dữ liệu 5 phút, cảnh báo sớm nhất là khoảng 5 phút sau sự cố. Notebook 03 cho thấy D4 cần 10–28 phút.
- **Cửa sổ đánh giá của monitor phải dài hơn vài chu kỳ.** Monitor Datadog kiểu `last_5m` trên dữ liệu 5 phút chỉ có 1 điểm, nên rất dễ báo giả hoặc "no data". Ở thời gian thật nên dùng 15–30 phút trở lên. Khi tua ×60, chia các cửa sổ này cho 60.
- **"Không có dữ liệu" là một tín hiệu**, không phải lỗi hiển thị. Cảm biến im quá 1,5 chu kỳ (7,5 phút) là sự cố.
- **Dashboard không cần làm mới mỗi giây.** Dữ liệu thật đổi mỗi 5 phút; làm mới khoảng 1 phút là đủ. Với demo tua ×60 thì làm mới 5–10 giây.

## 2. Bốn lớp giám sát

Một hệ thống giám sát cảm biến làm mát thật có 4 lớp. Mỗi lớp trả lời một câu hỏi khác nhau và phục vụ một người khác nhau.

```
Lớp 1  Phòng máy có an toàn không?        (vận hành phòng máy)   ← nhiệt độ, chuẩn ASHRAE
Lớp 2  Tủ làm mát có làm việc tốt không?  (vận hành phòng máy)   ← chênh nhiệt, hiệu quả dàn ống
Lớp 3  Dữ liệu cảm biến có đáng tin không? (cả hai)               ← nhịp gửi, toàn vẹn, giá trị bất thường
Lớp 4  Hệ thống giám sát có khoẻ không?   (SRE)                  ← broker, ingest, database
```

### Lớp 1: phòng máy có an toàn không (chuẩn ASHRAE)

ASHRAE TC 9.9 (bản 5, 2021) là chuẩn ngành về môi trường cho thiết bị IT. Nó áp lên **nhiệt độ khí đầu vào thiết bị**, tương ứng với **TAS** (khí cấp ra lối lạnh).

| Chỉ số | Công thức | Ngưỡng | Trên DAD |
|---|---|---|---|
| Nhiệt độ khí cấp | TAS | **khuyến nghị 18–27 °C**; cho phép (loại A1) 15–32 °C | 99,73% thời gian nằm trong 18–27 °C; thấp nhất 17,9 °C (gai đơn lẻ) |
| Biến thiên 15 phút | max − min của TAS trong 15 phút | **≤ 5 °C** | 0 lần vượt |
| Biến thiên 1 giờ | max − min trong 1 giờ | **≤ 20 °C** (thiết bị lưu băng từ: 5 °C) | lớn nhất 2,7 °C |
| Nhiệt độ khí hồi | TAR | không có chuẩn cứng; dùng để tính chênh nhiệt (lớp 2) | ≈ 26,3–27,3 °C |

- **Vì sao TAS quan trọng nhất:** đó là khí máy chủ hút vào. TAS cao thì máy chủ nóng. TAS thấp *một cách giả tạo*, như trong tấn công DAD, khiến hệ thống tưởng phòng đang mát mà giảm làm lạnh.
- **Chỉ số KPI cho quản lý:** % thời gian TAS nằm trong vùng khuyến nghị (mục tiêu ≥ 99%).

### Lớp 2: tủ làm mát có làm việc tốt không

Đây là các chỉ số người vận hành cơ điện thật sự theo dõi. Chúng được **tính ra** từ 4 cảm biến; không cảm biến nào đo trực tiếp.

| Chỉ số | Công thức | Ý nghĩa ngoài đời | DAD (trung bình ± độ lệch chuẩn) |
|---|---|---|---|
| **Chênh nhiệt khí** (ΔT khí) | TAR − TAS | lượng nhiệt mà thiết bị IT thải ra, tủ phải lấy đi. Tăng = tải IT tăng; giảm đột ngột = khí lạnh đi tắt về tủ (bypass airflow) | 6,3–7,3 ± 0,08 °C |
| **Chênh nhiệt nước** (ΔT nước) | TFSU − TFEU | nhiệt nước nhận được. **ΔT nước thấp kéo dài** ("low ΔT syndrome") nghĩa là bơm phải đẩy nhiều nước hơn, máy làm lạnh chạy kém hiệu quả | 3,7–4,1 ± 0,02–0,06 °C |
| **Approach** | TAS − TFEU | khí cấp còn ấm hơn nước vào bao nhiêu. **Tăng dần theo ngày** = dàn ống bẩn, quạt yếu, cần bảo trì | 8,1–8,9 ± 0,13–0,16 °C |
| **Cân bằng nhiệt khí–nước** | ΔT khí / ΔT nước | nhiệt khí mất đi phải bằng nhiệt nước nhận được, nên tỉ số này gần như cố định | 1,65–1,96 ± **0,01–0,02** |
| **Thứ tự vật lý** | TFEU < TFSU < TAS < TAR | sai thứ tự = gần như chắc chắn một cảm biến hỏng hoặc dữ liệu bị sửa | 100% đúng |

**Dùng để phát hiện cảm biến hỏng lẻ:** khi **một** cảm biến bắt đầu trôi hoặc hỏng, ΔT và tỉ số cân bằng nhiệt lệch ngay, vì 3 cảm biến kia không đổi. Tỉ số có độ lệch chuẩn chỉ 0,01–0,02, nên ngưỡng ±0,15 vẫn rất an toàn.

> **Lưu ý quan trọng cho DAD:** tấn công sửa giá trị trừ **cùng một lượng** trên cả 4 cảm biến. Vì vậy ΔT khí (7,32 → 7,32 °C) và tỉ số cân bằng nhiệt **không đổi**, còn tỉ lệ TAS trong vùng ASHRAE chỉ giảm từ 99,7% xuống 97,2%. **Chỉ nhìn lớp 1 và lớp 2 thì không thấy sự cố.** Đó là lý do bắt buộc phải có lớp 3.

### Lớp 3: dữ liệu cảm biến có đáng tin không

Đây là lớp bắt được cả 3 kiểu bất thường của DAD (notebook 02, 03).

| Chỉ số | Cách tính | Ngưỡng (P = chu kỳ) | Bắt được gì |
|---|---|---|---|
| **Độ tươi** (freshness) | (bây giờ − lần nhận cuối) / P | > 1,5P → cảnh báo; gộp theo tủ | chặn gói, mất kết nối, thiết bị treo |
| **Độ đầy đủ** (completeness) | số bản tin nhận / số bản tin kỳ vọng (288/ngày) | < 99% trong ngày; < 95% trong 1 giờ | mất gói kéo dài; DAD thứ Ba: 278/288 |
| **Gửi dồn** | khoảng cách tới bản tin trước < 0,8P, cùng kết nối | ≥ 2 trong 2 chu kỳ | chèn bản tin, firmware lỗi |
| **Lệch khỏi baseline** (D4) | giá trị − trung vị 1 ngày trước; đếm chu kỳ lệch < −0,8 °C | ≥ 3 trong 6 chu kỳ | **sửa giá trị** (cả 11 cửa sổ sự cố DAD bắt được cùng D1, D2) |
| **Đứng giá trị** (stuck) | n bản tin liên tiếp y hệt nhau | n ≥ 12 (1 giờ) | cảm biến treo, gửi lại giá trị cũ. DAD bình thường dài nhất 4 bản tin liên tiếp |
| **Ngoài dải hợp lệ** | giá trị ngoài dải đo thật ± 2 °C | xem `devices.valid_range_c` | lỗi đơn vị, giá trị rác |
| **Phạm vi ảnh hưởng** | số cảm biến cùng lệch trong một tủ | 1/4 → nghi hỏng cảm biến; 4/4 → sự cố cấp tủ | phân biệt **hỏng** với **bị can thiệp** |

### Lớp 4: hệ thống giám sát có khoẻ không (SRE)

Lớp này để trả lời "lỗi ở thiết bị hay ở chính hệ thống của mình", và là phần Datadog APM/Logs phát huy tác dụng.

| Chỉ số | Ngưỡng gợi ý | Căn cứ trên DAD |
|---|---|---|
| Độ trễ broker xác nhận (PUBACK) | p99 > 5 ms | bình thường p50 0,17 ms, p99 0,6 ms |
| Bản tin không được xác nhận | > 0 ngoài khung chuyển ngày | 20 bản tin, đều lúc 00:00 |
| Số lần kết nối lại / cảm biến / ngày | > 1 | bình thường đúng 1 lần lúc 00:00 |
| Cấu hình phiên thay đổi (keepalive) | khác hôm trước → thông báo | DAD có đổi theo ngày (dấu vết của bộ sinh dữ liệu) |
| Độ trễ ingest (thiết bị → MongoDB) | > 2P | tự đo khi build |
| Thời gian chạy một lượt phát hiện | > P | pipeline MongoDB hiện < 1 giây trên cả tuần dữ liệu |
| Lỗi trong log ingest / detector / remediator | > 0 | — |

## 3. Chỉ số nào bắt được loại sự cố nào

| Sự cố | Lớp 1 (ASHRAE) | Lớp 2 (ΔT, cân bằng nhiệt) | Lớp 3 (toàn vẹn) | Lớp 4 (hạ tầng) |
|---|---|---|---|---|
| Chặn gói / mất kết nối (DAD) | không | không | **độ tươi, độ đầy đủ** | có thể (nếu do broker) |
| Chèn bản tin (DAD) | không | không | **gửi dồn** | không |
| Sửa giá trị cả tủ (DAD) | yếu (TAS chạm dưới 18 °C vài lần) | **không** | **lệch baseline (D4)** | không |
| Một cảm biến hỏng / trôi | có thể | **có** (ΔT, cân bằng nhiệt) | ngoài dải, đứng giá trị | không |
| Quá nhiệt thật (tải IT tăng, làm mát yếu) | **có** | **có** (ΔT khí tăng, approach tăng) | không | không |
| Ingest chậm / broker lỗi | không | không | độ tươi (cả site cùng lúc) | **có** |

Bảng này là lập luận mạnh khi thuyết trình: **mỗi lớp bắt một loại sự cố mà lớp khác bỏ sót**. DAD chỉ chứa 3 dòng đầu; các dòng còn lại là năng lực cần có ngoài thực tế. Có thể tạo thêm khi demo, ví dụ cố ý làm 1 cảm biến trôi, hoặc tắt ingest.

## 4. Dashboard: ai xem gì

Không nên dồn mọi thứ vào một màn hình cho mọi người. Thực tế thường có một màn hình tổng quan và các màn hình chuyên sâu.

| Màn hình | Người xem | Widget chính | Làm mới |
|---|---|---|---|
| **Tổng quan** | mọi người, trên màn hình lớn | đèn trạng thái 4 tủ (xanh/vàng/đỏ) · số sự cố đang mở · % TAS trong vùng ASHRAE hôm nay · MTTD/MTTR gần nhất | 1 phút (demo: 5 giây) |
| **Phòng máy** | vận hành cơ điện | TAS 4 tủ với dải 18–27 °C tô nền · ΔT khí, ΔT nước, approach theo tủ · cân bằng nhiệt · bản đồ phòng máy (theo Hình 1) | 1 phút |
| **Chất lượng dữ liệu** | cả hai | độ tươi theo cảm biến (heatmap 16 ô) · độ đầy đủ 24 giờ · gửi dồn · D4 theo tủ, có vạch ngưỡng · cảm biến đang `quality=suspect` | 1 phút |
| **Hệ thống** | SRE | độ trễ ingest · PUBACK p99 · số bản tin mỗi phút · lỗi log theo service · trace chậm nhất | 30 giây |
| **Sự cố** | người đang xử lý | timeline sự cố (event Datadog) · bằng chứng (loại, mất/thừa, mức trừ, số cảm biến) · log và trace lọc theo `incident_id` · hành động đã làm | theo sự kiện |

**Nguyên tắc trình bày:**
- **Màu theo trạng thái, không theo cảm biến:** xanh = ổn, vàng = cảnh báo, đỏ = nghiêm trọng, xám = không có dữ liệu. Luôn kèm chữ, không chỉ dùng màu.
- **Mỗi biểu đồ có vạch ngưỡng** khớp với monitor tương ứng, để người xem hiểu vì sao có cảnh báo.
- **Tô vùng khuyến nghị ASHRAE** (18–27 °C) làm nền biểu đồ TAS.
- **Đặt event sự cố lên trục thời gian** của mọi biểu đồ, để thấy ngay nhiệt độ, nhịp gửi và hành động xử lý liên quan nhau thế nào.

## 5. Ai được báo, mức nào

| Mức | Khi nào | Ai nhận | Ví dụ |
|---|---|---|---|
| **P1, khẩn** | an toàn phòng máy hoặc dữ liệu điều khiển không đáng tin | vận hành phòng máy, ngay lập tức | D4 cả tủ; sai thứ tự vật lý; TAS ngoài 15–32 °C; biến thiên > 5 °C/15 phút |
| **P2, trong ca trực** | mất hoặc nhiễu dữ liệu, chưa ảnh hưởng an toàn | người trực ca | tủ im lặng > 1,5P; gửi dồn; ingest chậm |
| **P3, theo dõi** | xu hướng xấu dần, cảnh báo sớm | ticket, xem trong giờ hành chính | approach tăng dần; ΔT nước thấp kéo dài; D4 trên 1 cảm biến; keepalive thay đổi |

## 6. Pipeline MongoDB có sẵn

Tất cả trong `src/dad_mongo_pipelines.py`, đã chạy trên MongoDB 8.0.4 với toàn bộ dữ liệu DAD:

| Hàm | Lớp | Kết quả trên DAD |
|---|---|---|
| `cooling_kpis()` | 1, 2 | ΔT khí, ΔT nước, approach, cân bằng nhiệt, cờ ASHRAE theo tủ và slot; khớp số liệu ở mục 2 |
| `change_window()` | 1 | 0 lần vượt 5 °C/15 phút |
| `physics()`, `range_check()` | 2, 3 | 0 vi phạm |
| `silence_now()`, `d1_silence()` | 3 | bắt 5/5 lần chặn gói |
| `d2_burst()` | 3 | bắt 3/3 lần chèn gói |
| `d4_node()`, `d4_sensor()` | 3 | bắt 6/6 cửa sổ sửa giá trị |
| `stuck_sensor()` | 3 | 0 lần (n = 12) |
| `investigate()` | sự cố | loại, số bản tin mất/thừa, mức trừ, số cảm biến; khớp cả 11 sự cố |

Nguồn chuẩn ASHRAE: *Thermal Guidelines for Data Processing Environments*, 5th ed., reference card, Table 2.1 và chú thích f (ASHRAE TC 9.9, 2021).
