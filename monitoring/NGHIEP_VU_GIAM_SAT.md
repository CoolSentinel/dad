# Nghiệp vụ giám sát cảm biến làm mát: chuẩn ngành áp vào DAD

Tài liệu trả lời:
- cảm biến gửi bao lâu một lần;
- theo dõi chỉ số nào, ngưỡng bao nhiêu;
- cảnh báo thế nào để không thành "lụt cảnh báo";
- dashboard trình bày ra sao cho đúng chuẩn.

Mọi ngưỡng đều có nguồn (chuẩn ngành hoặc số đo trên DAD). Pipeline MongoDB tương ứng nằm ở `src/dad_mongo_pipelines.py`, đã chạy với toàn bộ dữ liệu DAD.

## 0. Các chuẩn được áp dụng

| Chuẩn / tài liệu | Lĩnh vực | Dùng cho phần nào |
|---|---|---|
| **ASHRAE TC 9.9**, *Thermal Guidelines*, bản 5 (2021) | môi trường thiết bị IT | ngưỡng nhiệt độ khí đầu vào, biến thiên nhiệt độ (mục 2.1) |
| **Rack Cooling Index (RCI)**, Herrlin 2005; DOE Air-Management Tool (LBNL) | hiệu quả làm mát | chỉ số tuân thủ nhiệt độ gom thành 1 con số (mục 2.1) |
| **ANSI/ISA-18.2**, **EEMUA 191**, IEC 62682 | quản lý cảnh báo trong công nghiệp | tần suất cảnh báo, phân bố mức ưu tiên, cảnh báo nhấp nháy (mục 4) |
| **ANSI/ISA-101.01** (High-Performance HMI) | thiết kế màn hình vận hành | 4 cấp màn hình, màu chỉ cho bất thường (mục 5) |
| **Google SRE**, chương *Monitoring Distributed Systems* | giám sát hệ thống phần mềm | 4 tín hiệu vàng, cảnh báo theo triệu chứng, "mọi cảnh báo phải hành động được" (mục 2.4, 4) |
| **Datadog**, *Monitor Best Practices*, *Monitor Configuration* | công cụ | multi-alert, ngưỡng phục hồi, xử lý mất dữ liệu, cửa sổ đánh giá (mục 1, 4.4) |
| Các chiều chất lượng dữ liệu IoT (đầy đủ, kịp thời, hợp lệ, nhất quán, không trùng) | chất lượng dữ liệu cảm biến | lớp "dữ liệu có đáng tin" (mục 2.3) |

## 1. Cảm biến gửi bao lâu một lần, và hệ quả cho cách giám sát

| Thông số | Giá trị |
|---|---|
| Chu kỳ gửi mỗi cảm biến | **5 phút** (đo được 300,1 giây; ở các tủ không bị tấn công, 99,95% khoảng cách giữa 2 bản tin lệch dưới 2 ms) |
| Số bản tin | **288/cảm biến/ngày**; 4.608/ngày cho 16 cảm biến (khoảng 3,2 bản tin/phút) |
| Khi tua ×60 cho demo | 5 giây/bản tin |

**Hệ quả khi cấu hình Datadog:**
- **Cửa sổ đánh giá ≥ 3 chu kỳ.** Datadog đánh giá monitor mỗi phút trên cửa sổ trượt. Với dữ liệu 5 phút, cửa sổ 5 phút chỉ có 1 điểm: một gai đơn lẻ (dữ liệu bình thường có gai ±2 °C) là đủ gây báo giả. Dùng **15–30 phút** ở thời gian thật, **15–30 giây** khi tua ×60.
- **Chọn hàm gộp đúng ý nghĩa.** `max` báo khi **bất kỳ** điểm nào vượt ngưỡng; `min` báo khi **mọi** điểm vượt ngưỡng (với ngưỡng "trên"; ngưỡng "dưới" thì đảo lại). Muốn "lệch kéo dài" thì dùng `min`/`avg`, không dùng `max`.
- **Mất dữ liệu là tín hiệu.** Monitor độ tươi đặt *On missing data* = **"Show NO DATA and notify"**. Monitor giá trị nhiệt độ đặt "Show last known status", để một lần trễ dữ liệu không làm nhiệt độ "về 0".
- **Gom theo ngày dùng UTC.** Làm tròn thời gian theo giờ địa phương sẽ lỗi ở ngày đổi giờ 27/10/2019 (đã gặp thật khi phân tích).

