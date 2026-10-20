"""Xuất dữ liệu DAD (data/*.pcap) thành dữ liệu nạp MongoDB, theo mô hình ở monitoring/DATA_MODEL.md.

Đầu ra (data/mongo/, NDJSON nén gzip, ngày giờ dạng MongoDB Extended JSON):
    telemetry.ndjson.gz   1 document / bản tin nhiệt độ (output của khâu ingest)
    latest.ndjson.gz      1 document / cảm biến, trạng thái sau bản tin cuối cùng (output của khâu ingest)
    incidents.ndjson.gz   sự cố do bộ quy tắc D1, D2, D4 phát hiện (output của khâu phát hiện)
    manifest.json         số document, tổng kiểm (sha256) từng file

Đọc PCAP bằng scapy, giữ thời gian chính xác đến micro giây (`ts_us`). Không dùng nhãn CSV ở đây.
Chạy từ gốc repo:  python monitoring/src/xuat_mongo.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from scapy.all import IP, TCP, PcapReader
from scapy.contrib.mqtt import MQTT, MQTTConnect, MQTTPublish

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data")
OUT = os.path.join(REPO, "data", "mongo")

P = 300.1
INROW_IP = {"10.6.56.41": 13, "10.6.56.36": 15, "10.6.56.50": 23, "10.6.56.34": 25}
SENSOR_BY_POS = {"1": "TFEU", "2": "TFSU", "3": "TAS", "4": "TAR"}
FILES = [  # thứ tự thời gian; kết nối có thể mở từ file ngày hôm trước
    "binh_thuong/capture_1910210000_mon.pcap", "bat_thuong/capture_1910220000_tue.pcap",
    "bat_thuong/capture_1910230000_wed.pcap", "bat_thuong/capture_1910240000_thu.pcap",
    "bat_thuong/capture_1910250000_fri.pcap", "bat_thuong/capture_1910260000_sat.pcap",
    "binh_thuong/capture_1910270000_sun.pcap",
]


def date_ms(ts_us: int) -> dict:
    """MongoDB Extended JSON cho Date (mili giây, làm tròn xuống)."""
    ms = ts_us // 1000
    return {"$date": datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}


def read_publishes() -> list[dict]:
    """Mọi bản tin PUBLISH từ 4 tủ, theo thứ tự file rồi thứ tự frame."""
    conn_map: dict[tuple[str, int], str] = {}
    rows = []
    for rel in FILES:
        with PcapReader(os.path.join(DATA, rel)) as rd:
            for n, pk in enumerate(rd, start=1):
                if not (pk.haslayer(MQTT) and pk.haslayer(TCP) and pk.haslayer(IP)):
                    continue
                key = (pk[IP].src, int(pk[TCP].sport))
                m = pk[MQTT]
                if m.type == 1 and pk.haslayer(MQTTConnect):
                    conn_map[key] = pk[MQTTConnect].clientId.decode()
                elif m.type == 3 and pk.haslayer(MQTTPublish) and key[0] in INROW_IP:
                    cid = conn_map[key]
                    p = pk[MQTTPublish]
                    rows.append({"ts_us": int(Decimal(pk.time) * 1_000_000), "inrow": INROW_IP[key[0]],
                                 "sensor": SENSOR_BY_POS[cid[-1]], "clientId": cid,
                                 "payload": p.value.decode(), "seq": int(p.msgid),
                                 "conn": f"{key[0]}:{key[1]}", "file": "data/" + rel, "frame": n})
    return rows


def telemetry_docs(rows: list[dict]) -> list[dict]:
    return [{"ts": date_ms(r["ts_us"]), "ts_us": r["ts_us"],
             "meta": {"inrow": r["inrow"], "sensor": r["sensor"], "clientId": r["clientId"]},
             "value": float(r["payload"]), "seq": r["seq"], "conn": r["conn"],
             "src": {"file": r["file"], "frame": r["frame"]}} for r in rows]


def latest_docs(rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[r["clientId"]].append(r)
    out = []
    for cid, rs in sorted(by.items()):
        rs.sort(key=lambda r: r["ts_us"])
        cur, prev = rs[-1], rs[-2]
        gap_s = (cur["ts_us"] - prev["ts_us"]) / 1e6
        out.append({"_id": cid, "inrow": cur["inrow"], "sensor": cur["sensor"], "ts": date_ms(cur["ts_us"]),
                    "ts_us": cur["ts_us"], "value": float(cur["payload"]), "seq": cur["seq"], "conn": cur["conn"],
                    "gap_s": round(gap_s, 6), "gap_P": round(gap_s / P, 4),
                    "src": {"file": cur["file"], "frame": cur["frame"]},
                    "prev_src": {"file": prev["file"], "frame": prev["frame"]}})
    return out


def incident_docs() -> list[dict]:
    """Chạy bộ quy tắc D1, D2, D4 (src/dad_mining.py, không dùng nhãn) và gộp cảnh báo cùng tủ cách nhau < 20 phút."""
    sys.path.insert(0, HERE)
    import pandas as pd
    import dad_mining as dm
    from dad_loader import load_all
    _, pubs = load_all(DATA, os.path.join(REPO, "monitoring", "data", "processed"))
    pubs = dm.add_baseline(pubs)
    nodes = dm.node_slots(pubs)
    A = dm.alarms(pubs, nodes)
    rules = {"D1 im lặng": ("D1", "mat_ban_tin"), "D2 gửi dồn": ("D2", "chen_ban_tin"),
             "D4 lệch âm 3/6 (mới)": ("D4", "sua_gia_tri")}
    a = pd.concat([A[k].assign(rule=v[0], kind=v[1]) for k, v in rules.items()]).sort_values(["inrow", "t"])
    new = (a.groupby("inrow").t.diff() > pd.Timedelta("20min")) | (a.inrow != a.inrow.shift())
    a["event"] = new.cumsum()
    out = []
    for _, g in a.groupby("event"):
        inrow = int(g.inrow.iloc[0])
        t0, t1 = g.t.min(), g.t.max()
        r = pubs[pubs.inrow == inrow]
        gap_start = r.time_utc - pd.to_timedelta(r.gap_s.fillna(0), unit="s")
        eps = pd.Timedelta("1s")
        # mỗi khoảng hở / bản tin đến sớm thuộc đúng sự cố chứa cảnh báo do chính nó sinh ra:
        #   D1 báo lúc (khoảng hở bắt đầu + 1,5 P); D2 báo đúng lúc bản tin đến sớm tới
        d1_at = gap_start + pd.Timedelta(seconds=dm.SILENCE_FACTOR * P)
        holes = r[(r.gap_s > dm.SILENCE_FACTOR * P) & (d1_at >= t0 - eps) & (d1_at <= t1 + eps)]
        early = r[(r.gap_s < dm.BURST_FACTOR * P) & ~r.new_conn & (r.time_utc >= t0 - eps) & (r.time_utc <= t1 + eps)]
        w = r[(r.time_utc >= t0 - pd.Timedelta("30min")) & (r.time_utc <= t1)]
        # sửa giá trị: slot 5 phút có trung bình (giá trị − baseline) của tủ < −0,8 °C, trong 30 phút trước cảnh báo đầu đến cảnh báo cuối
        neg = nodes[(nodes.inrow == inrow) & (nodes.slot >= t0 - pd.Timedelta("30min")) & (nodes.slot <= t1) & (nodes.dev < -dm.DEV_T)]
        neg_src = r[r.slot == neg.slot.min()] if len(neg) else r.iloc[0:0]
        us = lambda t: int(round(t.value / 1000))          # ns -> µs, làm tròn (tránh lệch 1 µs do số thực)
        first_kind = g.sort_values("t").kind.iloc[0]
        out.append({
            "_id": f"inrow{inrow}-{t0.strftime('%Y%m%dT%H%M%SZ')}-{first_kind}",
            "inrow": inrow, "kinds": sorted(g.kind.unique()), "rules": sorted(g.rule.unique()),
            "status": "resolved",
            "detected_at": date_ms(us(t0)), "detected_us": us(t0),
            "last_alarm_at": date_ms(us(t1)), "last_alarm_us": us(t1), "n_alarms": int(len(g)),
            "evidence": {"sensors": int(w.client_id.nunique()),
                         "ban_tin_mat": int(((holes.gap_s / P).round() - 1).sum()),
                         "ban_tin_den_som": int(len(early)),
                         "slot_lech_am": int(len(neg)),
                         "muc_tru_C": int(-neg.dev.round().mode().min()) if len(neg) else 0},
            "src_frames": [{"file": None, "day": str(d), "frame": int(f)} for d, f in
                           pd.concat([holes, early, neg_src])[["day", "frame"]].drop_duplicates().itertuples(index=False)][:40],
        })
    day_file = {f.split("_")[-1][:3]: "data/" + f for f in FILES}
    for doc in out:
        for s in doc["src_frames"]:
            s["file"] = day_file[s.pop("day")]
    return out


def write(name: str, docs: list[dict]) -> dict:
    path = os.path.join(OUT, f"{name}.ndjson.gz")
    raw = "".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n" for d in docs).encode()
    with gzip.GzipFile(path, "wb", mtime=0) as f:          # mtime=0: chạy lại cho đúng cùng file
        f.write(raw)
    return {"file": os.path.basename(path), "documents": len(docs), "sha256_ndjson": hashlib.sha256(raw).hexdigest()}


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    rows = read_publishes()
    manifest = {"source": "data/*.pcap (DAD, Vigoya et al., Sensors 2020)",
                "collections": {"telemetry": write("telemetry", telemetry_docs(rows)),
                                "latest": write("latest", latest_docs(rows)),
                                "incidents": write("incidents", incident_docs())}}
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
