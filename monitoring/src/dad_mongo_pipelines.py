"""Bộ phát hiện D1/D2/D4, kiểm tra vật lý và điều tra, viết bằng MongoDB Aggregation Pipeline.

Cùng logic với dad_mining.py (pandas) và đã được đối chiếu kết quả trong notebook 04.
Tham số P = chu kỳ gửi (giây) sau khi tua: 300.1 khi chạy dữ liệu gốc, 5 khi tua ×60.
Cần MongoDB >= 7.0 (dùng $median trong $setWindowFields).
"""
from __future__ import annotations

from datetime import datetime

P_DEFAULT = 300.1


def _num(expr: str) -> dict:
    """Điều kiện 'là số'. Trong MQL, null < mọi số, nên $lt với null trả về true: luôn phải chặn trước."""
    return {"$isNumber": expr}


def gaps(P: float = P_DEFAULT, match: dict | None = None) -> list[dict]:
    """Khoảng cách tới bản tin trước của cùng cảm biến, tính theo chu kỳ (gapP); sameConn = cùng kết nối TCP."""
    return [
        {"$match": match or {}},
        {"$setWindowFields": {"partitionBy": "$meta.clientId", "sortBy": {"ts": 1}, "output": {
            "prevTs": {"$shift": {"output": "$ts", "by": -1}},
            "prevConn": {"$shift": {"output": "$conn", "by": -1}}}}},
        {"$match": {"prevTs": {"$ne": None}}},
        {"$set": {"gapP": {"$divide": [{"$dateDiff": {"startDate": "$prevTs", "endDate": "$ts", "unit": "millisecond"}}, P * 1000]},
                  "sameConn": {"$eq": ["$conn", "$prevConn"]}}},
    ]


def d1_silence(P: float = P_DEFAULT, factor: float = 1.5, match: dict | None = None) -> list[dict]:
    """D1 (khi bản tin kế tiếp tới): khoảng cách > factor × P. Bản live còn so now - last_seen trong worker."""
    return gaps(P, match) + [{"$match": {"gapP": {"$gt": factor}}},
                             {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "inrow": "$meta.inrow", "gapP": 1,
                                           "lost": {"$subtract": [{"$round": ["$gapP", 0]}, 1]}}}]


def d2_burst(P: float = P_DEFAULT, factor: float = 0.8, match: dict | None = None) -> list[dict]:
    """D2: bản tin đến sớm hơn factor × P trên CÙNG kết nối (bỏ bản tin đầu của kết nối mới)."""
    return gaps(P, match) + [{"$match": {"gapP": {"$lt": factor}, "sameConn": True}},
                             {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "inrow": "$meta.inrow", "gapP": 1}}]


def baseline_dev(window: int = 288, min_periods: int = 24, match: dict | None = None) -> list[dict]:
    """dev = value - trung vị `window` bản tin TRƯỚC của chính cảm biến (không nhìn tương lai)."""
    return [
        {"$match": match or {}},
        {"$setWindowFields": {"partitionBy": "$meta.clientId", "sortBy": {"ts": 1}, "output": {
            "base": {"$median": {"input": "$value", "method": "approximate"}, "window": {"documents": [-window, -1]}},
            "nBase": {"$count": {}, "window": {"documents": [-window, -1]}}}}},
        {"$set": {"dev": {"$cond": [{"$gte": ["$nBase", min_periods]}, {"$subtract": ["$value", "$base"]}, None]}}},
    ]