## 2. Bốn lớp chỉ số

```
Lớp 1  Phòng máy có an toàn không?         ASHRAE, RCI               → vận hành phòng máy
Lớp 2  Tủ làm mát có làm việc tốt không?   chênh nhiệt, approach      → vận hành phòng máy
Lớp 3  Dữ liệu cảm biến có đáng tin không? 5 chiều chất lượng + D1–D4 → cả hai
Lớp 4  Hệ thống giám sát có khoẻ không?    4 tín hiệu vàng (SRE)      → SRE
```

### 2.1 Lớp 1: an toàn phòng máy

ASHRAE áp cho **nhiệt độ khí đầu vào thiết bị IT**. DAD không có cảm biến ở rack, nên dùng **TAS** (khí cấp ra lối lạnh) làm đại diện; bài báo DAD cũng nói TAS "tương đương cảm biến mặt trước rack".

| Chỉ số | Công thức | Ngưỡng | Trên DAD |
|---|---|---|---|
| Nhiệt độ khí cấp | TAS | **khuyến nghị 18–27 °C**; cho phép (loại A1) 15–32 °C | 99,73% thời gian trong 18–27 °C; thấp nhất 17,9 °C |
| Biến thiên 15 phút | max − min trong 15 phút | **≤ 5 °C** | 0 lần vượt |
| Biến thiên 1 giờ | max − min trong 1 giờ | **≤ 20 °C** (lưu trữ băng từ: 5 °C) | lớn nhất 2,7 °C |
| **RCI_HI / RCI_LO** | 100 × (1 − Σ phần vượt ngưỡng khuyến nghị / ((ngưỡng cho phép − ngưỡng khuyến nghị) × n)) | **100% lý tưởng, ≥ 95% tốt, < 90% kém** | ≈ 100% mọi tủ mọi ngày; InRow 13 RCI_LO 98,4–99,5% vào ngày bị tấn công |

RCI gom hàng trăm số đo thành **một con số cho mỗi tủ mỗi ngày**. Đây là chỉ số tóm tắt hợp cho màn hình tổng quan và báo cáo quản lý.

### 2.2 Lớp 2: hiệu quả làm mát

| Chỉ số | Công thức | Ý nghĩa ngoài đời | DAD (trung bình ± độ lệch chuẩn) |
|---|---|---|---|
| ΔT khí | TAR − TAS | nhiệt IT thải ra mà tủ phải lấy đi. Giảm đột ngột: khí lạnh đi tắt về tủ (bypass) | 6,3–7,3 ± 0,08 °C |
| ΔT nước | TFSU − TFEU | nhiệt nước nhận được. **Thấp kéo dài** ("low ΔT syndrome"): bơm phải đẩy nhiều nước hơn, máy làm lạnh chạy kém hiệu quả | 3,7–4,1 ± 0,02–0,06 °C |
| Approach | TAS − TFEU | **tăng dần qua nhiều ngày** = dàn ống bẩn, quạt yếu | 8,1–8,9 ± 0,13–0,16 °C |
| Cân bằng nhiệt | ΔT khí / ΔT nước | nhiệt khí mất đi = nhiệt nước nhận vào, nên gần như hằng số. **Lệch = nghi một cảm biến hỏng** | 1,65–1,96 ± 0,01–0,02 |
| Thứ tự vật lý | TFEU < TFSU < TAS < TAR | sai thứ tự = cảm biến hỏng hoặc dữ liệu bị sửa | 100% đúng |

**Không đo được với DAD** (thiếu cảm biến); nên nhắc khi thuyết trình là hướng mở rộng:
- **Return Temperature Index (RTI)** (Herrlin): cần chênh nhiệt qua rack, để biết khí lạnh bị đi tắt hay khí nóng bị hút ngược;
- độ ẩm và điểm sương (ASHRAE cũng giới hạn);
- tốc độ quạt, độ mở van nước của tủ InRow;
- công suất điện, PUE.

> **Điểm quan trọng nhất:** tấn công sửa giá trị trong DAD trừ **cùng một lượng** trên cả 4 cảm biến. Vì vậy:
> - ΔT khí vẫn 7,32 °C, cân bằng nhiệt không đổi;
> - tỉ lệ TAS trong vùng ASHRAE chỉ giảm từ 99,7% xuống 97,2%;
> - RCI vẫn ≥ 98%, tức vẫn "tốt" theo thang Herrlin.
>
> **Lớp 1 và lớp 2 không thấy sự cố.** Đây là lý do phải có lớp 3.

