# Tự host MongoDB trên EC2

Thể lệ chỉ yêu cầu "MongoDB là nền tảng dữ liệu vận hành chính", **không bắt buộc Atlas**. Tự host trên EC2 là hợp lệ.

Các bước dưới đây đã được chạy thử với MongoDB 8.0.4: replica set một node, bật xác thực có keyFile, nạp dữ liệu `data/mongo`, chạy pipeline D4 (85 slot, đúng như notebook 04), mở Change Stream trên `incidents`, kiểm tra quyền user.

## 1. EC2 hay Atlas?

| | **EC2 tự host** | **Atlas** |
|---|---|---|
| Hợp lệ với thể lệ | có | có |
| Time Series, `$setWindowFields`, `$median`, TTL | có (cần ≥ 7.0; dùng 8.0) | có |
| Change Streams | có, **nhưng phải chạy replica set** (mục 4) | có sẵn |
| Atlas Search, Vector Search | **không** (bài này không cần) | có |
| Datadog theo dõi chính MongoDB | cài Agent ngay trên EC2; bật được **Database Monitoring** (hỗ trợ Community 4.4–8.0, Agent ≥ 7.58) | dùng tích hợp Atlas hoặc Agent kết nối từ xa |
| Công sức | tự cài, tự bảo mật, tự backup | gần như không |

**Khuyến nghị:** nếu đội đã quen AWS và muốn có thêm phần "Datadog theo dõi sức khoẻ MongoDB" (lớp 4) thì chọn EC2. Muốn ít việc nhất thì chọn Atlas.

## 2. Tạo máy: cấu hình đủ dùng và rẻ nhất

**Chốt: một máy `t4g.small` (ARM Graviton2, 2 vCPU, 2 GiB RAM) chạy tất cả: MongoDB, ingest API, detector, remediator, replayer và Datadog Agent.** Ổ gp3 16 GB, region Singapore.

| Mục | Đề xuất |
|---|---|
| AMI | Ubuntu Server 24.04 LTS **(64-bit Arm)**. Repo MongoDB 8.0 cho `noble` có bản `arm64`; Datadog Agent, `pymongo`, `pandas`, `ddtrace` đều có bản cho arm64 |
| Loại máy | `t4g.small`. Khi tạo, đặt **Credit specification = Standard** (mặc định của T4g là Unlimited, có thể bị tính thêm tiền khi dùng quá CPU nền) |
| Ổ đĩa | gp3 **16 GB** (mặc định 3000 IOPS, không cần tăng) |
| Region | `ap-southeast-1` (Singapore), gần Việt Nam |
| Security group | cổng 22 **chỉ từ IP của đội**. Mọi thứ chạy chung một máy nên **không cần mở 27017** |

### Vì sao đủ: số đo thật

Đo trên MongoDB 8.0.4 (replica set một node, WiredTiger cache giới hạn 0,25 GB), với toàn bộ `data/mongo` và các pipeline trong `src/dad_mongo_pipelines.py`:

| Đo | Kết quả |
|---|---|
| Dữ liệu sau khi nạp (9 collection, 32.288 bản tin) | 0,4 MB; trên đĩa 0,1 MB |
| RAM của mongod: lúc trống / sau khi nạp / sau khi chạy pipeline | 156 / 166 / **193 MB** |
| 8 pipeline (D1, D2, D4, D4 theo sensor, KPI làm mát, RCI, độ đầy đủ, vật lý) trên cả tuần | 1,1 giây |
| Một lượt phát hiện live (D2 + D4) khi tua ×60 | 48 ms, chạy mỗi 5 giây, tức < 1 % một vCPU |
| Một tiến trình Python dùng pymongo | khoảng 100 MB |
| Thư mục dữ liệu mongod | 201 MB, gần hết là journal cấp sẵn |
| Repo (gồm 7 PCAP) | 78 MB |

Ước lượng RAM khi chạy đủ bộ:

| Thành phần | RAM |
|---|---|
| Ubuntu | khoảng 250 MB (ước lượng) |
| mongod | khoảng 200 MB (đo) |
| Datadog Agent có APM và DBM | khoảng 250–300 MB (ước lượng) |
| 4 tiến trình Python (ingest, detector, remediator, replayer) | khoảng 400 MB (100 MB mỗi tiến trình, đo) |
| **Tổng** | **khoảng 1,1–1,2 GB** |

- **`t4g.micro` (1 GiB) không đủ.** Chạy được nếu bỏ Datadog Agent hoặc thêm swap, nhưng sẽ chậm và dễ bị OOM đúng lúc quay demo.
- **`t4g.small` (2 GiB) còn dư khoảng 0,8 GB.** CPU nền của máy là 20 % mỗi vCPU, trong khi bài này dùng chưa tới vài phần trăm.
- **`t4g.medium` hoặc `t3.medium` là thừa.**