def d4_node(T: float = 0.8, K: int = 3, W: int = 6, slot_s: float = 300, match: dict | None = None) -> list[dict]:
    """D4 theo InRow: trung bình dev của 4 cảm biến trong mỗi slot; đếm slot có dev < -T trong W slot gần nhất.

    slot_s = độ dài slot (giây) = P sau khi tua: 300 với dữ liệu gốc, 5 khi tua ×60.
    """
    return baseline_dev(match=match) + [
        {"$group": {"_id": {"inrow": "$meta.inrow", "slot": {"$dateTrunc": {"date": "$ts", "unit": "millisecond", "binSize": int(slot_s * 1000)}}},
                    "dev": {"$avg": "$dev"}, "n": {"$sum": 1}}},
        {"$setWindowFields": {"partitionBy": "$_id.inrow", "sortBy": {"_id.slot": 1}, "output": {
            "negCount": {"$sum": {"$cond": [{"$and": [_num("$dev"), {"$lt": ["$dev", -T]}]}, 1, 0]},
                         "window": {"documents": [-(W - 1), 0]}},
            "nWin": {"$count": {}, "window": {"documents": [-(W - 1), 0]}}}}},
        {"$match": {"negCount": {"$gte": K}, "nWin": W}},
        {"$project": {"_id": 0, "inrow": "$_id.inrow", "slot": "$_id.slot", "dev": 1, "negCount": 1}},
        {"$sort": {"inrow": 1, "slot": 1}},
    ]


def d4_sensor(T: float = 0.8, K: int = 3, W: int = 6, match: dict | None = None) -> list[dict]:
    """D4 theo từng cảm biến (cảnh báo sớm): đếm bản tin có dev < -T trong W bản tin gần nhất."""
    return baseline_dev(match=match) + [
        {"$setWindowFields": {"partitionBy": "$meta.clientId", "sortBy": {"ts": 1}, "output": {
            "negCount": {"$sum": {"$cond": [{"$and": [_num("$dev"), {"$lt": ["$dev", -T]}]}, 1, 0]},
                         "window": {"documents": [-(W - 1), 0]}},
            "nWin": {"$count": {}, "window": {"documents": [-(W - 1), 0]}}}}},
        {"$match": {"negCount": {"$gte": K}, "nWin": W}},
        {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "inrow": "$meta.inrow", "dev": 1, "negCount": 1}},
    ]


def physics(slot_s: float = 300, match: dict | None = None) -> list[dict]:
    """Bất biến TFEU < TFSU < TAS < TAR trong cùng InRow, cùng slot. Trả về các slot vi phạm."""
    pick = lambda s: {"$avg": {"$cond": [{"$eq": ["$meta.sensor", s]}, "$value", None]}}
    return [
        {"$match": match or {}},
        {"$group": {"_id": {"inrow": "$meta.inrow", "slot": {"$dateTrunc": {"date": "$ts", "unit": "millisecond", "binSize": int(slot_s * 1000)}}},
                    "TFEU": pick("TFEU"), "TFSU": pick("TFSU"), "TAS": pick("TAS"), "TAR": pick("TAR")}},
        {"$match": {"TFEU": {"$ne": None}, "TFSU": {"$ne": None}, "TAS": {"$ne": None}, "TAR": {"$ne": None}}},
        {"$match": {"$expr": {"$not": {"$and": [{"$lt": ["$TFEU", "$TFSU"]}, {"$lt": ["$TFSU", "$TAS"]}, {"$lt": ["$TAS", "$TAR"]}]}}}},
    ]


def range_check(match: dict | None = None) -> list[dict]:
    """Giá trị ngoài dải hợp lệ của cảm biến (devices.valid_range_c)."""
    return [
        {"$match": match or {}},
        {"$lookup": {"from": "devices", "localField": "meta.clientId", "foreignField": "_id", "as": "dev"}},
        {"$set": {"lo": {"$arrayElemAt": [{"$arrayElemAt": ["$dev.valid_range_c", 0]}, 0]},
                  "hi": {"$arrayElemAt": [{"$arrayElemAt": ["$dev.valid_range_c", 0]}, 1]}}},
        {"$match": {"$expr": {"$or": [{"$lt": ["$value", "$lo"]}, {"$gt": ["$value", "$hi"]}]}}},
        {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "value": 1, "lo": 1, "hi": 1}},
    ]


