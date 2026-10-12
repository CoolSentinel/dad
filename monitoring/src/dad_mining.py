"""Khai thác bộ DAD để lấy thông số cho hệ thống giám sát.

Gồm: đọc tầng mạng (TCP/UDP/MQTT) từ PCAP, dựng bảng chuỗi theo node, dựng danh sách sự cố
(ground truth), các bộ phát hiện chỉ dùng dữ liệu quá khứ, và hàm chấm ở mức sự kiện.
"""
from __future__ import annotations

import glob
import os
import re

import numpy as np
import pandas as pd

from dad_loader import DAYS, DAY_RE

PERIOD_S = 300.1          # chu kỳ gửi chuẩn đo được
SILENCE_FACTOR = 1.5      # D1: im lặng quá 1,5 chu kỳ
BURST_FACTOR = 0.8        # D2: bản tin đến sớm hơn 0,8 chu kỳ, cùng kết nối
BASE_WINDOW = 288         # baseline = trung vị 288 bản tin trước (1 ngày), chỉ dùng quá khứ
DEV_T = 0.8               # D4: lệch dưới baseline quá 0,8 °C
DEV_K, DEV_W = 3, 6       # D4: ít nhất 3 trong 6 chu kỳ gần nhất


def parse_network(raw_dir: str, cache: str | None = None) -> pd.DataFrame:
    """Mỗi frame một dòng, giữ thông tin tầng IP/TCP/UDP/MQTT (cổng, cờ, msgid, CONNECT...)."""
    if cache and os.path.exists(cache):
        return pd.read_pickle(cache)
    from scapy.all import IP, TCP, UDP, PcapReader
    from scapy.contrib.mqtt import MQTT, MQTTConnect, MQTTPuback, MQTTPublish

    rows = []
    files = sorted(glob.glob(os.path.join(raw_dir, "capture_*.pcap")),
                   key=lambda x: DAYS.index(DAY_RE.search(x).group(2)))
    for f in files:
        day = DAY_RE.search(os.path.basename(f)).group(2)
        with PcapReader(f) as rd:
            for n, pk in enumerate(rd, start=1):
                ip = pk[IP]
                r = dict(day=day, frame=n, ts=float(pk.time), src=ip.src, dst=ip.dst, length=len(pk))
                if pk.haslayer(UDP):
                    r.update(proto="UDP", sport=pk[UDP].sport, dport=pk[UDP].dport)
                elif pk.haslayer(TCP):
                    t = pk[TCP]
                    r.update(proto="TCP", sport=t.sport, dport=t.dport, seq=t.seq,
                             tcp_flags=str(t.flags), plen=len(t.payload))
                    if pk.haslayer(MQTT):
                        m = pk[MQTT]
                        r.update(mtype=m.type, qos=m.QOS, dup=m.DUP)
                        if pk.haslayer(MQTTPuback):
                            r["msgid"] = pk[MQTTPuback].msgid
                        if pk.haslayer(MQTTPublish):
                            r["msgid"] = pk[MQTTPublish].msgid
                            r["payload"] = pk[MQTTPublish].value.decode(errors="replace")
                        if pk.haslayer(MQTTConnect):
                            c = pk[MQTTConnect]
                            r.update(client_id=c.clientId.decode(), keepalive=c.klive,
                                     clean_session=c.cleansess)
                rows.append(r)
    d = pd.DataFrame(rows)
    d["time"] = pd.to_datetime(d.ts, unit="s", utc=True).dt.tz_convert("Europe/Madrid")
    # khoá kết nối nhìn từ phía client, để ghép PUBLISH với PUBACK
    to_broker = d.dport == 1883
    d["conn"] = np.where(to_broker, d.src + ":" + d.sport.astype("Int64").astype(str),
                         d.dst + ":" + d.dport.astype("Int64").astype(str))
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        d.to_pickle(cache)
    return d


def add_baseline(pubs: pd.DataFrame) -> pd.DataFrame:
    """dev = giá trị - trung vị BASE_WINDOW bản tin trước của chính cảm biến đó (không nhìn tương lai)."""
    pubs = pubs.sort_values(["client_id", "ts"]).copy()
    pubs["new_conn"] = pubs.groupby("client_id").sport.shift() != pubs.sport
    pubs["base"] = pubs.groupby("client_id").value.transform(
        lambda s: s.shift().rolling(BASE_WINDOW, min_periods=24).median())
    pubs["dev"] = pubs.value - pubs.base
    pubs["slot"] = pubs.time_utc.dt.floor("5min")
    return pubs


def node_slots(pubs: pd.DataFrame) -> pd.DataFrame:
    """Gộp 4 cảm biến của một InRow theo chu kỳ 5 phút, rồi tính các đặc trưng cửa sổ trượt."""
    n = (pubs.groupby(["inrow", "slot"])
             .agg(dev=("dev", "mean"), label=("label", "max"), day=("day", "first"),
                  time=("time", "first"), n_msg=("value", "size"))
             .reset_index().sort_values(["inrow", "slot"]))
    g = n.groupby("inrow")
    n["absd"] = g.dev.diff().abs()
    n["vol6"] = g.absd.transform(lambda s: s.rolling(6).mean())
    n["neg"] = n.dev < -DEV_T
    n["neg_count6"] = g.neg.transform(lambda s: s.rolling(DEV_W).sum())
    n["mean_dev6"] = -g.dev.transform(lambda s: s.rolling(DEV_W).mean())
    n["abs_count6"] = g.dev.transform(lambda s: (s.abs() > DEV_T).rolling(DEV_W).sum())
    return n