### 2.3 Lớp 3: dữ liệu có đáng tin không (5 chiều chất lượng dữ liệu)

| Chiều | Chỉ số | Cách tính | Ngưỡng | Bắt được |
|---|---|---|---|---|
| **Kịp thời** (timeliness / freshness) | độ tươi | (bây giờ − lần nhận cuối) / P, gộp theo tủ | > 1,5P | chặn gói, mất kết nối, thiết bị treo |
| **Đầy đủ** (completeness) | % **ô 5 phút có dữ liệu** | số ô có ≥ 1 bản tin / 288 | < 99%/ngày; < 95%/giờ | mất gói kéo dài |
| **Không trùng** (uniqueness) | gửi dồn | khoảng cách < 0,8P trên cùng kết nối | ≥ 2 trong 2 chu kỳ | chèn bản tin, firmware lỗi |
| **Hợp lệ** (validity) | ngoài dải; đứng giá trị | ngoài dải đo thật ± 2 °C; ≥ 12 bản tin liên tiếp y hệt (DAD bình thường tối đa 4) | > 0 | giá trị rác, cảm biến treo |
| **Nhất quán** (consistency) | lệch baseline (D4); thứ tự vật lý; cân bằng nhiệt | xem notebook 02–03 | D4 ≥ 3/6 chu kỳ | **sửa giá trị**, cảm biến trôi |

**Đếm bản tin dễ che mất việc mất dữ liệu.** InRow 13 thứ Sáu nhận 292 bản tin/cảm biến (≥ 288, trông như 100%). Nhưng thực tế mất khoảng 100 bản tin và bị chèn bù. **Đếm theo ô 5 phút chỉ còn 94,8%.** Pipeline `completeness()` đếm theo ô.

**Điểm chất lượng dữ liệu cho mỗi tủ** (gợi ý trình bày): hiển thị 5 chiều trên dưới dạng 5 ô xanh/vàng/đỏ, thay vì gộp thành một con số. Gộp thành một điểm sẽ che mất chiều nào đang hỏng.

### 2.4 Lớp 4: hệ thống giám sát (4 tín hiệu vàng của SRE)

Google SRE: nếu chỉ đo được 4 thứ của một hệ thống, hãy đo **độ trễ, lưu lượng, lỗi, độ bão hoà**. Áp vào đường đi dữ liệu cảm biến:

| Tín hiệu vàng | Chỉ số cụ thể | Ngưỡng gợi ý | Căn cứ DAD |
|---|---|---|---|
| **Độ trễ** (latency) | thời gian thiết bị → MongoDB (p50, p95, p99, không dùng trung bình); PUBACK broker | ingest p99 > 2P; PUBACK p99 > 5 ms | PUBACK p50 0,17 ms, p99 0,6 ms |
| **Lưu lượng** (traffic) | bản tin/phút toàn site | lệch > 10% so với 16/P | bình thường 3,2/phút |
| **Lỗi** (errors) | lỗi ghi MongoDB, bản tin không parse được, PUBLISH không được ACK | > 0 ngoài khung 00:00 | 20 bản tin không ACK, đều lúc 00:00 |
| **Bão hoà** (saturation) | hàng đợi ingest; thời gian chạy 1 lượt phát hiện so với P | lượt phát hiện > 0,5P | pipeline < 1 giây trên cả tuần |

Với broker và ingest, dùng thêm phương pháp **USE** (Utilisation, Saturation, Errors cho từng tài nguyên): CPU, bộ nhớ, kết nối.

## 3. Sự cố nào, lớp nào bắt được

| Sự cố | Lớp 1 | Lớp 2 | Lớp 3 | Lớp 4 |
|---|---|---|---|---|
| Chặn gói / mất kết nối (DAD) | không | không | **kịp thời, đầy đủ** | có thể |
| Chèn bản tin (DAD) | không | không | **không trùng** | không |
| Sửa giá trị cả tủ (DAD) | yếu (RCI_LO ≈ 98–99%) | **không** | **nhất quán (D4)** | không |
| Một cảm biến hỏng/trôi | có thể | **có** (cân bằng nhiệt) | hợp lệ, nhất quán | không |
| Quá nhiệt thật | **có** | **có** | không | không |
| Ingest chậm / broker lỗi | không | không | kịp thời (cả site cùng lúc) | **có** |

