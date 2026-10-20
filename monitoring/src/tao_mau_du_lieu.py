"""Sinh object mẫu cho DATA_MODEL.md, lấy THẲNG từ dữ liệu nạp MongoDB (data/mongo/).

Vì vậy mẫu luôn cùng schema với dữ liệu thật trong MongoDB. Riêng mẫu bản tin MQTT gốc được đọc
từ file PCAP (scapy) và đối chiếu với dòng CSV cùng frame và với document telemetry tương ứng.

Chạy từ thư mục gốc repo `dad` (sau khi đã chạy xuat_mongo.py):
    python monitoring/src/tao_mau_du_lieu.py            # in JSON ra màn hình
    python monitoring/src/tao_mau_du_lieu.py --ghi      # ghi monitoring/samples/*.json
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from decimal import Decimal

from scapy.all import IP, TCP, PcapReader
from scapy.contrib.mqtt import MQTT, MQTTConnect, MQTTPublish

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SEED = os.path.join(REPO, "data", "mongo")
OUT = os.path.join(REPO, "monitoring", "samples")
P_US = 300_100_000

WED = "data/bat_thuong/capture_1910230000_wed.pcap"
TELEMETRY = {  # tình huống -> (file, frame)
    "binh_thuong_InRow15_TAS": ("data/binh_thuong/capture_1910210000_mon.pcap", 217),
    "sua_gia_tri_InRow13_TAS_0410": (WED, 2707),
    "chen_ban_tin_InRow13_TFEU_030637": ("data/bat_thuong/capture_1910240000_thu.pcap", 2102),
}
LATEST = {  # trạng thái `latest` ngay sau khi nhận bản tin (file, frame)
    "binh_thuong": ("data/binh_thuong/capture_1910210000_mon.pcap", 217),
    "sau_khoang_ho_chan_goi": ("data/bat_thuong/capture_1910220000_tue.pcap", 488),
    "ban_tin_den_som": ("data/bat_thuong/capture_1910240000_thu.pcap", 2102),
}
INCIDENTS = {
    "mat_ban_tin": "inrow13-20191021T222233Z-mat_ban_tin",
    "sua_gia_tri": "inrow13-20191023T022500Z-sua_gia_tri",
    "chen_ban_tin": "inrow13-20191024T010637Z-chen_ban_tin",
    "node_ngat_ket_noi": "inrow13-20191024T211126Z-mat_ban_tin",
}


def seed(name: str) -> list[dict]:
    with gzip.open(os.path.join(SEED, f"{name}.ndjson.gz"), "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def csv_line(pcap_rel: str, frame: int) -> str:
    with open(os.path.join(REPO, pcap_rel[:pcap_rel.rindex("_")] + "_labels.csv"), encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            if i == frame + 1:                                 # dòng 1 là tiêu đề
                return line.rstrip("\n")
    raise ValueError(frame)


def mqtt_sample(tel: dict) -> dict:
    """Bản tin gốc ở frame 2707 (thứ Tư), đọc từ PCAP, và dạng khi phát lại theo topic phân cấp."""
    conn = {}
    with PcapReader(os.path.join(REPO, WED)) as rd:
        for n, pk in enumerate(rd, start=1):
            if pk.haslayer(MQTTConnect):
                conn[(pk[IP].src, int(pk[TCP].sport))] = (n, pk[MQTTConnect].clientId.decode(), int(pk[MQTTConnect].klive))
            if n == 2707:
                p, m = pk[MQTTPublish], pk[MQTT]
                ip, port = pk[IP].src, int(pk[TCP].sport)
                ts_us = int(Decimal(pk.time) * 1_000_000)
                break
    cframe, cid, ka = conn[(ip, port)]
    doc = tel[(WED, 2707)]
    line = csv_line(WED, 2707)
    assert line == f"2707;{ip};{port};{cid};{p.msgid};1", line
    assert doc["ts_us"] == ts_us and doc["value"] == float(p.value.decode()) and doc["seq"] == p.msgid
    return {
        "goc_trong_pcap": {"topic": p.topic.decode(), "payload": p.value.decode(), "qos": int(m.QOS), "msgid": int(p.msgid),
                           "ip_nguon": ip, "cong_nguon": port, "ts_us": ts_us,
                           "_nguon": {"file": WED, "frame": 2707}, "_dong_csv": line,
                           "_connect": {"file": WED, "frame": cframe, "clientId": cid, "keepalive": ka}},
        "khi_phat_lai": {"topic": f"dc/citic/inrow{doc['meta']['inrow']}/{doc['meta']['sensor']}",
                         "payload": {"value": doc["value"], "seq": doc["seq"], "ts": doc["ts"]["$date"]},
                         "qos": 1, "_nguon": {"file": WED, "frame": 2707}},
    }


def latest_at(by_cid: dict[str, list[dict]], key: tuple[str, int]) -> dict:
    """Document `latest` của cảm biến ngay sau bản tin `key`, cùng schema với latest.ndjson.gz."""
    for cid, docs in by_cid.items():
        for i, d in enumerate(docs):
            if (d["src"]["file"], d["src"]["frame"]) == key:
                prev = docs[i - 1]
                gap_s = (d["ts_us"] - prev["ts_us"]) / 1e6
                return {"_id": cid, "inrow": d["meta"]["inrow"], "sensor": d["meta"]["sensor"], "ts": d["ts"],
                        "ts_us": d["ts_us"], "value": d["value"], "seq": d["seq"], "conn": d["conn"],
                        "gap_s": round(gap_s, 6), "gap_P": round(gap_s * 1e6 / P_US, 4),
                        "src": d["src"], "prev_src": prev["src"]}
    raise KeyError(key)


def main() -> None:
    tel_list = seed("telemetry")
    tel = {(d["src"]["file"], d["src"]["frame"]): d for d in tel_list}
    by_cid: dict[str, list[dict]] = {}
    for d in sorted(tel_list, key=lambda d: (d["ts_us"], d["src"]["file"], d["src"]["frame"])):
        by_cid.setdefault(d["meta"]["clientId"], []).append(d)
    incs = {d["_id"]: d for d in seed("incidents")}
    latest_schema = set(seed("latest")[0])
    samples = {
        "mqtt": mqtt_sample(tel),
        "telemetry": {k: tel[v] for k, v in TELEMETRY.items()},
        "latest": {k: latest_at(by_cid, v) for k, v in LATEST.items()},
        "incidents": {k: incs[v] for k, v in INCIDENTS.items()},
    }
    assert all(set(d) == latest_schema for d in samples["latest"].values())
    if "--ghi" in sys.argv:
        os.makedirs(OUT, exist_ok=True)
        for k, v in samples.items():
            with open(os.path.join(OUT, f"{k}.json"), "w", encoding="utf-8") as f:
                json.dump(v, f, ensure_ascii=False, indent=2)
        print("đã ghi", OUT)
    else:
        print(json.dumps(samples, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