def investigate(inrow: int, start: datetime, end: datetime, P: float = P_DEFAULT, T: float = 0.8, slot_min: int = 5) -> list[dict]:
    """Điều tra một cửa sổ sự cố: bản tin mất, bản tin thừa, số slot bị trừ, mức trừ hay gặp, số cảm biến.

    Chạy trên dữ liệu từ (start - 1 ngày) để có baseline, rồi chỉ giữ kết quả trong [start - 5', end + 5'].
    """
    from datetime import timedelta
    lo, hi = start - timedelta(minutes=5), end + timedelta(minutes=5)
    m = {"meta.inrow": inrow, "ts": {"$gte": start - timedelta(days=1, minutes=30), "$lte": hi}}
    msgs = gaps(P, m)[1:]                                   # bỏ $match đầu, dùng chung $match bên dưới
    return [
        {"$match": m},
        {"$facet": {
            "timing": msgs + [
                {"$match": {"ts": {"$gte": lo, "$lte": hi}}},
                {"$group": {"_id": None,
                            "lost": {"$sum": {"$cond": [{"$gt": ["$gapP", 1.5]}, {"$subtract": [{"$round": ["$gapP", 0]}, 1]}, 0]}},
                            "extra": {"$sum": {"$cond": [{"$and": [{"$lt": ["$gapP", 0.8]}, "$sameConn"]}, 1, 0]}},
                            "sensors": {"$addToSet": "$meta.clientId"}}}],
            "values": baseline_dev()[1:] + [
                {"$group": {"_id": {"$dateTrunc": {"date": "$ts", "unit": "minute", "binSize": slot_min}}, "dev": {"$avg": "$dev"}}},
                {"$match": {"_id": {"$gte": start.replace(second=0, microsecond=0, minute=start.minute - start.minute % slot_min), "$lte": end},
                            "dev": {"$lt": -T, "$ne": None}}},
                {"$group": {"_id": {"$round": [{"$multiply": ["$dev", -1]}, 0]}, "slots": {"$sum": 1}}},
                {"$sort": {"slots": -1}}]}},
        {"$project": {"lost": {"$ifNull": [{"$first": "$timing.lost"}, 0]}, "extra": {"$ifNull": [{"$first": "$timing.extra"}, 0]},
                      "sensors": {"$size": {"$ifNull": [{"$first": "$timing.sensors"}, []]}},
                      "dropped_slots": {"$sum": "$values.slots"}, "drop_c": {"$first": "$values._id"}}},
    ]


def silence_now(now: datetime, P: float = P_DEFAULT, factor: float = 1.5, lookback_periods: int = 50) -> list[dict]:
    """D1 live: với mỗi cảm biến, (now - lần nhận cuối) / P. Gộp theo InRow: số cảm biến đang im quá `factor` chu kỳ.

    Chạy mỗi chu kỳ trong detector worker; không chờ bản tin kế tiếp tới như d1_silence.
    """
    from datetime import timedelta
    return [
        {"$match": {"ts": {"$gte": now - timedelta(seconds=lookback_periods * P), "$lte": now}}},
        {"$group": {"_id": "$meta.clientId", "inrow": {"$first": "$meta.inrow"}, "lastTs": {"$max": "$ts"}}},
        {"$set": {"silenceP": {"$divide": [{"$dateDiff": {"startDate": "$lastTs", "endDate": now, "unit": "millisecond"}}, P * 1000]}}},
        {"$group": {"_id": "$inrow", "maxSilenceP": {"$max": "$silenceP"},
                    "silentSensors": {"$sum": {"$cond": [{"$gt": ["$silenceP", factor]}, 1, 0]}}}},
        {"$project": {"_id": 0, "inrow": "$_id", "maxSilenceP": {"$round": ["$maxSilenceP", 2]}, "silentSensors": 1}},
        {"$sort": {"inrow": 1}},
    ]