Nên giới hạn cache để mongod không lấn RAM của các tiến trình khác (mặc định trên máy 2 GiB là 0,5 GB). Thêm vào `/etc/mongod.conf`:

```yaml
storage:
  wiredTiger:
    engineConfig:
      cacheSizeGB: 0.25
```

### Chi phí (Singapore, chạy 24/7 trong 30 ngày)

| Khoản | Giá | Một tháng |
|---|---|---|
| `t4g.small` | **0 USD nhờ chương trình dùng thử T4g**: 750 giờ/tháng đến hết 31/12/2026, áp dụng cho mọi tài khoản. Hết dùng thử thì khoảng 0,0212 USD/giờ | **0** (sau dùng thử khoảng 15 USD) |
| gp3 16 GB | khoảng 0,096 USD/GB-tháng; **vẫn tính tiền khi máy đã dừng** | khoảng 1,5 USD |
| IPv4 công khai | 0,005 USD/giờ, chỉ tính khi máy đang chạy | khoảng 3,6 USD |
| Truyền dữ liệu | dữ liệu rất nhỏ | khoảng 0 |
| **Tổng** | | **khoảng 5 USD/tháng**; tắt máy khi không dùng thì còn khoảng 2–3 USD |

Những thứ **không được tạo** vì tốn tiền mà không cần:
- NAT Gateway: khoảng 45 USD/tháng.
- Elastic IP để không: bị tính tiền cả khi máy dừng. Dùng IP tự cấp; IP sẽ đổi sau mỗi lần bật lại máy, nên SSH bằng Public DNS mới.
- Máy thứ hai riêng cho ứng dụng.
- Ổ io2.

Tài khoản mới còn có thêm tối đa 200 USD credit trong 6 tháng (Free Plan). Nên đặt **AWS Budgets** báo động ở mức 5 USD.

Nếu đội cần x86 (ví dụ một thư viện không có bản arm64) thì dùng `t3.small`. Cấu hình y hệt, nhưng không có dùng thử miễn phí, khoảng 19 USD/tháng.

## 3. Cài MongoDB 8.0

```bash
sudo apt-get update && sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
  | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update && sudo apt-get install -y mongodb-org
```

## 4. Bật replica set + xác thực

**Vì sao cần replica set:** Change Streams (remediator nghe `incidents`, replayer nghe `device_commands`) chỉ chạy trên replica set. Một node là đủ.

**Vì sao cần keyFile:** đã thử: bật xác thực trên replica set mà thiếu keyFile thì MongoDB **từ chối khởi động** (`security.keyFile is required when authorization is enabled with replica sets`), kể cả chỉ một node.

```bash
sudo mkdir -p /etc/mongodb && openssl rand -base64 756 | sudo tee /etc/mongodb/keyfile > /dev/null
sudo chown mongodb:mongodb /etc/mongodb/keyfile && sudo chmod 400 /etc/mongodb/keyfile
```

Sửa `/etc/mongod.conf`. `<PRIVATE_IP>` là IP nội bộ của EC2, ví dụ `10.0.1.23`:

```yaml
net:
  port: 27017
  bindIp: 127.0.0.1,<PRIVATE_IP>
replication:
  replSetName: rs0
security:
  authorization: enabled
  keyFile: /etc/mongodb/keyfile
```

```bash
sudo systemctl enable --now mongod
mongosh --eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "<PRIVATE_IP>:27017"}]})'
```

**`host` trong `rs.initiate` phải là địa chỉ mà máy ứng dụng kết nối tới được.** Driver đọc địa chỉ này từ cấu hình replica set; nếu để `127.0.0.1` thì máy khác kết nối kiểu replica set sẽ thất bại.

Nếu chạy tất cả trên một máy như cấu hình ở mục 2, có thể dùng `127.0.0.1` cho cả `bindIp` lẫn `host`. Khi đó ứng dụng kết nối bằng `mongodb://dad_app:<PASS>@127.0.0.1:27017/dad?replicaSet=rs0&authSource=admin`, và cổng 27017 không mở ra ngoài máy.

## 5. Tạo user

Ngay sau `rs.initiate`, MongoDB cho phép tạo user đầu tiên từ `localhost`:

```javascript
// mongosh trên EC2
use admin
db.createUser({ user: "admin", pwd: passwordPrompt(), roles: [{ role: "root", db: "admin" }] })
db.auth("admin")
// ứng dụng: chỉ đọc/ghi database dad
db.createUser({ user: "dad_app", pwd: passwordPrompt(), roles: [{ role: "readWrite", db: "dad" }] })
// Datadog Agent (theo tài liệu Datadog)
db.createUser({ user: "datadog", pwd: passwordPrompt(), roles: [
  { role: "read", db: "admin" }, { role: "clusterMonitor", db: "admin" }, { role: "read", db: "local" }, { role: "read", db: "dad" } ] })
```

