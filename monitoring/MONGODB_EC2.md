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

## 2. Tạo máy

| Mục | Đề xuất |
|---|---|
| AMI | Ubuntu Server 24.04 LTS (x86_64) |
| Loại máy | `t3.small` (2 GB RAM) là đủ cho 32.288 document; `t3.medium` nếu chạy chung replayer, ingest và Datadog Agent trên cùng máy |
| Ổ đĩa | gp3 20 GB |
| Region | `ap-southeast-1` (Singapore), gần Việt Nam |
| Security group | cổng 22 **chỉ từ IP của đội**; cổng 27017 **chỉ từ security group của máy chạy ứng dụng**. **Không bao giờ mở 27017 cho `0.0.0.0/0`** |

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
- **Tắt máy khi không dùng** để tiết kiệm. Dừng EC2 không mất dữ liệu trên EBS.

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

Nguồn:
- Datadog, *MongoDB integration*: https://docs.datadoghq.com/integrations/mongo/
- Datadog, *Database Monitoring for self-hosted MongoDB*: https://docs.datadoghq.com/database_monitoring/setup_mongodb/selfhosted/
