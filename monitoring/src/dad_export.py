"""Xuất bộ DAD gốc (PCAP + CSV nhãn) thành các collection sẵn sàng nạp vào MongoDB.

Chạy:  python src/dad_export.py            (đọc PCAP ở gốc repo, ghi data/mongo/*.ndjson.gz)

Mỗi file là NDJSON theo MongoDB Extended JSON (relaxed): ngày giờ dạng {"$date": "...Z"},
nên nạp được bằng `mongoimport` hoặc `src/dad_mongo_load.py`.

Collection                Số document  Dùng để
telemetry_hist            32.288       chuỗi nhiệt độ gốc (time series), nguồn cho replay và phân tích
devices                   16           hồ sơ 16 cảm biến: loại, dải giá trị, baseline ban đầu
inrows                    4            hồ sơ 4 tủ làm mát
mqtt_sessions             112          mỗi kết nối MQTT một ngày: keepalive, số bản tin, số bản tin không được ACK
traffic_daily             35           số gói theo ngày × IP × loại (đối chiếu Table 5/6 của bài báo)
gt_labels                 544          bản tin PUBLISH có nhãn 1 (chỉ để chấm, không dùng để phát hiện)
gt_incidents              11           cửa sổ sự cố chuẩn + kết quả điều tra
detector_config           1            ngưỡng D1/D2/D4/INV/RANGE
demo_scenarios            4            đoạn dữ liệu nên replay cho video demo
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dad_mining as dm  # noqa: E402
from dad_loader import BROKER_IP, DAYS, INROW_IP, load_all  # noqa: E402

SITE = "CITIC-DC"
SENSOR_INFO = {  # ánh xạ theo giá trị đo (notebook 00 mục 7); tên đầy đủ theo bài báo
    "TFEU": ("Unit Entering Fluid Temperature", "nước lạnh đi vào tủ", 1),
    "TFSU": ("Unit Leaving Fluid Temperature", "nước đi ra khỏi tủ", 2),
    "TAS": ("Unit Supply Air Temperature", "khí cấp ra lối lạnh", 3),
    "TAR": ("Unit Return Air Temperature", "khí hồi từ lối nóng", 4),
}
NETBOTZ = {13: "NETBOTZ 1", 15: "NETBOTZ 1", 23: "NETBOTZ 2", 25: "NETBOTZ 2"}  # Hình 1 bài báo
# Table 1 bài báo: 14 ngày đo thật (mean, sd, min, max, median)
REAL_TABLE1 = {
    (13, "TAS"): (20.00, .38, 18.2, 20.9, 19.9), (13, "TAR"): (27.33, .24, 26.1, 28.1, 27.3),
    (13, "TFEU"): (11.94, .93, 9.4, 14.3, 11.8), (13, "TFSU"): (15.89, .79, 13.9, 17.8, 15.8),
    (15, "TAS"): (20.00, .42, 18.0, 21.2, 19.9), (15, "TAR"): (27.20, .25, 25.1, 27.9, 27.2),
    (15, "TFEU"): (11.69, .98, 9.1, 14.2, 11.6), (15, "TFSU"): (15.37, .89, 13.2, 17.8, 15.2),
    (23, "TAS"): (20.00, .34, 18.3, 20.8, 20.0), (23, "TAR"): (26.29, .27, 25.2, 27.3, 26.3),
    (23, "TFEU"): (11.14, 1.00, 8.1, 13.6, 11.0), (23, "TFSU"): (14.95, .88, 12.8, 17.4, 14.8),
    (25, "TAS"): (20.00, .37, 17.9, 21.1, 20.1), (25, "TAR"): (26.79, .22, 25.7, 27.6, 26.8),
    (25, "TFEU"): (11.24, 1.00, 8.5, 13.9, 11.1), (25, "TFSU"): (15.34, .88, 13.2, 17.7, 15.2),
}
RANGE_MARGIN_C = 2.0   # nới dải thật 2 °C: 0 vi phạm trên dữ liệu DAD bình thường (notebook 02 mục 7.2)


def _dt(x) -> datetime | None:
    """pandas/float epoch -> datetime UTC (BSON lưu tới mili-giây)."""
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NaT:
        return None
    if isinstance(x, (int, float, np.floating)):
        return datetime.fromtimestamp(float(x), tz=timezone.utc)
    return pd.Timestamp(x).tz_convert("UTC").floor("us").to_pydatetime()


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def build(raw_dir: str, cache_dir: str) -> dict[str, list[dict]]:
    packets, pubs = load_all(raw_dir, cache_dir)
    net = dm.parse_network(raw_dir, os.path.join(cache_dir, "network.pkl"))
    pubs = dm.add_baseline(pubs)
    nodes = dm.node_slots(pubs)
    gt = dm.ground_truth(pubs)
    out: dict[str, list[dict]] = {}

    # --- PUBACK latency cho từng PUBLISH (ghép theo kết nối + msgid)
    ack = net[net.mtype == 4][["conn", "msgid", "ts"]].rename(columns={"ts": "ack_ts"})
    pa = net[net.mtype == 3][["day", "frame", "conn", "msgid", "ts"]].merge(ack, on=["conn", "msgid"], how="left")
    pa["puback_ms"] = (pa.ack_ts - pa.ts) * 1000
    pubs = pubs.merge(pa[["day", "frame", "puback_ms"]], on=["day", "frame"], how="left")
    pubs["conn"] = pubs.src + ":" + pubs.sport.astype(int).astype(str)

    # --- telemetry_hist: KHÔNG chứa nhãn (nhãn ở gt_labels) để bộ phát hiện không "nhìn trộm"
    out["telemetry_hist"] = [_clean({
        "ts": _dt(r.ts),
        "meta": {"site": SITE, "inrow": int(r.inrow), "sensor": r.sensor, "clientId": r.client_id, "ip": r.src},
        "value": r.value, "seq": int(r.msgid), "conn": r.conn,
        "puback_ms": None if pd.isna(r.puback_ms) else round(float(r.puback_ms), 3),
        "src": {"day": str(r.day), "frame": int(r.frame)},
    }) for r in pubs.sort_values("ts").itertuples()]

    # --- devices: 16 cảm biến
    clean = pubs[(pubs.inrow != 13) | pubs.day.isin(["mon", "sun"])]
    mon = pubs[pubs.day == "mon"]
    devs = []
    for cid, g in pubs.groupby("client_id"):
        inrow, sensor = int(g.inrow.iloc[0]), g.sensor.iloc[0]
        c = clean[clean.client_id == cid].value
        mean_r, sd_r, min_r, max_r, med_r = REAL_TABLE1[(inrow, sensor)]
        ranges = [REAL_TABLE1[(i, sensor)] for i in (13, 15, 23, 25)]
        devs.append(_clean({
            "_id": cid, "clientId": cid, "inrow": inrow, "ip": g.src.iloc[0], "position": int(cid[2]),
            "sensor": sensor, "sensor_name": SENSOR_INFO[sensor][0], "measures_vi": SENSOR_INFO[sensor][1],
            "physical_order": SENSOR_INFO[sensor][2],
            "expected_period_s": dm.PERIOD_S,
            "profile_dad": {"mean": round(c.mean(), 3), "std": round(c.std(), 3), "p01": round(c.quantile(.01), 2),
                            "p99": round(c.quantile(.99), 2), "min": c.min(), "max": c.max(), "n": int(len(c))},
            "profile_real_paper": {"mean": mean_r, "sd": sd_r, "min": min_r, "max": max_r, "median": med_r},
            "valid_range_c": [round(min(r[2] for r in ranges) - RANGE_MARGIN_C, 1), round(max(r[3] for r in ranges) + RANGE_MARGIN_C, 1)],
            "baseline_init": round(float(mon[mon.client_id == cid].value.median()), 3),
            "quality": "ok", "rate_limited": False,
        }))
    out["devices"] = devs

    # --- inrows: 4 tủ làm mát
    ntp_src = set(net[(net.proto == "UDP") & (net.dport == 123)].src)
    out["inrows"] = [_clean({
        "_id": inrow, "inrow": inrow, "ip": ip, "site": SITE, "netbotz": NETBOTZ[inrow],
        "clients": sorted(pubs[pubs.inrow == inrow].client_id.unique().tolist()),
        "ntp_seen_in_capture": ip in ntp_src,
        "note": "NTP qua card mạng thứ hai (theo bài báo)" if ip not in ntp_src else "",
    }) for ip, inrow in sorted(INROW_IP.items(), key=lambda x: x[1])]

    # --- mqtt_sessions: mỗi kết nối (ip:port) một document
    con = net[net.mtype == 1][["day", "ts", "conn", "client_id", "keepalive", "clean_session"]]
    disc = net[(net.mtype == 14)].groupby("conn").ts.max().rename("disconnect_ts")
    p_by = pubs.groupby("conn").agg(n_publish=("ts", "size"), first_pub=("ts", "min"), last_pub=("ts", "max"),
                                    first_seq=("msgid", "min"), last_seq=("msgid", "max"),
                                    n_unacked=("puback_ms", lambda s: int(s.isna().sum())),
                                    puback_p99_ms=("puback_ms", lambda s: s.quantile(.99)))
    ses = con.set_index("conn").join(disc).join(p_by).reset_index()
    out["mqtt_sessions"] = [_clean({
        "_id": r.conn + "@" + r.day, "conn": r.conn, "clientId": r.client_id, "inrow": int(r.client_id[:2]),
        "ip": r.conn.split(":")[0], "port": int(r.conn.split(":")[1]), "capture_day": r.day,
        "connect_ts": _dt(r.ts), "disconnect_ts": _dt(r.disconnect_ts), "first_publish_ts": _dt(r.first_pub),
        "last_publish_ts": _dt(r.last_pub), "keepalive_s": int(r.keepalive), "clean_session": bool(r.clean_session),
        "n_publish": r.n_publish, "first_seq": r.first_seq, "last_seq": r.last_seq, "n_unacked": r.n_unacked,
        "puback_p99_ms": None if pd.isna(r.puback_p99_ms) else round(float(r.puback_p99_ms), 3),
    }) for r in ses.itertuples()]

    # --- traffic_daily: số gói theo ngày × IP nguồn × loại
    kind = np.select([net.mtype.eq(3), net.mtype.eq(4), net.mtype.isin([1, 2, 14]), net.proto.eq("TCP") & net.mtype.isna(),
                      net.dport.eq(123) | net.sport.eq(123), net.dport.eq(137)],
                     ["publish", "puback", "session", "tcp_control", "ntp", "netbios"], "other")
    lab_pk = packets[["day", "frame", "label"]]
    t = net.assign(kind=kind).merge(lab_pk, on=["day", "frame"], how="left")
    td = t.pivot_table(index=["day", "src"], columns="kind", values="frame", aggfunc="count", fill_value=0)
    lb = t.groupby(["day", "src"]).agg(packets=("frame", "size"), bytes=("length", "sum"), labeled=("label", "sum"))
    td = td.join(lb).reset_index()
    out["traffic_daily"] = [_clean({
        "_id": f"{r['day']}|{r['src']}", "day": r["day"], "ip": r["src"],
        "role": "broker" if r["src"] == BROKER_IP else f"InRow {INROW_IP[r['src']]}",
        "packets": r["packets"], "bytes": r["bytes"], "labeled_packets": r["labeled"],
        "by_kind": {k: r[k] for k in ["publish", "puback", "session", "tcp_control", "ntp", "netbios"] if k in r},
    }) for _, r in td.iterrows()]

    # --- gt_labels: 544 bản tin có nhãn 1
    l1 = pubs[pubs.label == 1]
    out["gt_labels"] = [_clean({"ts": _dt(r.ts), "clientId": r.client_id, "inrow": int(r.inrow), "seq": int(r.msgid),
                                "conn": r.conn, "src": {"day": str(r.day), "frame": int(r.frame)}, "label": 1})
                        for r in l1.itertuples()]

    # --- gt_incidents: 11 cửa sổ + điều tra
    inc = []
    for i, g in gt.iterrows():
        w = pubs[(pubs.inrow == g.inrow) & (pubs.time_utc >= g.start - pd.Timedelta("5min")) & (pubs.time_utc <= g.end + pd.Timedelta("5min"))]
        nn = nodes[(nodes.inrow == g.inrow) & (nodes.slot >= g.start.floor("5min")) & (nodes.slot <= g.end)]
        lost = int(((w.gap_s / dm.PERIOD_S).round() - 1).clip(lower=0)[w.gap_s > dm.SILENCE_FACTOR * dm.PERIOD_S].sum())
        extra = int(((w.gap_s < dm.BURST_FACTOR * dm.PERIOD_S) & ~w.new_conn).sum())
        drops = nn.dev[nn.dev < -dm.DEV_T]
        kinds = [k for k, c in [("interception", lost > 0), ("duplication", extra > 0), ("modification", len(drops) >= dm.DEV_K)] if c]
        inc.append(_clean({
            "_id": f"GT-{i + 1:02d}", "inrow": int(g.inrow), "source": "label" if g.kind == "labeled" else "gap_rule",
            "start": _dt(g.start), "end": _dt(g.end), "local": g.local, "duration_min": g.dur_min, "kinds": kinds,
            "evidence": {"lost_msgs": lost, "extra_msgs": extra, "dropped_slots": int(len(drops)),
                         "drop_c": (int(-drops.round().mode().iloc[0]) if len(drops) else None), "sensors": int(w.client_id.nunique()),
                         "labeled_msgs": int(w.label.sum())},
        }))
    out["gt_incidents"] = inc

    # --- detector_config
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "outputs", "detector_config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    cfg.update({"_id": "default", "period_s": dm.PERIOD_S, "silence_factor": dm.SILENCE_FACTOR, "burst_factor": dm.BURST_FACTOR,
                "baseline_window": dm.BASE_WINDOW, "dev_threshold_c": dm.DEV_T, "dev_k": dm.DEV_K, "dev_w": dm.DEV_W,
                "valid_range_c": {d["sensor"]: d["valid_range_c"] for d in devs}})
    out["detector_config"] = [_clean(cfg)]

    # --- demo_scenarios: đoạn nên replay (giờ UTC; khung giờ địa phương trong `local`)
    sc = [("warmup", "mon", "2019-10-20T22:00:00Z", "2019-10-21T22:00:00Z", "nạp trước làm baseline, không cần tua", []),
          ("duplication", "thu", "2019-10-24T00:50:00Z", "2019-10-24T01:35:00Z", "chèn bản tin 03:05–03:22 giờ địa phương", ["D2"]),
          ("modification", "wed", "2019-10-23T01:45:00Z", "2019-10-23T04:35:00Z", "sửa giá trị 04:10–06:15 giờ địa phương", ["D4"]),
          ("interception", "fri", "2019-10-25T01:15:00Z", "2019-10-25T03:10:00Z", "chặn gói 03:25–05:00 giờ địa phương", ["D1"])]
    out["demo_scenarios"] = [{"_id": n, "capture_day": d, "start": _dt(pd.Timestamp(s)), "end": _dt(pd.Timestamp(e)),
                              "note": note, "expected_detectors": det} for n, d, s, e, note, det in sc]
    return out


def write(cols: dict[str, list[dict]], out_dir: str) -> pd.DataFrame:
    from bson import json_util
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for name, docs in cols.items():
        path = os.path.join(out_dir, f"{name}.ndjson.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for d in docs:
                f.write(json_util.dumps(d, json_options=json_util.RELAXED_JSON_OPTIONS, ensure_ascii=False) + "\n")
        rows.append((name, len(docs), round(os.path.getsize(path) / 1024, 1)))
    man = pd.DataFrame(rows, columns=["collection", "documents", "KB_gzip"])
    man.to_csv(os.path.join(out_dir, "manifest.csv"), index=False)
    return man


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    raw = os.path.abspath(os.path.join(here, "..", ".."))
    cache = os.path.join(here, "..", "data", "processed")
    print(write(build(raw, cache), os.path.join(here, "..", "data", "mongo")).to_string(index=False))
