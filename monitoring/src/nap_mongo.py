"""Nạp dữ liệu đã xuất (data/mongo/) vào MongoDB tự host.

Tạo database `dad` với:
    telemetry  time series collection (timeField ts, metaField meta, granularity minutes)
    latest     collection thường (_id = clientId)
    incidents  collection thường (nghe change stream)
Không đặt TTL cho telemetry: dữ liệu DAD là năm 2019, TTL sẽ xoá ngay khi nạp.
Chạy lại là xoá và nạp lại từ đầu (idempotent).

    MONGODB_URI="mongodb://127.0.0.1:27018/?replicaSet=rs0" python monitoring/src/nap_mongo.py
"""
from __future__ import annotations

import gzip
import json
import os

from bson import json_util
from pymongo import ASCENDING, MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.abspath(os.path.join(HERE, "..", "..", "data", "mongo"))
URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018/?replicaSet=rs0")
DB = os.environ.get("MONGODB_DB", "dad")


def read(name: str) -> list[dict]:
    with gzip.open(os.path.join(SEED, f"{name}.ndjson.gz"), "rt", encoding="utf-8") as f:
        return [json_util.loads(line) for line in f]


def main() -> None:
    db = MongoClient(URI)[DB]
    manifest = json.load(open(os.path.join(SEED, "manifest.json"), encoding="utf-8"))
    for name in ("telemetry", "latest", "incidents"):
        db.drop_collection(name)
    db.create_collection("telemetry", timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"})
    db.telemetry.create_index([("meta.inrow", ASCENDING), ("meta.sensor", ASCENDING), ("ts", ASCENDING)])
    db.telemetry.create_index([("src.file", ASCENDING), ("src.frame", ASCENDING)])
    db.create_collection("latest")
    db.create_collection("incidents")
    db.incidents.create_index([("inrow", ASCENDING), ("detected_at", ASCENDING)])

    for name in ("telemetry", "latest", "incidents"):
        docs = read(name)
        for i in range(0, len(docs), 5000):
            db[name].insert_many(docs[i:i + 5000], ordered=True)
        n, want = db[name].count_documents({}), manifest["collections"][name]["documents"]
        print(f"{name:10s} nạp {n:>6} document (manifest {want}) {'OK' if n == want else 'LỆCH'}")
        assert n == want


if __name__ == "__main__":
    main()