- Các user ở trên được tạo **trong database `admin`**, nên chuỗi kết nối phải có **`authSource=admin`**. Khai `authSource=dad` sẽ bị "Authentication failed" (đã gặp khi thử).
- Đã kiểm tra: `dad_app` sai mật khẩu bị chặn; `dad_app` không ghi được sang database khác.

## 6. Kết nối và nạp dữ liệu

**Từ ứng dụng chạy trong cùng VPC:**
```
MONGODB_URI=mongodb://dad_app:<PASS>@<PRIVATE_IP>:27017/dad?replicaSet=rs0&authSource=admin
```

**Từ laptop, qua SSH tunnel** (không mở 27017 ra internet):
```bash
ssh -i key.pem -N -L 27017:127.0.0.1:27017 ubuntu@<EC2_PUBLIC_DNS> &
export MONGODB_URI="mongodb://dad_app:<PASS>@127.0.0.1:27017/dad?directConnection=true&authSource=admin"
python src/dad_mongo_load.py --uri "$MONGODB_URI" --db dad
```
Qua tunnel phải dùng `directConnection=true`, vì địa chỉ `<PRIVATE_IP>` trong cấu hình replica set không truy cập được từ laptop.

- Mật khẩu có ký tự đặc biệt (`@ : / ? #`) thì phải URL-encode trong chuỗi kết nối.
- **Không commit `MONGODB_URI`.** Để trong file `.env` và thêm `.env` vào `.gitignore` (thể lệ mục 6.1 cấm đưa thông tin xác thực vào repo và video).

## 7. Datadog Agent theo dõi MongoDB (lớp 4)

Cài Datadog Agent trên EC2 (lệnh cài lấy trong Datadog: *Integrations → Agent*), rồi tạo `/etc/datadog-agent/conf.d/mongo.d/conf.yaml`:

```yaml
init_config:
instances:
  - hosts:
      - 127.0.0.1:27017
    username: datadog
    password: "<DATADOG_USER_PASSWORD>"
    options:
      authSource: admin
    dbm: true                 # Database Monitoring: truy vấn chậm, kế hoạch thực thi, tải database
    cluster_name: dad-ec2
```

```bash
sudo systemctl restart datadog-agent && sudo datadog-agent status | grep -A5 mongo
```

Bạn sẽ có metric `mongodb.*` (kết nối, thao tác/giây, độ trễ, replication) và màn hình Database Monitoring, dùng cho lớp 4 (`NGHIEP_VU_GIAM_SAT.md` mục 2.4). Nếu thời gian chạy aggregation D4 tăng đột biến, DBM sẽ chỉ ra truy vấn nào chậm, đúng tinh thần "điều tra" của đề.

## 8. Bảo trì tối thiểu

- **Backup:** chụp snapshot EBS mỗi ngày (AWS Data Lifecycle Manager), hoặc `mongodump --uri "$MONGODB_URI" --archive=dad.gz --gzip` trước mỗi lần quay demo.
- **Không mất dữ liệu gốc:** dù có sự cố, `data/mongo/*.ndjson.gz` trong repo nạp lại được trong vài giây.
- **Tắt máy khi không dùng** để tiết kiệm. Dừng EC2 không mất dữ liệu trên EBS, nhưng IP công khai sẽ đổi.

## 9. Các bẫy đã kiểm chứng

| Bẫy | Biểu hiện | Cách tránh |
|---|---|---|
| Bật xác thực trên replica set thiếu keyFile | mongod không khởi động | tạo keyFile (mục 4) |
| `authSource` sai | "Authentication failed" | user tạo ở `admin` → `authSource=admin` |
| `host` trong replica set là `127.0.0.1` | máy khác kết nối kiểu replica set thất bại | dùng private IP; laptop dùng `directConnection=true` |
| Change Streams trên Time Series | lỗi "Cannot run aggregation on timeseries" | chỉ `watch()` `incidents`, `device_commands` |
| TTL trên dữ liệu 2019 | dữ liệu bị xoá sau vài giây | dữ liệu gốc ở `telemetry_hist` (không TTL) |
| MongoDB < 7.0 | `$median` không chạy | dùng 8.0 |
| Mở 27017 ra internet | bị quét, bị xoá dữ liệu | security group chỉ cho máy ứng dụng; laptop dùng SSH tunnel |
| T4g để Credit specification = Unlimited | phát sinh phí CPU dù đang dùng thử | chọn Standard khi tạo máy |

Nguồn:
- Datadog, *MongoDB integration*: https://docs.datadoghq.com/integrations/mongo/
- Datadog, *Database Monitoring for self-hosted MongoDB*: https://docs.datadoghq.com/database_monitoring/setup_mongodb/selfhosted/
