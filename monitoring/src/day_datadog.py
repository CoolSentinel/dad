"""Đẩy dữ liệu từ MongoDB (collection telemetry) sang Datadog để giám sát.

Datadog chỉ nhận điểm có timestamp không cũ quá 1 giờ và không sớm quá 10 phút
(https://docs.datadoghq.com/api/latest/metrics/submit-metrics.md), nên dữ liệu 2019 được PHÁT LẠI:
    replay_ts = t0 + (ts_us - ts_us_đầu_tiên) // (speed * 1_000_000)      (số nguyên, giây)

Metric (gauge), tag: inrow, sensor, client_id, source:dad_replay
    dad.temp    nhiệt độ của bản tin
    dad.gap_p   khoảng cách tới bản tin trước của cùng cảm biến, tính theo chu kỳ P = 300,1 s

Mỗi điểm được ghi vào "sổ gửi" (journal) kèm src {file, frame} gốc để kiểm ngược bằng kiem_tra_du_lieu.py.

Chế độ:
    chạy thử (mặc định): không gửi, ghi journal + payload ra monitoring/data/datadog_out/
    --live             : gửi thật theo nhịp phát lại; cần DD_API_KEY, tuỳ chọn DD_SITE (mặc định datadoghq.com)

Ví dụ:
    python monitoring/src/day_datadog.py --speed 10
    python monitoring/src/day_datadog.py --speed 60 --tu 2019-10-23T01:30:00Z --den 2019-10-23T05:00:00Z --live
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "data", "datadog_out"))
URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018/?replicaSet=rs0")
P_US = 300_100_000                       # chu kỳ gửi, micro giây
GAUGE = 3                                # metric type gauge trong API v2
MAX_BATCH_BYTES = 400_000                # dưới giới hạn 500 KB của API


def parse_iso(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1_000_000)


def load(db, tu_us: int | None, den_us: int | None) -> list[dict]:
    q = {}
    if tu_us or den_us:
        q["ts_us"] = {k: v for k, v in (("$gte", tu_us), ("$lte", den_us)) if v is not None}
    docs = list(db.telemetry.find(q, {"_id": 0}).sort([("ts_us", 1), ("src.file", 1), ("src.frame", 1)]))
    if not docs:
        sys.exit("Không có document nào trong khoảng thời gian đã chọn.")
    return docs


def build_points(docs: list[dict], t0: int, speed: int) -> list[dict]:
    """Mỗi document -> 1 điểm dad.temp, và 1 điểm dad.gap_p nếu có bản tin trước của cùng cảm biến."""
    first_us = docs[0]["ts_us"]
    prev_us: dict[str, int] = {}
    pts = []
    for d in docs:
        m = d["meta"]
        tags = [f"inrow:{m['inrow']}", f"sensor:{m['sensor'].lower()}", f"client_id:{m['clientId']}", "source:dad_replay"]
        ts = t0 + (d["ts_us"] - first_us) // (speed * 1_000_000)
        src = {"file": d["src"]["file"], "frame": d["src"]["frame"], "ts_us": d["ts_us"]}
        pts.append({"metric": "dad.temp", "tags": tags, "timestamp": ts, "value": d["value"], "src": src})
        if m["clientId"] in prev_us:
            gap_p = round((d["ts_us"] - prev_us[m["clientId"]]) / P_US, 6)
            pts.append({"metric": "dad.gap_p", "tags": tags, "timestamp": ts, "value": gap_p, "src": src})
        prev_us[m["clientId"]] = d["ts_us"]
    return pts


def check_collisions(pts: list[dict]) -> None:
    """Datadog lưu theo giây: hai điểm cùng series cùng giây sẽ đè nhau, nên dừng nếu có."""
    seen = defaultdict(set)
    for p in pts:
        key = (p["metric"], tuple(p["tags"]))
        if p["timestamp"] in seen[key]:
            sys.exit(f"Trùng giây ở series {key} lúc {p['timestamp']}: giảm --speed.")
        seen[key].add(p["timestamp"])


def batches(pts: list[dict]):
    """Gom điểm theo series thành các payload v2, mỗi payload dưới MAX_BATCH_BYTES."""
    cur: dict[tuple, list] = defaultdict(list)
    size = 0
    for p in pts:
        cur[(p["metric"], tuple(p["tags"]))].append({"timestamp": p["timestamp"], "value": p["value"]})
        size += 40
        if size > MAX_BATCH_BYTES:
            yield payload(cur)
            cur, size = defaultdict(list), 0
    if cur:
        yield payload(cur)


def payload(series: dict) -> dict:
    return {"series": [{"metric": m, "type": GAUGE, "tags": list(t), "points": ps} for (m, t), ps in series.items()]}


def send(body: dict, api_key: str, site: str) -> None:
    req = urllib.request.Request(f"https://api.{site}/api/v2/series", data=json.dumps(body).encode(), method="POST",
                                 headers={"DD-API-KEY": api_key, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 202:
            raise RuntimeError(f"Datadog trả {r.status}: {r.read()[:300]!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speed", type=int, default=10, help="tốc độ phát lại (×), mặc định 10")
    ap.add_argument("--tu", help="chỉ lấy bản tin từ thời điểm gốc này (ISO, UTC)")
    ap.add_argument("--den", help="đến thời điểm gốc này (ISO, UTC)")
    ap.add_argument("--t0", type=int, help="giây Unix của điểm đầu tiên khi phát lại (mặc định: bây giờ + 5 s)")
    ap.add_argument("--live", action="store_true", help="gửi thật tới Datadog")
    a = ap.parse_args()

    db = MongoClient(URI)[os.environ.get("MONGODB_DB", "dad")]
    docs = load(db, parse_iso(a.tu) if a.tu else None, parse_iso(a.den) if a.den else None)
    t0 = a.t0 or int(time.time()) + 5
    pts = build_points(docs, t0, a.speed)
    check_collisions(pts)

    os.makedirs(OUT, exist_ok=True)
    meta = {"t0": t0, "speed": a.speed, "first_ts_us": docs[0]["ts_us"], "documents": len(docs), "points": len(pts),
            "tu": a.tu, "den": a.den, "live": a.live}
    with gzip.open(os.path.join(OUT, "journal.ndjson.gz"), "wt", encoding="utf-8") as f:
        for p in pts:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")
    with open(os.path.join(OUT, "run.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if not a.live:
        with gzip.open(os.path.join(OUT, "payloads.ndjson.gz"), "wt", encoding="utf-8") as f:
            n = 0
            for b in batches(pts):
                f.write(json.dumps(b, separators=(",", ":")) + "\n")
                n += 1
        print(f"chạy thử: {len(docs)} document → {len(pts)} điểm, {n} payload; ghi ở {OUT}")
        return

    api_key = os.environ.get("DD_API_KEY")
    if not api_key:
        sys.exit("Thiếu DD_API_KEY.")
    site = os.environ.get("DD_SITE", "datadoghq.com")
    pending = sorted(pts, key=lambda p: p["timestamp"])
    i = sent = 0
    print(f"gửi {len(pts)} điểm tới {site}, tốc độ ×{a.speed}, kết thúc khoảng {datetime.fromtimestamp(pending[-1]['timestamp'])}")
    while i < len(pending):
        now = int(time.time())
        j = i
        while j < len(pending) and pending[j]["timestamp"] <= now:
            j += 1
        if j > i:
            for b in batches(pending[i:j]):
                send(b, api_key, site)
            sent += j - i
            i = j
            print(f"\r  đã gửi {sent}/{len(pending)}", end="", flush=True)
        time.sleep(1)
    print("\nxong")


if __name__ == "__main__":
    main()
