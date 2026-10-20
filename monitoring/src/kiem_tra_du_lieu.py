"""Kiểm tra dữ liệu khớp tuyệt đối theo chuỗi: PCAP gốc ⇄ CSV ⇄ MongoDB ⇄ dữ liệu gửi Datadog.

Đọc PCAP bằng bộ giải mã viết tay (struct, theo định dạng pcap / Ethernet / IPv4 / TCP / MQTT 3.1.1),
KHÔNG dùng scapy, để độc lập với bộ xuất xuat_mongo.py.

Các nhóm kiểm tra:
  A. PCAP ⇄ CSV nhãn   : số gói = số dòng CSV; mọi PUBLISH khớp frame, IP, cổng, clientId, msgid
  B. PCAP ⇄ telemetry  : đủ, không thừa, không trùng; ts_us, ts, value, seq, meta, conn khớp từng bản tin
  C. PCAP ⇄ latest     : bản tin cuối của từng cảm biến, khoảng cách tới bản tin trước
  D. PCAP ⇄ incidents  : bằng chứng (bản tin mất, đến sớm) tính lại từ PCAP; phủ đủ cửa sổ sự cố (đối chiếu nhãn CSV)
  E. telemetry ⇄ Datadog: mọi điểm trong sổ gửi và trong payload khớp bản tin gốc (giá trị, tag, thời điểm phát lại)
  F. (tuỳ chọn) đọc lại từ Datadog: cần DD_API_KEY, DD_APP_KEY; so điểm đã lưu trên Datadog với sổ gửi

    python monitoring/src/kiem_tra_du_lieu.py            # A–E
    python monitoring/src/kiem_tra_du_lieu.py --datadog  # thêm F
Thoát với mã 1 nếu có bất kỳ lệch nào.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import struct
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(REPO, "data")
DD_OUT = os.path.join(REPO, "monitoring", "data", "datadog_out")
URI = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27018/?replicaSet=rs0")
P_US = 300_100_000
INROW = {"10.6.56.41": 13, "10.6.56.36": 15, "10.6.56.50": 23, "10.6.56.34": 25}
SENSOR = {"1": "TFEU", "2": "TFSU", "3": "TAS", "4": "TAR"}
FILES = ["binh_thuong/capture_1910210000_mon.pcap", "bat_thuong/capture_1910220000_tue.pcap",
         "bat_thuong/capture_1910230000_wed.pcap", "bat_thuong/capture_1910240000_thu.pcap",
         "bat_thuong/capture_1910250000_fri.pcap", "bat_thuong/capture_1910260000_sat.pcap",
         "binh_thuong/capture_1910270000_sun.pcap"]

FAIL: list[str] = []
REPORT: list[tuple[str, str, bool]] = []


def check(group: str, what: str, ok: bool, detail: str = "") -> None:
    REPORT.append((group, what + (f" ({detail})" if detail else ""), bool(ok)))
    if not ok:
        FAIL.append(f"{group}: {what} {detail}")


# ---------------- bộ giải mã PCAP viết tay ----------------
def mqtt_messages(buf: bytes):
    """Tách các bản tin MQTT trong payload TCP: (type, flags, body)."""
    i = 0
    while i < len(buf):
        b0 = buf[i]
        mult, rem, j = 1, 0, i + 1
        while True:
            d = buf[j]
            rem += (d & 0x7F) * mult
            j += 1
            if not d & 0x80:
                break
            mult *= 128
        yield b0 >> 4, b0 & 0x0F, buf[j:j + rem]
        i = j + rem


def read_pcap(path: str):
    """Sinh (frame, ts_us, src_ip, sport, mqtt_list) cho mọi gói; mqtt_list rỗng nếu không phải MQTT."""
    with open(path, "rb") as f:
        gh = f.read(24)
        magic = struct.unpack("<I", gh[:4])[0]
        assert magic == 0xA1B2C3D4, f"chỉ hỗ trợ pcap little-endian micro giây, gặp {magic:#x}"
        n = 0
        while True:
            rh = f.read(16)
            if len(rh) < 16:
                return
            sec, usec, incl, _ = struct.unpack("<IIII", rh)
            pkt = f.read(incl)
            n += 1
            ts_us = sec * 1_000_000 + usec
            if struct.unpack("!H", pkt[12:14])[0] != 0x0800:          # chỉ IPv4
                yield n, ts_us, None, None, []
                continue
            ip = pkt[14:]
            ihl = (ip[0] & 0x0F) * 4
            total = struct.unpack("!H", ip[2:4])[0]
            src = ".".join(map(str, ip[12:16]))
            if ip[9] != 6:                                             # không phải TCP
                yield n, ts_us, src, None, []
                continue
            tcp = ip[ihl:total]
            sport, dport = struct.unpack("!HH", tcp[:4])
            data = tcp[(tcp[12] >> 4) * 4:]
            msgs = list(mqtt_messages(data)) if data and (sport == 1883 or dport == 1883) else []
            yield n, ts_us, src, sport, msgs


def parse_raw():
    """Mọi PUBLISH của cảm biến (đủ trường), mọi DISCONNECT, và số gói mỗi file."""
    conn: dict[tuple[str, int], str] = {}
    pubs, discs, counts = [], [], {}
    for rel in FILES:
        path = os.path.join(DATA, rel)
        last = 0
        for n, ts_us, src, sport, msgs in read_pcap(path):
            last = n
            for typ, flags, body in msgs:
                if typ == 1:                                           # CONNECT
                    plen = struct.unpack("!H", body[:2])[0]
                    k = 2 + plen + 1 + 1 + 2                           # tên giao thức, level, flags, keepalive
                    clen = struct.unpack("!H", body[k:k + 2])[0]
                    conn[(src, sport)] = body[k + 2:k + 2 + clen].decode()
                elif typ == 3 and src in INROW:                        # PUBLISH từ cảm biến
                    qos = (flags >> 1) & 3
                    tlen = struct.unpack("!H", body[:2])[0]
                    topic = body[2:2 + tlen].decode()
                    k = 2 + tlen
                    msgid = struct.unpack("!H", body[k:k + 2])[0] if qos else None
                    payload = body[k + (2 if qos else 0):].decode()
                    cid = conn[(src, sport)]
                    pubs.append({"file": "data/" + rel, "frame": n, "ts_us": ts_us, "ip": src, "port": sport,
                                 "clientId": cid, "inrow": INROW[src], "sensor": SENSOR[cid[-1]], "msgid": msgid,
                                 "topic": topic, "payload": payload, "qos": qos})
                elif typ == 14 and src in INROW:
                    discs.append({"file": "data/" + rel, "frame": n, "ts_us": ts_us, "ip": src})
        counts["data/" + rel] = last
    return pubs, discs, counts


# ---------------- A. PCAP ⇄ CSV ----------------
def check_csv(pubs, counts):
    by_file = defaultdict(dict)
    for p in pubs:
        by_file[p["file"]][p["frame"]] = p
    labels = []
    for f, total in counts.items():
        csv = f[:f.rindex("_")] + "_labels.csv"
        with open(os.path.join(REPO, csv), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        check("A", f"{os.path.basename(csv)}: số dòng = số gói", len(lines) - 1 == total, f"{len(lines) - 1} / {total}")
        bad = 0
        csv_pub_frames = set()
        for line in lines[1:]:
            fr, ip, port, cid, mid, lab = line.split(";")
            fr = int(fr)
            if cid:
                csv_pub_frames.add(fr)
                p = by_file[f].get(fr)
                if not (p and p["ip"] == ip and str(p["port"]) == port.split(".")[0] and p["clientId"] == cid.split(".")[0]
                        and str(p["msgid"]) == mid.split(".")[0]):
                    bad += 1
                if lab == "1":
                    labels.append((f, fr))
        check("A", f"{os.path.basename(csv)}: PUBLISH khớp từng trường với CSV", bad == 0 and csv_pub_frames == set(by_file[f]),
              f"lệch {bad}; CSV {len(csv_pub_frames)} / PCAP {len(by_file[f])}")
    return labels


# ---------------- B. PCAP ⇄ telemetry ----------------
def check_telemetry(db, pubs):
    docs = list(db.telemetry.find({}, {"_id": 0}))
    check("B", "số document = số PUBLISH trong PCAP", len(docs) == len(pubs), f"{len(docs)} / {len(pubs)}")
    keys = Counter((d["src"]["file"], d["src"]["frame"]) for d in docs)
    check("B", "không trùng (file, frame)", max(keys.values()) == 1)
    raw = {(p["file"], p["frame"]): p for p in pubs}
    check("B", "tập (file, frame) trùng khít với PCAP", set(keys) == set(raw))
    bad = Counter()
    for d in docs:
        p = raw.get((d["src"]["file"], d["src"]["frame"]))
        if p is None:
            bad["không có trong PCAP"] += 1
            continue
        if d["ts_us"] != p["ts_us"]: bad["ts_us"] += 1
        if int(d["ts"].timestamp() * 1000) != p["ts_us"] // 1000: bad["ts (mili giây)"] += 1
        if d["value"] != float(p["payload"]) or f"{d['value']:.2f}" != p["payload"]: bad["value"] += 1
        if d["seq"] != p["msgid"]: bad["seq"] += 1
        if d["meta"] != {"inrow": p["inrow"], "sensor": p["sensor"], "clientId": p["clientId"]}: bad["meta"] += 1
        if d["conn"] != f"{p['ip']}:{p['port']}": bad["conn"] += 1
        if "label" in d: bad["có trường nhãn"] += 1
    check("B", "mọi bản tin khớp ts_us, ts, value, seq, meta, conn; không chứa nhãn", not bad, dict(bad) if bad else f"{len(docs)} bản tin")
    return docs


# ---------------- C. PCAP ⇄ latest ----------------
def check_latest(db, pubs):
    by = defaultdict(list)
    for p in pubs:
        by[p["clientId"]].append(p)
    docs = {d["_id"]: d for d in db.latest.find()}
    check("C", "16 cảm biến", set(docs) == set(by), f"{len(docs)}")
    bad = 0
    for cid, ps in by.items():
        ps.sort(key=lambda p: p["ts_us"])
        cur, prev = ps[-1], ps[-2]
        d = docs.get(cid, {})
        ok = (d.get("ts_us") == cur["ts_us"] and d.get("value") == float(cur["payload"]) and d.get("seq") == cur["msgid"]
              and d.get("src") == {"file": cur["file"], "frame": cur["frame"]}
              and d.get("prev_src") == {"file": prev["file"], "frame": prev["frame"]}
              and d.get("gap_s") == round((cur["ts_us"] - prev["ts_us"]) / 1e6, 6))
        bad += not ok
    check("C", "bản tin cuối và khoảng cách tới bản tin trước khớp PCAP", bad == 0, f"lệch {bad}")


# ---------------- D. PCAP ⇄ incidents ----------------
def check_incidents(db, pubs, discs, labels):
    by = defaultdict(list)
    for p in pubs:
        by[p["clientId"]].append(p)
    holes, early = [], []
    for cid, ps in by.items():
        ps.sort(key=lambda p: (p["ts_us"], p["file"], p["frame"]))
        for a, b in zip(ps, ps[1:]):
            gap = b["ts_us"] - a["ts_us"]
            if gap * 2 > 3 * P_US:                                     # > 1,5 P
                holes.append({"inrow": b["inrow"], "d1_us": a["ts_us"] + 3 * P_US // 2, "lost": round(gap / P_US) - 1,
                              "start": a["ts_us"], "end": b["ts_us"]})
            if gap * 5 < 4 * P_US and a["port"] == b["port"]:          # < 0,8 P, cùng kết nối
                early.append({"inrow": b["inrow"], "ts_us": b["ts_us"]})
    check("D", "tổng bản tin mất (tính từ PCAP)", sum(h["lost"] for h in holes) == 180, str(sum(h["lost"] for h in holes)))
    check("D", "tổng bản tin đến sớm (tính từ PCAP)", len(early) == 248, str(len(early)))
    # baseline độc lập: trung vị 288 bản tin TRƯỚC của chính cảm biến (cần ít nhất 24), dev = giá trị − baseline
    from statistics import median
    slot_devs = defaultdict(list)
    for cid, ps in by.items():
        vals = []
        for p in ps:                                                   # ps đã sắp theo thời gian ở trên
            if len(vals) >= 24:
                slot = p["ts_us"] // 300_000_000 * 300_000_000         # ô 5 phút theo UTC
                slot_devs[(p["inrow"], slot)].append(float(p["payload"]) - median(vals[-288:]))
            vals.append(float(p["payload"]))
    node_dev = {k: sum(v) / len(v) for k, v in slot_devs.items()}
    incs = list(db.incidents.find())
    raw_keys = {(p["file"], p["frame"]) for p in pubs}
    bad = 0
    for inc in incs:
        lo, hi = inc["detected_us"] - 1_000_000, inc["last_alarm_us"] + 1_000_000
        lost = sum(h["lost"] for h in holes if h["inrow"] == inc["inrow"] and lo <= h["d1_us"] <= hi)
        n_early = sum(1 for e in early if e["inrow"] == inc["inrow"] and lo <= e["ts_us"] <= hi)
        frames_ok = all((s["file"], s["frame"]) in raw_keys for s in inc["src_frames"])
        neg = [d for (r, slot), d in node_dev.items() if r == inc["inrow"] and inc["detected_us"] - 1_800_000_000 <= slot <= inc["last_alarm_us"] and d < -0.8]
        mode = int(-min(Counter(round(d) for d in neg).most_common(), key=lambda x: (-x[1], x[0]))[0]) if neg else 0
        ok = (lost == inc["evidence"]["ban_tin_mat"] and n_early == inc["evidence"]["ban_tin_den_som"] and frames_ok
              and len(neg) == inc["evidence"]["slot_lech_am"] and mode == inc["evidence"]["muc_tru_C"])
        if not ok:
            print("  lệch:", inc["_id"], inc["evidence"], {"lost": lost, "early": n_early, "neg": len(neg), "mode": mode, "frames": frames_ok})
        bad += not ok
    check("D", "bằng chứng từng sự cố (mất, đến sớm, slot lệch âm, mức trừ, frame) tính lại từ PCAP khớp", bad == 0, f"{len(incs)} sự cố, lệch {bad}")
    # thời điểm phát hiện phải truy ngược được về đúng bản tin gốc (đến micro giây)
    early_ts = {(e["inrow"], e["ts_us"]) for e in early}
    d1_ts = {(h["inrow"], h["start"] + 3 * P_US // 2) for h in holes}
    def traced(inc):
        r, t = inc["inrow"], inc["detected_us"]
        if (r, t) in early_ts:
            return "D2"
        if any(abs(t - x) <= 1 for (rr, x) in d1_ts if rr == r):
            return "D1"
        if t % 300_000_000 == 0:
            return "D4"
        return None
    tr = [traced(i) for i in incs]
    check("D", "thời điểm phát hiện truy ngược đúng bản tin gốc (D2: bản tin đến sớm; D1: bản tin cuối + 1,5 P; D4: mốc slot)",
          all(t is not None and t in i["rules"] for t, i in zip(tr, incs)), f"{sum(t is not None for t in tr)}/{len(incs)}")
    check("D", "tổng bằng chứng của các sự cố = tổng trong PCAP",
          sum(i["evidence"]["ban_tin_mat"] for i in incs) == 180 and sum(i["evidence"]["ban_tin_den_som"] for i in incs) == 248)

    # cửa sổ sự cố chuẩn: nhãn CSV gộp cách nhau < 30 phút; khoảng hở > 1,5 P gộp cách nhau < 30 phút
    lab_ts = sorted(next(p["ts_us"] for p in pubs if (p["file"], p["frame"]) == k) for k in labels)
    def windows(intervals, gap_us=30 * 60 * 1_000_000):
        """Gộp các đoạn [đầu, cuối] cách nhau dưới 30 phút (cùng cách dựng ground truth trong báo cáo)."""
        out = []
        for a, b in sorted(intervals):
            if out and a <= out[-1][1] + gap_us:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return out
    win = windows([(t, t) for t in lab_ts]) + windows([(h["start"], h["end"]) for h in holes])
    margin = 15 * 60 * 1_000_000
    covered = sum(any(i["detected_us"] <= w[1] + margin and i["last_alarm_us"] >= w[0] - margin for i in incs) for w in win)
    false_inc = sum(not any(i["detected_us"] <= w[1] + margin and i["last_alarm_us"] >= w[0] - margin for w in win) for i in incs)
    check("D", "phủ đủ cửa sổ sự cố chuẩn (nhãn CSV + khoảng hở)", covered == len(win) == 11, f"{covered}/{len(win)}")
    check("D", "không có sự cố ngoài cửa sổ chuẩn (báo giả)", false_inc == 0, str(false_inc))


# ---------------- E. telemetry ⇄ Datadog ----------------
def check_datadog_files(pubs):
    run = json.load(open(os.path.join(DD_OUT, "run.json")))
    with gzip.open(os.path.join(DD_OUT, "journal.ndjson.gz"), "rt", encoding="utf-8") as f:
        journal = [json.loads(l) for l in f]
    sel = [p for p in pubs if (run["tu"] is None or p["ts_us"] >= _iso(run["tu"])) and (run["den"] is None or p["ts_us"] <= _iso(run["den"]))]
    sel.sort(key=lambda p: (p["ts_us"], p["file"], p["frame"]))
    first = sel[0]["ts_us"]
    check("E", "điểm đầu tiên khớp", first == run["first_ts_us"])
    raw = {(p["file"], p["frame"]): p for p in sel}
    prev, expect = {}, []
    for p in sel:
        tags = [f"inrow:{p['inrow']}", f"sensor:{p['sensor'].lower()}", f"client_id:{p['clientId']}", "source:dad_replay"]
        ts = run["t0"] + (p["ts_us"] - first) // (run["speed"] * 1_000_000)
        expect.append(("dad.temp", tuple(tags), ts, float(p["payload"]), p["file"], p["frame"]))
        if p["clientId"] in prev:
            expect.append(("dad.gap_p", tuple(tags), ts, round((p["ts_us"] - prev[p["clientId"]]) / P_US, 6), p["file"], p["frame"]))
        prev[p["clientId"]] = p["ts_us"]
    got = [(j["metric"], tuple(j["tags"]), j["timestamp"], j["value"], j["src"]["file"], j["src"]["frame"]) for j in journal]
    check("E", "sổ gửi: số điểm", len(got) == len(expect), f"{len(got)} / {len(expect)}")
    check("E", "sổ gửi: từng điểm (metric, tag, thời điểm phát lại, giá trị, frame gốc) khớp PCAP", Counter(got) == Counter(expect))
    series_ts = Counter((m, t, ts) for m, t, ts, *_ in expect)
    check("E", "không có hai điểm cùng series cùng giây (Datadog sẽ đè nhau)", max(series_ts.values()) == 1)
    pay = os.path.join(DD_OUT, "payloads.ndjson.gz")
    if os.path.exists(pay) and not run["live"]:
        pts, sizes = Counter(), []
        with gzip.open(pay, "rt", encoding="utf-8") as f:
            for line in f:
                sizes.append(len(line.encode()))
                for s in json.loads(line)["series"]:
                    for pt in s["points"]:
                        pts[(s["metric"], tuple(s["tags"]), pt["timestamp"], pt["value"])] += 1
                    if s["type"] != 3:
                        FAIL.append("E: series không phải gauge")
        check("E", "payload Datadog: đúng bằng các điểm trong sổ gửi", pts == Counter(e[:4] for e in expect), f"{sum(pts.values())} điểm")
        check("E", "payload Datadog: mỗi payload < 512000 byte", max(sizes) < 512_000, f"lớn nhất {max(sizes)}")
    return journal, run


def _iso(s: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1_000_000)


# ---------------- F. đọc lại từ Datadog ----------------
def check_datadog_live(journal, run):
    api, app = os.environ.get("DD_API_KEY"), os.environ.get("DD_APP_KEY")
    if not (api and app):
        check("F", "đọc lại từ Datadog", False, "thiếu DD_API_KEY / DD_APP_KEY")
        return
    site = os.environ.get("DD_SITE", "datadoghq.com")
    by_series = defaultdict(dict)
    for j in journal:
        if j["metric"] == "dad.temp":
            by_series[j["tags"][2]][j["timestamp"]] = j["value"]
    bad = missing = 0
    for cid_tag, pts in sorted(by_series.items()):
        ts = sorted(pts)
        for a in range(0, len(ts), 1000):                          # truy vấn từng đoạn ngắn, rollup 1 giây
            lo, hi = ts[a], ts[min(a + 999, len(ts) - 1)]
            q = urllib.parse.urlencode({"from": lo, "to": hi + 1, "query": f"avg:dad.temp{{{cid_tag},source:dad_replay}}.rollup(avg,1)"})
            req = urllib.request.Request(f"https://api.{site}/api/v1/query?{q}", headers={"DD-API-KEY": api, "DD-APPLICATION-KEY": app})
            got = {}
            for s in json.load(urllib.request.urlopen(req, timeout=60)).get("series", []):
                got.update({int(t // 1000): v for t, v in s["pointlist"] if v is not None})
            for t in ts[a:a + 1000]:
                if t not in got:
                    missing += 1
                elif abs(got[t] - pts[t]) > 1e-9:
                    bad += 1
    check("F", "Datadog lưu đúng mọi điểm dad.temp", bad == 0 and missing == 0, f"thiếu {missing}, lệch {bad}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datadog", action="store_true", help="đọc lại dữ liệu từ Datadog (cần DD_API_KEY, DD_APP_KEY)")
    a = ap.parse_args()
    pubs, discs, counts = parse_raw()
    print(f"PCAP (bộ giải mã viết tay): {sum(counts.values())} gói, {len(pubs)} PUBLISH của cảm biến, {len(discs)} DISCONNECT")
    labels = check_csv(pubs, counts)
    db = MongoClient(URI, tz_aware=True)[os.environ.get("MONGODB_DB", "dad")]       # Date của MongoDB là UTC
    print(f"MongoDB: {URI} / database {db.name}")
    check_telemetry(db, pubs)
    check_latest(db, pubs)
    check_incidents(db, pubs, discs, labels)
    if os.path.exists(os.path.join(DD_OUT, "run.json")):               # nhóm E chỉ chạy khi đã chạy day_datadog.py
        journal, run = check_datadog_files(pubs)
        if a.datadog:
            check_datadog_live(journal, run)
    else:
        print("(bỏ qua nhóm E: chưa chạy day_datadog.py)")
    for g, w, ok in REPORT:
        print(f"[{'OK ' if ok else 'LỆCH'}] {g}  {w}")
    print(f"\n{sum(ok for *_, ok in REPORT)}/{len(REPORT)} kiểm tra đạt")
    with open(os.path.join(REPO, "monitoring", "data", "kiem_tra_ket_qua.json"), "w", encoding="utf-8") as f:
        json.dump([{"nhóm": g, "kiểm tra": w, "đạt": ok} for g, w, ok in REPORT], f, ensure_ascii=False, indent=2)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
