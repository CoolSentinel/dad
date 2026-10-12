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