def _windows(times: pd.Series, gap: str = "30min") -> pd.DataFrame:
    t = times.sort_values()
    grp = (t.diff() > pd.Timedelta(gap)).cumsum()
    return pd.DataFrame({"start": t.groupby(grp).min(), "end": t.groupby(grp).max()})


def ground_truth(pubs: pd.DataFrame, inrow: int = 13) -> pd.DataFrame:
    """Cửa sổ có nhãn (gộp nhãn cách nhau < 30 phút) + cửa sổ mất gói (khoảng hở > 1,5 chu kỳ)."""
    r = pubs[pubs.inrow == inrow]
    lab = _windows(r[r.label == 1].time_utc).assign(kind="labeled")
    gp = r[r.gap_s > SILENCE_FACTOR * PERIOD_S]
    iv = sorted(zip(gp.time_utc - pd.to_timedelta(gp.gap_s, unit="s"), gp.time_utc))
    merged: list[list] = []
    for a, b in iv:
        if merged and a <= merged[-1][1] + pd.Timedelta("30min"):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    inter = pd.DataFrame(merged, columns=["start", "end"]).assign(kind="interception")
    gt = pd.concat([lab, inter]).sort_values("start").reset_index(drop=True)
    gt["inrow"] = inrow
    loc = lambda s: s.dt.tz_convert("Europe/Madrid")
    gt["local"] = loc(gt.start).dt.strftime("%a %d/%m %H:%M") + "–" + loc(gt.end).dt.strftime("%H:%M")
    gt["dur_min"] = ((gt.end - gt.start).dt.total_seconds() / 60).round(0)
    return gt


def alarms(pubs: pd.DataFrame, nodes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Thời điểm hệ thống real-time có thể bắn cảnh báo, cho từng bộ phát hiện."""
    out = {}
    s = pubs[pubs.gap_s > SILENCE_FACTOR * PERIOD_S]
    # im lặng được phát hiện khi hết hạn chờ, không phải khi bản tin kế tiếp tới
    out["D1 im lặng"] = pd.DataFrame({"inrow": s.inrow, "t": s.time_utc - pd.to_timedelta(
        s.gap_s - SILENCE_FACTOR * PERIOD_S, unit="s")})
    s = pubs[(pubs.gap_s < BURST_FACTOR * PERIOD_S) & ~pubs.new_conn]
    out["D2 gửi dồn"] = pd.DataFrame({"inrow": s.inrow, "t": s.time_utc})
    over = nodes.vol6 > 1.0
    run = over.groupby(nodes.inrow).transform(lambda x: x.groupby((~x).cumsum()).cumsum())
    s = nodes[run >= 2]
    out["D3 biến động (cũ)"] = pd.DataFrame({"inrow": s.inrow, "t": s.slot + pd.Timedelta("5min")})
    s = nodes[nodes.neg_count6 >= DEV_K]
    out["D4 lệch âm 3/6 (mới)"] = pd.DataFrame({"inrow": s.inrow, "t": s.slot + pd.Timedelta("5min")})
    return out


def evaluate(alarm: pd.DataFrame, gt: pd.DataFrame, margin: str = "15min", merge: str = "20min"):
    """Gộp cảnh báo thành sự kiện; sự kiện đúng nếu chồng lên một cửa sổ ground truth (± margin).

    Trả về (bảng sự kiện, Series độ trễ phút theo từng cửa sổ ground truth).
    """
    m = pd.Timedelta(margin)
    if alarm.empty:
        return (pd.DataFrame(columns=["inrow", "start", "end", "n", "dung"]).astype({"dung": bool}),
                pd.Series(np.nan, index=gt.index))
    a = alarm.sort_values(["inrow", "t"])
    new = (a.groupby("inrow").t.diff() > pd.Timedelta(merge)) | (a.inrow != a.inrow.shift())
    ev = a.assign(e=new.cumsum()).groupby("e").agg(inrow=("inrow", "first"), start=("t", "min"),
                                                   end=("t", "max"), n=("t", "size"))
    ev["dung"] = ev.apply(lambda r: bool(((gt.inrow == r.inrow) & (gt.start - m <= r.end)
                                          & (gt.end + m >= r.start)).any()), axis=1)
    delay = {}
    for i, g in gt.iterrows():
        x = a[(a.inrow == g.inrow) & (a.t >= g.start - m) & (a.t <= g.end + m)]
        delay[i] = round((x.t.min() - g.start).total_seconds() / 60, 1) if len(x) else np.nan
    return ev.reset_index(drop=True), pd.Series(delay)