def cooling_kpis(slot_s: float = 300, ashrae=(18.0, 27.0), match: dict | None = None) -> list[dict]:
    """Chỉ số vận hành làm mát theo InRow và slot (dùng cho dashboard phòng máy).

    dT_air   = TAR - TAS   : nhiệt IT thải ra mà tủ phải lấy đi (≈ 6,3–7,3 °C trong DAD)
    dT_water = TFSU - TFEU : nhiệt nước nhận được qua dàn ống (≈ 3,7–4,1 °C)
    approach = TAS - TFEU  : khí cấp còn ấm hơn nước vào bao nhiêu (≈ 8,1–8,9 °C); tăng dần = dàn ống kém đi
    ratio    = dT_air / dT_water : cân bằng nhiệt khí–nước, rất ổn định (std ≈ 0,01–0,02) -> lệch = nghi 1 cảm biến hỏng
    ashrae_ok: TAS trong vùng khuyến nghị ASHRAE 18–27 °C
    """
    pick = lambda s: {"$avg": {"$cond": [{"$eq": ["$meta.sensor", s]}, "$value", None]}}
    return [
        {"$match": match or {}},
        {"$group": {"_id": {"inrow": "$meta.inrow", "slot": {"$dateTrunc": {"date": "$ts", "unit": "millisecond", "binSize": int(slot_s * 1000)}}},
                    "TFEU": pick("TFEU"), "TFSU": pick("TFSU"), "TAS": pick("TAS"), "TAR": pick("TAR")}},
        {"$match": {"TFEU": {"$ne": None}, "TFSU": {"$ne": None}, "TAS": {"$ne": None}, "TAR": {"$ne": None}}},
        {"$set": {"dT_air": {"$subtract": ["$TAR", "$TAS"]}, "dT_water": {"$subtract": ["$TFSU", "$TFEU"]},
                  "approach": {"$subtract": ["$TAS", "$TFEU"]}}},
        {"$set": {"ratio": {"$cond": [{"$gt": ["$dT_water", 0]}, {"$divide": ["$dT_air", "$dT_water"]}, None]},
                  "ashrae_ok": {"$and": [{"$gte": ["$TAS", ashrae[0]]}, {"$lte": ["$TAS", ashrae[1]]}]}}},
        {"$project": {"_id": 0, "inrow": "$_id.inrow", "slot": "$_id.slot", "TFEU": 1, "TFSU": 1, "TAS": 1, "TAR": 1,
                      "dT_air": 1, "dT_water": 1, "approach": 1, "ratio": 1, "ashrae_ok": 1}},
        {"$sort": {"inrow": 1, "slot": 1}},
    ]


def stuck_sensor(n: int = 12, match: dict | None = None) -> list[dict]:
    """Cảm biến 'đứng giá trị': n bản tin liên tiếp cùng một giá trị (DAD bình thường dài nhất 4; n = 12 là 1 giờ)."""
    return [
        {"$match": match or {}},
        {"$setWindowFields": {"partitionBy": "$meta.clientId", "sortBy": {"ts": 1}, "output": {
            "vmin": {"$min": "$value", "window": {"documents": [-(n - 1), 0]}},
            "vmax": {"$max": "$value", "window": {"documents": [-(n - 1), 0]}},
            "cnt": {"$count": {}, "window": {"documents": [-(n - 1), 0]}}}}},
        {"$match": {"$expr": {"$and": [{"$eq": ["$cnt", n]}, {"$eq": ["$vmin", "$vmax"]}]}}},
        {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "value": 1}},
    ]


def change_window(window_s: float = 900, limit_c: float = 5.0, sensor: str = "TAS", match: dict | None = None) -> list[dict]:
    """ASHRAE: (max - min) nhiệt độ khí đầu vào trong cửa sổ 15 phút không quá 5 °C (1 giờ: 20 °C)."""
    return [
        {"$match": {**(match or {}), "meta.sensor": sensor}},
        {"$setWindowFields": {"partitionBy": "$meta.clientId", "sortBy": {"ts": 1}, "output": {
            "vmin": {"$min": "$value", "window": {"range": [-window_s, 0], "unit": "second"}},
            "vmax": {"$max": "$value", "window": {"range": [-window_s, 0], "unit": "second"}}}}},
        {"$set": {"swing": {"$subtract": ["$vmax", "$vmin"]}}},
        {"$match": {"swing": {"$gt": limit_c}}},
        {"$project": {"_id": 0, "ts": 1, "clientId": "$meta.clientId", "swing": 1}},
    ]


