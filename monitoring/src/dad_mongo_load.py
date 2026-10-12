"""Nạp các file data/mongo/*.ndjson.gz (do dad_export.py tạo) vào MongoDB.

Chạy:  MONGODB_URI="mongodb+srv://..." python src/dad_mongo_load.py [--db dad] [--drop]

Tạo:
- telemetry_hist : Time Series, dữ liệu gốc 2019, KHÔNG có TTL (TTL 7 ngày sẽ xoá sạch dữ liệu năm 2019 ngay khi nạp)
- telemetry      : Time Series rỗng cho replay/live, CÓ TTL 7 ngày
- incidents, actions : rỗng, có JSON Schema validator, dùng khi hệ thống chạy
- devices, inrows, mqtt_sessions, traffic_daily, gt_labels, gt_incidents, detector_config, demo_scenarios
"""
from __future__ import annotations

import argparse
import gzip
import os

from bson import json_util
from pymongo import ASCENDING, DESCENDING, MongoClient

TS_OPTS = {"timeField": "ts", "metaField": "meta", "granularity": "seconds"}
TTL_SECONDS = 7 * 24 * 3600

VALIDATORS = {
    "devices": {"$jsonSchema": {"bsonType": "object", "required": ["clientId", "inrow", "sensor", "valid_range_c"],
                                "properties": {"clientId": {"bsonType": "string", "pattern": "^[0-9]{3}$"},
                                               "inrow": {"enum": [13, 15, 23, 25]},
                                               "sensor": {"enum": ["TFEU", "TFSU", "TAS", "TAR"]},
                                               "quality": {"enum": ["ok", "suspect"]}}}},
    "incidents": {"$jsonSchema": {"bsonType": "object", "required": ["inrow", "status", "kinds", "detected_at"],
                                  "properties": {"status": {"enum": ["open", "ack", "mitigated", "resolved"]},
                                                 "kinds": {"bsonType": "array", "items": {"enum": ["interception", "duplication", "modification", "physics", "range", "infra"]}},
                                                 "detected_at": {"bsonType": "date"}}}},
    "actions": {"$jsonSchema": {"bsonType": "object", "required": ["incident_id", "action", "at"],
                                "properties": {"action": {"enum": ["reconnect", "rate_limit", "quarantine", "release", "ticket", "restart_ingest"]},
                                               "at": {"bsonType": "date"}}}},
}

INDEXES = {
    "telemetry_hist": [[("meta.clientId", ASCENDING), ("ts", ASCENDING)], [("meta.inrow", ASCENDING), ("ts", ASCENDING)]],
    "telemetry": [[("meta.clientId", ASCENDING), ("ts", ASCENDING)], [("meta.inrow", ASCENDING), ("ts", ASCENDING)]],
    "mqtt_sessions": [[("clientId", ASCENDING), ("connect_ts", ASCENDING)]],
    "gt_labels": [[("clientId", ASCENDING), ("ts", ASCENDING)]],
    "incidents": [[("status", ASCENDING), ("inrow", ASCENDING)], [("detected_at", DESCENDING)]],
    "actions": [[("incident_id", ASCENDING), ("at", ASCENDING)]],
}


def read_ndjson(path: str):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json_util.loads(line)


def load(uri: str, db_name: str, data_dir: str, drop: bool = True) -> dict[str, int]:
    db = MongoClient(uri, tz_aware=True)[db_name]
    files = sorted(f for f in os.listdir(data_dir) if f.endswith(".ndjson.gz"))
    existing = set(db.list_collection_names())
    if drop:
        for name in [f[:-len(".ndjson.gz")] for f in files] + ["telemetry", "incidents", "actions"]:
            if name in existing:
                db.drop_collection(name)
        existing = set()
    # Time Series: lịch sử không TTL, live có TTL
    if "telemetry_hist" not in existing:
        db.create_collection("telemetry_hist", timeseries=TS_OPTS)
    if "telemetry" not in existing:
        db.create_collection("telemetry", timeseries=TS_OPTS, expireAfterSeconds=TTL_SECONDS)
    for name, v in VALIDATORS.items():
        if name not in existing:
            db.create_collection(name, validator=v, validationLevel="strict")
    counts = {}
    for f in files:
        name = f[:-len(".ndjson.gz")]
        docs = list(read_ndjson(os.path.join(data_dir, f)))
        for i in range(0, len(docs), 5000):
            db[name].insert_many(docs[i:i + 5000], ordered=False)
        counts[name] = db[name].count_documents({})
    for name, idxs in INDEXES.items():
        for keys in idxs:
            db[name].create_index(keys)
    return counts


def load_scenario(uri: str, db_name: str, scenario: str, speed: float = 60.0, now=None, clear: bool = True) -> dict:
    """Chép 1 ngày làm nóng (thứ Hai) + một kịch bản demo từ telemetry_hist sang `telemetry` (live, có TTL).

    Thời gian được dời để kịch bản KẾT THÚC lúc `now`, và nén theo `speed` (×60: 5 phút thành 5 giây).
    Dùng để thử pipeline với P = 300.1 / speed mà không cần chạy replayer MQTT.
    """
    from datetime import datetime, timedelta, timezone
    db = MongoClient(uri, tz_aware=True)[db_name]
    now = now or datetime.now(timezone.utc)
    warm, sc = db.demo_scenarios.find_one({"_id": "warmup"}), db.demo_scenarios.find_one({"_id": scenario})
    period = 300.1
    seg = []                                                 # (doc, giây kể từ đầu chuỗi đã ghép, chưa nén)
    w_docs = list(db.telemetry_hist.find({"ts": {"$gte": warm["start"], "$lt": warm["end"]}}, {"_id": 0}).sort("ts", 1))
    s_docs = list(db.telemetry_hist.find({"ts": {"$gte": sc["start"], "$lt": sc["end"]}}, {"_id": 0}).sort("ts", 1))
    t0 = w_docs[0]["ts"]
    w_len = (w_docs[-1]["ts"] - t0).total_seconds()
    for d in w_docs:
        seg.append((d, (d["ts"] - t0).total_seconds()))
    # nối kịch bản ngay sau ngày làm nóng, giữ đúng pha gửi trong chu kỳ để khoảng cách ở chỗ nối ≈ 1 chu kỳ
    s0 = s_docs[0]["ts"]
    phase = ((s0 - t0).total_seconds() - w_len) % period
    offset = w_len + phase if phase > 1 else w_len + period
    for d in s_docs:
        seg.append((d, offset + (d["ts"] - s0).total_seconds()))
    total = seg[-1][1]
    out = []
    for d, sec in seg:
        d = dict(d); d["orig_ts"] = d["ts"]
        d["ts"] = now - timedelta(seconds=(total - sec) / speed)
        d["conn"] = d["conn"] + ("@warm" if sec <= w_len else "@" + scenario)   # 2 phiên khác nhau, như kết nối lại
        out.append(d)
    if clear:
        db.telemetry.delete_many({})
    db.telemetry.insert_many(out)
    return {"scenario": scenario, "speed": speed, "docs": len(out), "period_s": period / speed,
            "scenario_start": now - timedelta(seconds=(total - offset) / speed), "end": now}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--uri", default=os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--db", default="dad")
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "mongo"))
    ap.add_argument("--keep", action="store_true", help="không xoá collection cũ")
    a = ap.parse_args()
    for k, v in load(a.uri, a.db, a.data, drop=not a.keep).items():
        print(f"{k:16s} {v}")