## 4. Quản lý cảnh báo (ISA-18.2 / EEMUA 191 / SRE)

### 4.1 Nguyên tắc
1. **Mọi cảnh báo phải hành động được** (SRE): nếu nhận cảnh báo mà không cần làm gì, đó không phải cảnh báo. Đưa nó lên dashboard thay vì gửi thông báo.
2. **Cảnh báo theo triệu chứng, điều tra theo nguyên nhân** (SRE): gọi người khi có triệu chứng ("tủ 13 không gửi dữ liệu", "dữ liệu tủ 13 không đáng tin"). Nguyên nhân (broker, cổng, firmware) đặt trên dashboard và trong nội dung điều tra.
3. **Một sự cố, một cảnh báo:** 4 cảm biến cùng lệch là **một** sự cố của tủ, không phải 4 cảnh báo. Dùng **multi-alert theo `inrow`** của Datadog.
4. **Có độ trễ khi phục hồi** (hysteresis): ngưỡng phục hồi khác ngưỡng báo, để cảnh báo không nhấp nháy.

### 4.2 Chỉ tiêu cảnh báo và số đo trên DAD

Bảng chỉ tiêu theo tổng hợp của Emerson, dựa trên EEMUA 191, ISA-18.2, IEC 62682:

| Chỉ tiêu | Mục tiêu | Ngưỡng phải hành động | DAD, **cảnh báo thô** (mỗi bản tin/slot vi phạm) | DAD, **gộp thành sự cố** (theo tủ, cách nhau ≥ 20 phút) |
|---|---|---|---|---|
| Cảnh báo / người trực / ngày | < 288 | > 432 | 57 | **2,6** |
| Cảnh báo / 10 phút | 1–2 | > 3 | tối đa **41** | tối đa **1** |
| % khoảng 10 phút có > 10 cảnh báo ("lụt") | < 1% | > 5% | 0,89% (nhưng đỉnh 41) | **0%** |
| Cảnh báo nhấp nháy (chattering) | 0 | > 5 | D4 bật/tắt **14 lần** cho 6 sự cố | xử lý bằng ngưỡng phục hồi (mục 4.4) |
| Cảnh báo treo > 24 giờ | < 5/ngày | > 5 | 0 | 0 |
| Phân bố mức ưu tiên | ~80% thấp, ~15% trung bình, ~5% cao | cao > 15% | — | đặt mức theo bảng 4.3 |

**Kết luận:** bắn cảnh báo cho từng bản tin vi phạm sẽ gây **lụt cảnh báo** (41 cảnh báo trong 10 phút lúc bị chèn bản tin). **Gộp theo tủ thành sự cố** đưa về 2,6/ngày, tối đa 1 trong 10 phút, nằm trong chỉ tiêu. Đây là lập luận định lượng cho thiết kế "incident ở mức tủ".

### 4.3 Bảng hợp lý hoá cảnh báo (alarm rationalization)

ISA-18.2 yêu cầu mỗi cảnh báo được "hợp lý hoá": ghi rõ nguyên nhân, hậu quả nếu bỏ qua, người trực phải làm gì, trong bao lâu. Đây là **danh mục cảnh báo chính thức** của hệ thống:

| Mã | Cảnh báo | Nguyên nhân có thể | Hậu quả nếu bỏ qua | Hành động | Thời gian phản ứng | Mức | Tự động? | Điều kiện phục hồi |
|---|---|---|---|---|---|---|---|---|
| M1 | Tủ {inrow} không gửi dữ liệu | mất mạng, thiết bị treo, gói bị chặn | mù nhiệt độ của tủ; quá nhiệt không ai thấy | gửi lệnh kết nối lại; quá 3P thì cử người kiểm tra | < 15 phút | trung bình | có (kết nối lại) | độ tươi < 1,2P trong 3 chu kỳ |
| M2 | Tủ {inrow} gửi dồn bất thường | firmware lỗi, bị chèn bản tin | dữ liệu nhiễu, tải hệ thống | giới hạn tốc độ tại ingest | < 30 phút | thấp | có | 0 bản tin dồn trong 3 chu kỳ |
| M3 | Dữ liệu tủ {inrow} không đáng tin | cấu hình sai, bị sửa dữ liệu | **làm mát hành động sai → quá nhiệt** (sự cố CITIC) | xem bằng chứng; **duyệt cách ly**; kiểm tra tại chỗ | **< 5 phút** | **cao** | không (cần người duyệt) | `neg_count6` = 0 trong 3 chu kỳ |
| M4 | Cảm biến {client_id} lệch baseline | cảm biến trôi hoặc hỏng | sai số đo kéo dài | mở ticket bảo trì | trong ngày | thấp | có (ticket) | `neg_count6` = 0 |
| M5 | Vi phạm vật lý / ngoài dải ở tủ {inrow} | cảm biến hỏng, lỗi đơn vị, dữ liệu bị sửa | dữ liệu sai | cách ly cảm biến, kiểm tra | < 15 phút | cao | không | 3 chu kỳ không vi phạm |
| M6 | Đường đi dữ liệu chậm | ingest quá tải, MongoDB chậm | mọi cảnh báo khác bị trễ | xem trace; khởi động lại hoặc scale | < 15 phút | trung bình | không | ingest p99 < P |
| M8 | Nhiệt độ khí cấp tủ {inrow} ngoài 18–27 °C | quá tải nhiệt, làm mát yếu | thiết bị IT quá nhiệt | kiểm tra tải và tủ; cân bằng tải | < 15 phút | cao nếu ngoài 15–32 °C; trung bình nếu chỉ ngoài 18–27 °C | không | trong vùng 30 phút |

Theo phân bố khuyến nghị (~80/15/5), phần lớn cảnh báo phải là mức **thấp** (M2, M4). Mức **cao** chỉ dành cho những gì đe doạ an toàn phòng máy (M3, M5, M8 ngoài vùng cho phép).

### 4.4 Cấu hình Datadog tương ứng
- **Tiêu đề rõ ràng**, ví dụ `[P1] Dữ liệu tủ {{inrow.name}} không đáng tin (D4)`.
- **Multi-alert** `by {inrow}`: một monitor, mỗi tủ một cảnh báo riêng.
- **Ngưỡng cảnh báo và ngưỡng phục hồi**, ví dụ M3: alert ≥ 3, warning ≥ 2, **recovery ≤ 0**, để chống nhấp nháy.
- **Nội dung cảnh báo có ngữ cảnh:** bằng chứng (`kinds`, `drop_c`, `sensors`), link dashboard đã lọc theo tủ, link runbook, `incident_id`.
- **Metadata:** `priority`, `team`, tag `layer:integrity|facility|platform`.
- **Mất dữ liệu:** M1 dùng "Show NO DATA and notify"; các monitor giá trị dùng "Show last known status".

## 5. Thiết kế dashboard theo ISA-101

### 5.1 Bốn cấp màn hình

ISA-101 chia màn hình vận hành thành 4 cấp, đi từ tổng quan tới chi tiết. Áp vào hệ thống:

| Cấp ISA-101 | Màn hình | Người xem | Nội dung | Widget Datadog |
|---|---|---|---|---|
| **1. Tổng quan** | *Site Overview* | mọi người, màn hình lớn | **chỉ KPI và bất thường**: 4 ô trạng thái tủ; số sự cố đang mở; RCI hôm nay; độ đầy đủ dữ liệu 24 giờ; MTTD/MTTR gần nhất | Monitor Summary, Query Value, SLO |
| **2. Theo khu vực** | *Cooling* và *Data Integrity* | vận hành phòng máy | TAS 4 tủ với nền 18–27 °C; ΔT khí, ΔT nước, approach; heatmap độ tươi 16 cảm biến; D4 theo tủ có vạch ngưỡng | Timeseries (có marker ngưỡng), Heatmap, Top List |
| **3. Chi tiết tủ** | *InRow {inrow}* (template variable `$inrow`) | người đang xử lý | 4 cảm biến của tủ; cân bằng nhiệt; lịch sử sự cố và hành động; trạng thái `quality` | Timeseries, Event Timeline, Table |
| **4. Chẩn đoán** | *Platform* và *Incident* | SRE | độ trễ ingest p50/p95/p99; PUBACK; lỗi theo service; log stream lọc `incident_id`; trace chậm nhất | Distribution, Log Stream, Trace/Service Map |

**Điều hướng:** mỗi ô ở cấp 1 có link sang cấp 2 hoặc 3 đã lọc sẵn. Từ cảnh báo, link thẳng tới cấp 3 của đúng tủ.

