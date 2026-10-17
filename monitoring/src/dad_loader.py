"""Đọc bộ dữ liệu DAD (Vigoya et al., Sensors 2020) từ PCAP + CSV nhãn.

Những gì đã kiểm tra trực tiếp trên file:
- Mỗi ngày một file PCAP, MQTT trên TCP/1883, topic "IoT", payload là nhiệt độ dạng text, QoS 1.
- clientId chỉ có trong gói CONNECT, nên ta ánh xạ (ip, cổng nguồn) -> clientId.
- CSV nhãn: frame.number;ip.src;tcp.srcport;mqtt.clientid;mqtt.msgid;label (0/1).
"""
from __future__ import annotations

import glob
import os
import re

import pandas as pd
from scapy.all import IP, TCP, UDP, PcapReader
from scapy.contrib.mqtt import MQTT, MQTTConnect, MQTTPublish

# Vị trí cuối trong clientId -> loại cảm biến. Suy ra từ giá trị trung bình so với Table 1 của bài báo
# (bài báo không công bố bảng này). Xem mục 4 của notebook.
SENSOR_BY_POS = {"1": "TFEU", "2": "TFSU", "3": "TAS", "4": "TAR"}
INROW_IP = {"10.6.56.41": 13, "10.6.56.36": 15, "10.6.56.50": 23, "10.6.56.34": 25}
BROKER_IP = "10.6.56.1"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_RE = re.compile(r"capture_(\d{10})_(\w{3})\.pcap$")


def _mqtt_layers(pkt):
    """Mọi bản tin MQTT trong một segment TCP (một segment có thể chứa nhiều bản tin)."""
    out, i = [], 1
    while True:
        layer = pkt.getlayer(MQTT, nb=i)
        if layer is None:
            return out
        out.append(layer)
        i += 1


def parse_pcap(path: str, conn_map: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trả về (packets, publishes).

    packets  : 1 dòng / frame (giao thức, cờ TCP, số bản tin MQTT trong frame).
    publishes: 1 dòng / bản tin PUBLISH từ cảm biến gửi tới broker.
    conn_map được truyền qua các ngày vì kết nối TCP có thể mở từ file của ngày trước.
    """
    day = DAY_RE.search(os.path.basename(path)).group(2)
    if conn_map is None:
        conn_map = {}
    pk_rows, pub_rows = [], []
    with PcapReader(path) as rd:
        for n, p in enumerate(rd, start=1):
            ts = float(p.time)
            proto = "TCP" if p.haslayer(TCP) else ("UDP" if p.haslayer(UDP) else "OTHER")
            msgs = _mqtt_layers(p) if p.haslayer(MQTT) else []
            src = p[IP].src if p.haslayer(IP) else None
            sport = int(p[TCP].sport) if p.haslayer(TCP) else None
            flags = str(p[TCP].flags) if p.haslayer(TCP) else None
            pk_rows.append((day, n, ts, src, sport, proto, flags, len(p), len(msgs),
                            ",".join(str(m.type) for m in msgs)))
            for m in msgs:
                if m.type == 1 and m.haslayer(MQTTConnect):
                    conn_map[(src, sport)] = m[MQTTConnect].clientId.decode()
                elif m.type == 3 and m.haslayer(MQTTPublish) and src != BROKER_IP:
                    pub = m[MQTTPublish]
                    try:
                        val = float(pub.value.decode())
                    except Exception:
                        val = float("nan")
                    pub_rows.append((day, n, ts, src, sport, conn_map.get((src, sport)),
                                     getattr(pub, "msgid", None), pub.topic.decode(), val, int(m.DUP)))
    packets = pd.DataFrame(pk_rows, columns=["day", "frame", "ts", "src", "sport", "proto",
                                             "tcp_flags", "length", "n_mqtt", "mqtt_types"])
    pubs = pd.DataFrame(pub_rows, columns=["day", "frame", "ts", "src", "sport", "client_id",
                                           "msgid", "topic", "value", "dup_flag"])
    return packets, pubs


def load_labels(raw_dir: str) -> pd.DataFrame:
    """Đọc 7 file CSV nhãn, gắn tên ngày theo thứ tự thời gian."""
    files = sorted(glob.glob(os.path.join(raw_dir, "capture_*_labels.csv")))
    frames = []
    for day, f in zip(DAYS, files):
        d = pd.read_csv(f, sep=";")
        d["day"] = day
        frames.append(d)
    lab = pd.concat(frames, ignore_index=True)
    return lab.rename(columns={"frame.number": "frame", "ip.src": "src_csv",
                               "tcp.srcport": "sport_csv", "mqtt.clientid": "client_id_csv",
                               "mqtt.msgid": "msgid_csv"})


def load_all(raw_dir: str, cache_dir: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Đọc 7 PCAP, gắn nhãn theo (ngày, frame), thêm inrow/sensor/time/gap. Có cache CSV.gz."""
    if cache_dir:
        pk_c = os.path.join(cache_dir, "packets.csv.gz")
        pub_c = os.path.join(cache_dir, "publishes.csv.gz")
        if os.path.exists(pk_c) and os.path.exists(pub_c):
            return _finish(pd.read_csv(pk_c), pd.read_csv(pub_c, dtype={"client_id": str}))
    pk_all, pub_all, conn_map = [], [], {}
    files = sorted(glob.glob(os.path.join(raw_dir, "capture_*.pcap")),
                   key=lambda x: DAYS.index(DAY_RE.search(x).group(2)))
    for f in files:
        pk, pub = parse_pcap(f, conn_map)
        pk_all.append(pk)
        pub_all.append(pub)
    packets = pd.concat(pk_all, ignore_index=True)
    pubs = pd.concat(pub_all, ignore_index=True)
    lab = load_labels(raw_dir)[["day", "frame", "label"]]
    packets = packets.merge(lab, on=["day", "frame"], how="left")
    pubs = pubs.merge(lab, on=["day", "frame"], how="left")
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        packets.to_csv(pk_c, index=False)
        pubs.to_csv(pub_c, index=False)
    return _finish(packets, pubs)


def _finish(packets: pd.DataFrame, pubs: pd.DataFrame):
    for d in (packets, pubs):
        d["time_utc"] = pd.to_datetime(d["ts"], unit="s", utc=True)
        # Giờ địa phương của data center (Tây Ban Nha). Lưu ý: 27/10/2019 đổi giờ mùa đông.
        d["time"] = d["time_utc"].dt.tz_convert("Europe/Madrid")
        d["day"] = pd.Categorical(d["day"], categories=DAYS, ordered=True)
    pubs = pubs[pubs["client_id"].notna()].copy()
    pubs["client_id"] = pubs["client_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    pubs["inrow"] = pubs["client_id"].str[:2].astype(int)
    pubs["sensor"] = pubs["client_id"].str[2].map(SENSOR_BY_POS)
    pubs = pubs.sort_values(["client_id", "ts"]).reset_index(drop=True)
    pubs["gap_s"] = pubs.groupby("client_id")["ts"].diff()
    return packets, pubs