def rci(rec=(18.0, 27.0), allow=(15.0, 32.0), sensor: str = "TAS", group_unit: str = "day", match: dict | None = None) -> list[dict]:
    """Rack Cooling Index (Herrlin 2005) trên nhiệt độ khí cấp, theo InRow và theo ngày (UTC).

    RCI_HI = 100 * (1 - Σ(T - max_rec | T > max_rec) / ((max_all - max_rec) * n));  RCI_LO tương tự ở biên dưới.
    100% = lý tưởng, ≥ 95% tốt, < 90% kém. DAD không có cảm biến đầu vào rack, nên dùng TAS làm đại diện.
    """
    lo_r, hi_r = rec
    lo_a, hi_a = allow
    return [
        {"$match": {**(match or {}), "meta.sensor": sensor}},
        {"$group": {"_id": {"inrow": "$meta.inrow", "period": {"$dateTrunc": {"date": "$ts", "unit": group_unit}}},
                    "n": {"$sum": 1},
                    "over": {"$sum": {"$cond": [{"$gt": ["$value", hi_r]}, {"$subtract": ["$value", hi_r]}, 0]}},
                    "under": {"$sum": {"$cond": [{"$lt": ["$value", lo_r]}, {"$subtract": [lo_r, "$value"]}, 0]}},
                    "outside_allowable": {"$sum": {"$cond": [{"$or": [{"$lt": ["$value", lo_a]}, {"$gt": ["$value", hi_a]}]}, 1, 0]}}}},
        {"$project": {"_id": 0, "inrow": "$_id.inrow", "period": "$_id.period", "n": 1, "outside_allowable": 1,
                      "RCI_HI": {"$round": [{"$multiply": [100, {"$subtract": [1, {"$divide": ["$over", {"$multiply": [hi_a - hi_r, "$n"]}]}]}]}, 2]},
                      "RCI_LO": {"$round": [{"$multiply": [100, {"$subtract": [1, {"$divide": ["$under", {"$multiply": [lo_r - lo_a, "$n"]}]}]}]}, 2]}}},
        {"$sort": {"inrow": 1, "period": 1}},
    ]


def completeness(slot_s: float = 300, expected_per_day: int = 288, match: dict | None = None) -> list[dict]:
    """Độ đầy đủ theo SỐ Ô THỜI GIAN có dữ liệu (không đếm bản tin): bản tin chèn thêm không bù được ô bị mất.

    DAD InRow 13 thứ Sáu: đếm bản tin cho 100%, đếm ô 5 phút cho 94,8%.
    """
    return [
        {"$match": match or {}},
        {"$group": {"_id": {"clientId": "$meta.clientId", "inrow": "$meta.inrow",
                            "day": {"$dateTrunc": {"date": "$ts", "unit": "day"}},
                            "slot": {"$dateTrunc": {"date": "$ts", "unit": "millisecond", "binSize": int(slot_s * 1000)}}},
                    "msgs": {"$sum": 1}}},
        {"$group": {"_id": {"clientId": "$_id.clientId", "inrow": "$_id.inrow", "day": "$_id.day"},
                    "slots": {"$sum": 1}, "msgs": {"$sum": "$msgs"}}},
        {"$project": {"_id": 0, "clientId": "$_id.clientId", "inrow": "$_id.inrow", "day": "$_id.day", "msgs": 1, "slots": 1,
                      "completeness_pct": {"$round": [{"$multiply": [100, {"$divide": [{"$min": ["$slots", expected_per_day]}, expected_per_day]}]}, 1]}}},
        {"$sort": {"clientId": 1, "day": 1}},
    ]