### 5.2 Nguyên tắc trình bày (ISA-101 + thực hành tốt)
- **Nền trung tính, màu chỉ dành cho bất thường.** Trạng thái bình thường hiển thị xám hoặc trung tính. Vàng = cảnh báo, đỏ = nghiêm trọng, xám đậm = không có dữ liệu. Không dùng đỏ hoặc xanh lá cho trạng thái bình thường, để mắt người trực chỉ dừng ở chỗ có vấn đề.
- **Luôn kèm chữ và biểu tượng**, không chỉ dùng màu: người mù màu, màn hình in đen trắng.
- **Hiển thị bối cảnh, không chỉ con số:** mỗi biểu đồ có vạch ngưỡng hoặc nền vùng cho phép. Con số "20,1 °C" đứng một mình không cho biết tốt hay xấu.
- **Xu hướng quan trọng hơn giá trị tức thời:** approach tăng dần trong nhiều tuần mới là dấu hiệu bảo trì, nên cấp 2 hiển thị 7–30 ngày cho các chỉ số này.
- **Tách màn hình theo người xem:** tổng quan cho quản lý không chứa từng số đo cảm biến. Trộn hai nhóm thì nhóm nào cũng khó dùng.
- **Event sự cố đặt chồng lên mọi biểu đồ**, để thấy ngay quan hệ giữa nhiệt độ, nhịp gửi và hành động xử lý.
- **Làm mới:** 1 phút ở thời gian thật (dữ liệu đổi 5 phút một lần); 5–10 giây khi demo tua ×60.

## 6. Pipeline MongoDB có sẵn

| Hàm | Lớp | Kết quả trên DAD |
|---|---|---|
| `cooling_kpis()` | 1, 2 | ΔT khí, ΔT nước, approach, cân bằng nhiệt, cờ ASHRAE theo tủ và slot |
| `rci()` | 1 | RCI_HI, RCI_LO theo tủ và ngày (UTC); ≈ 100%, InRow 13 RCI_LO 98,4–99,5% khi bị tấn công |
| `change_window()` | 1 | biến thiên ASHRAE; 0 lần vượt 5 °C/15 phút |
| `completeness()` | 3 | đếm **ô 5 phút**; InRow 13 thứ Sáu 94,8% |
| `silence_now()`, `d1_silence()` | 3 | bắt 5/5 lần chặn gói |
| `d2_burst()` | 3 | bắt 3/3 lần chèn bản tin |
| `d4_node()`, `d4_sensor()` | 3 | bắt 6/6 cửa sổ sửa giá trị |
| `stuck_sensor()`, `range_check()`, `physics()` | 3 | 0 vi phạm trên dữ liệu bình thường |
| `investigate()` | sự cố | loại, số bản tin mất/thừa, mức trừ, số cảm biến; khớp 11/11 sự cố |

Khi gộp theo ngày bằng MongoDB (UTC), ngày đầu và ngày cuối của tập dữ liệu chỉ có một phần (file DAD chia theo giờ Tây Ban Nha), nên độ đầy đủ ở hai ngày này thấp vì bị cắt ngày, không phải vì mất dữ liệu.

## 6b. Datadog đã được dùng trong lĩnh vực này chưa

Tra cứu tài liệu chính thức của Datadog (10/2026):

