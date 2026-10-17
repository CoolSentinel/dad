"""Xem nội dung một hoặc nhiều frame trong file PCAP gốc của DAD, kèm dòng nhãn CSV cùng frame.

Dùng để tự kiểm chứng một bản ghi được nhắc trong báo cáo, không đi qua code phân tích
(đọc thẳng file PCAP bằng scapy và đọc thẳng dòng thứ frame + 1 của file CSV).

Chạy từ thư mục gốc repo `dad`:
    python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap 2707
    python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap 2705 2706 2707 2708
    python monitoring/src/xem_frame.py data/bat_thuong/capture_1910230000_wed.pcap --tu 2700 --den 2712
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from scapy.all import IP, TCP, UDP, PcapReader
from scapy.contrib.mqtt import MQTT, MQTTConnect, MQTTPuback, MQTTPublish

MADRID = ZoneInfo("Europe/Madrid")
MQTT_TYPES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 12: "PINGREQ", 13: "PINGRESP", 14: "DISCONNECT"}


def labels_path(pcap_path: str) -> str:
    """capture_1910230000_wed.pcap -> capture_1910230000_labels.csv (cùng thư mục)."""
    base = os.path.basename(pcap_path)
    return os.path.join(os.path.dirname(pcap_path), base[:len("capture_1910230000")] + "_labels.csv")


def csv_line(pcap_path: str, frame: int) -> str | None:
    """Dòng CSV của frame: dòng 1 là tiêu đề, nên frame N nằm ở dòng N + 1."""
    path = labels_path(pcap_path)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            if i == frame + 1:
                return line.rstrip("\n")
    return None


def describe(n: int, pkt) -> dict:
    t = datetime.fromtimestamp(float(pkt.time), tz=timezone.utc)
    d = {"frame": n, "utc": t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
         "madrid": t.astimezone(MADRID).strftime("%Y-%m-%d %H:%M:%S %z")}
    if pkt.haslayer(IP):
        d["src"], d["dst"] = pkt[IP].src, pkt[IP].dst
    if pkt.haslayer(TCP):
        d.update(proto="TCP", sport=pkt[TCP].sport, dport=pkt[TCP].dport, flags=str(pkt[TCP].flags))
    elif pkt.haslayer(UDP):
        d.update(proto="UDP", sport=pkt[UDP].sport, dport=pkt[UDP].dport)
    msgs, i = [], 1
    while pkt.haslayer(MQTT) and (m := pkt.getlayer(MQTT, nb=i)) is not None:
        x = {"type": MQTT_TYPES.get(m.type, m.type), "qos": m.QOS, "dup": m.DUP}
        if m.haslayer(MQTTConnect):
            c = m[MQTTConnect]
            x.update(clientId=c.clientId.decode(), keepalive=c.klive, clean_session=c.cleansess)
        if m.haslayer(MQTTPublish):
            p = m[MQTTPublish]
            x.update(topic=p.topic.decode(), msgid=p.msgid, payload=p.value.decode(errors="replace"))
        if m.haslayer(MQTTPuback):
            x["msgid"] = m[MQTTPuback].msgid
        msgs.append(x)
        i += 1
    d["mqtt"] = msgs
    return d


def read_frames(pcap_path: str, frames: set[int]) -> dict[int, dict]:
    out, last = {}, max(frames)
    with PcapReader(pcap_path) as rd:
        for n, pkt in enumerate(rd, start=1):
            if n in frames:
                out[n] = describe(n, pkt)
            if n >= last:
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap", help="đường dẫn file .pcap gốc")
    ap.add_argument("frames", nargs="*", type=int, help="số frame (giống cột No. trong Wireshark)")
    ap.add_argument("--tu", type=int, help="frame bắt đầu (kèm --den)")
    ap.add_argument("--den", type=int, help="frame kết thúc")
    a = ap.parse_args()
    frames = set(a.frames)
    if a.tu and a.den:
        frames |= set(range(a.tu, a.den + 1))
    if not frames:
        sys.exit("Cần ít nhất một số frame, hoặc --tu và --den.")
    found = read_frames(a.pcap, frames)
    for n in sorted(frames):
        if n not in found:
            print(f"frame {n}: không có trong file")
            continue
        d = found[n]
        head = f"frame {n} | UTC {d['utc']} | Madrid {d['madrid']} | {d.get('proto', '?')} {d.get('src')}:{d.get('sport', '')} → {d.get('dst')}:{d.get('dport', '')}"
        if "flags" in d:
            head += f" | cờ TCP {d['flags']}"
        print(head)
        for m in d["mqtt"]:
            print("    MQTT", ", ".join(f"{k}={v}" for k, v in m.items()))
        line = csv_line(a.pcap, n)
        if line is not None:
            print(f"    CSV dòng {n + 1}: {line}")


if __name__ == "__main__":
    main()