| Mảng | Datadog có gì | Áp vào bài |
|---|---|---|
| **Thiết bị hạ tầng vật lý qua SNMP** (Network Device Monitoring) | profile có sẵn cho **APC** (UPS), **Vertiv**, **Avtech** (cảm biến môi trường), PDU **Eaton, Raritan, CyberPower, Tripp Lite**. **Không** có profile riêng cho APC NetBotz hay tủ làm mát InRow; NetBotz dùng MIB riêng (theo Schneider), nên phải tự viết *custom profile* | DAD không có SNMP. Nêu như hướng mở rộng: thiết bị thật (NetBotz, InRow) đưa vào Datadog bằng custom SNMP profile |
| **IoT / thiết bị biên** | *Edge Device Monitoring* (trước là IoT Agent); tích hợp Azure IoT Hub / IoT Edge, AWS IoT, Google Cloud IoT; gộp metric theo tag, host map cho cả đội thiết bị | cách làm phổ biến là **metric tuỳ biến qua DogStatsD/API, gắn tag** theo thiết bị, đúng như thiết kế `dad.*` với tag `inrow`, `sensor` |
| **Broker MQTT** | tích hợp chính thức cho **EMQX** và **HiveMQ** (số kết nối, thông lượng bản tin). **Không** có tích hợp chính thức cho Mosquitto; muốn thì chạy Prometheus exporter cho Mosquitto rồi để Agent đọc bằng OpenMetrics check | nếu muốn có metric broker "chuẩn Datadog" cho lớp 4, cân nhắc dùng **EMQX** thay Mosquitto |
| **Trường hợp thực tế gần nhất** | **Charm Industrial** (case study của Datadog): cảm biến nhiệt độ, áp suất trên thiết bị công nghiệp; dashboard và cảnh báo theo ngưỡng an toàn; phát hiện **áp suất tăng dần trong một tháng** (tắc dần) trước khi hỏng | giống ý tưởng "approach tăng dần = cần bảo trì" (mục 2.2): giá trị của xu hướng dài hạn |
| **Phần cứng trong data center** | *Hardware Sentry* (Marketplace): nhiệt độ, phần cứng máy chủ, dashboard theo site / phòng máy | xác nhận Datadog được dùng cho góc nhìn "theo phòng máy" |

**Kết luận:** trong data center, giám sát cơ điện (làm mát, điện) thường do phần mềm DCIM/BMS chuyên dụng đảm nhận (Schneider EcoStruxure, Sunbird, Vertiv…); Datadog mạnh ở IT, ứng dụng và đường đi dữ liệu. Bài của đội đặt Datadog làm **lớp quan sát hợp nhất**: dữ liệu cảm biến (lớp 1–3) và sức khoẻ đường đi dữ liệu (lớp 4) trên **cùng một nền tảng**, liên kết bằng tag và trace. Hướng này có tiền lệ (Edge Monitoring, Charm Industrial), nhưng chưa phổ biến cho làm mát data center, nên là điểm sáng tạo hợp lý để nêu khi thuyết trình.

## 7. Nguồn

- ASHRAE TC 9.9, *Thermal Guidelines for Data Processing Environments*, 5th ed., reference card, Table 2.1 và chú thích f: https://www.ashrae.org/file%20library/technical%20resources/bookstore/supplemental%20files/therm-gdlns-5th-r-e-refcard.pdf
- M. Herrlin, *Airflow and Cooling Performance of Data Centers* (RCI, RTI, SHI), LBNL / PG&E 2010: https://datacenters.lbl.gov/sites/default/files/AirManagement_Herrlin2010.pdf
- Emerson, *Alarm management by the numbers* (bảng chỉ tiêu theo EEMUA 191 / ISA-18.2 / IEC 62682): https://www.emerson.com/is/content/emerson/en/corporate/news-and-events/articles/documents/alarm-management-by-the-numbers.pdf
- Google SRE Book, *Monitoring Distributed Systems*: https://sre.google/sre-book/monitoring-distributed-systems/
- Datadog, *Monitor Best Practices* và *Configure Monitors*: https://docs.datadoghq.com/monitors/guide/monitor_best_practices/ , https://docs.datadoghq.com/monitors/configuration/
- ISA-101 (tổng hợp thứ cấp; nên đối chiếu bản chuẩn ANSI/ISA-101.01-2015): https://ladx.ai/resources/isa-101-hmi-design
- Litmus, *How to Measure Industrial Data Quality: SLOs for Latency, Completeness and Freshness*: https://litmus.io/blog/how-to-measure-industrial-data-quality-slos-for-latency-completeness-and-freshness
- Upsite, *The 4 Delta T's of Data Center Cooling*: https://www.upsite.com/blog/the-4-delta-ts-of-data-center-cooling-what-youre-missing
- FlowCon, *Data Centers and Correct ΔT Control*: https://flowcon.com/articles/data-centers-and-correct-dt-control
- Datadog, *Supported Devices* (Network Device Monitoring): https://docs.datadoghq.com/network_monitoring/devices/supported_devices/
- Datadog, *Edge Monitoring*: https://www.datadoghq.com/solutions/edge-monitoring/
- Datadog, tích hợp EMQX: https://docs.datadoghq.com/integrations/emqx/ ; HiveMQ: https://docs.datadoghq.com/integrations/hivemq/
- Datadog case study, Charm Industrial: https://www.datadoghq.com/case-studies/charm/
