# -*- coding: utf-8 -*-
"""trackgen.py —— 轨迹生成（原创）。

把一条「地图折线 / 跑道」变成一条看起来合理的跑步记录：
  - 沿折线按目标距离重采样，配速 + 抖动得到每帧速度；
  - 叠加 GPS 噪声（漂移 / 野值），模拟真机定位；
  - 输出点串、60 秒步数桶、人脸打卡点、提交表单、合格性判定。

口径：内部坐标一律 WGS-84；导出坐标按 params["crs"] 转 GCJ-02（默认 gcj02）。
"""
import math
import random
import time

import geo


def _build_path(points, loop_mode, target_m):
    """把折线展开成足够长的顶点序列（loop_mode=repeat 时循环拼接）。"""
    if not points or len(points) < 2:
        raise ValueError("points 至少需要 2 个点")
    verts = [[float(p[0]), float(p[1])] for p in points]
    if loop_mode == "repeat":
        # 先算一圈长度，循环拼接直到够目标距离 + 缓冲
        seg = []
        total = 0.0
        for i in range(len(verts) - 1):
            d = geo.haversine_m(verts[i][0], verts[i][1], verts[i + 1][0], verts[i + 1][1])
            seg.append(d)
            total += d
        if total <= 0:
            raise ValueError("折线总长度为 0")
        need = int(target_m / total) + 2
        out = list(verts)
        for _ in range(need):
            out.extend(verts[1:])  # 不重复首点
        return out
    return verts


def _cum_dist(verts):
    cum = [0.0]
    for i in range(len(verts) - 1):
        cum.append(cum[-1] + geo.haversine_m(verts[i][0], verts[i][1],
                                              verts[i + 1][0], verts[i + 1][1]))
    return cum


def _pos_at(verts, cum, d):
    """弧长 d 处插值坐标（WGS-84）。"""
    if d <= 0:
        return verts[0][0], verts[0][1]
    if d >= cum[-1]:
        return verts[-1][0], verts[-1][1]
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < d:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    seg = cum[i] - cum[i - 1] or 1e-9
    t = (d - cum[i - 1]) / seg
    lng = verts[i - 1][0] + (verts[i][0] - verts[i - 1][0]) * t
    lat = verts[i - 1][1] + (verts[i][1] - verts[i - 1][1]) * t
    return lng, lat


def _stride(sex):
    # 步幅（米）：男约 0.78，女约 0.68，带 ±5% 抖动
    base = 0.78 if (sex or "male") == "male" else 0.68
    return base * (1.0 + random.uniform(-0.05, 0.05))


def generate(params, start_ms=None, run_type=1, seed=None):
    if seed is not None:
        random.seed(seed)
    points = params.get("points") or []
    target_km = float(params.get("target_km") or 2.0)
    pace = float(params.get("pace_s_per_km") or 330.0)
    interval = float(params.get("sample_interval_s") or 1.0)
    jitter = float(params.get("speed_jitter") or 0.08)
    loop_mode = params.get("loop_mode") or "repeat"
    crs = (params.get("crs") or "gcj02").lower()
    sex = params.get("sex") or "male"
    pause_count = int(params.get("pause_count") or 0)
    target_m = target_km * 1000.0

    verts = _build_path(points, loop_mode, target_m)
    cum = _cum_dist(verts)
    speed_base = 1000.0 / max(1.0, pace)  # m/s

    # 每帧原始速度（配速 + 高斯抖动）
    n = max(2, int(target_m / speed_base / interval))
    raw_speed = [max(0.5, speed_base * (1.0 + jitter * random.gauss(0, 1))) for _ in range(n + 1)]
    # 暂停：随机若干段速度置近 0
    for _ in range(pause_count):
        k = random.randint(1, max(1, n - 1))
        raw_speed[k] = speed_base * random.uniform(0.0, 0.1)
    # 累计原始距离并线性拉伸到目标
    raw_cum = [0.0]
    for s in raw_speed[:-1]:
        raw_cum.append(raw_cum[-1] + s * interval)
    raw_total = raw_cum[-1] or 1.0

    start_ms = int(start_ms or time.time() * 1000)
    samples = []
    pointdata = []
    for i in range(n + 1):
        d = target_m * raw_cum[i] / raw_total
        lng, lat = _pos_at(verts, cum, d)
        # GPS 噪声：3~7 米随机漂移
        nm = random.uniform(3.0, 7.0)
        lat += geo.m_to_deg_lat(nm * random.uniform(-1, 1))
        lng += geo.m_to_deg_lng(nm * random.uniform(-1, 1), lat)
        t_ms = start_ms + int(i * interval * 1000)
        spd = raw_speed[i]
        cum_m = d
        samples.append({"t_ms": t_ms, "lat": lat, "lng": lng,
                        "cumulative_m": cum_m, "speed_mps": spd, "paused": spd < speed_base * 0.2})
        # 导出坐标
        elng, elat = geo.wgs84_to_gcj02(lng, lat) if crs == "gcj02" else (lng, lat)
        pointdata.append({"o": round(elng, 7), "a": round(elat, 7),
                          "t": t_ms, "s": round(spd, 3), "d": round(cum_m, 1)})

    distance_m = samples[-1]["cumulative_m"]
    elapsed_s = n * interval
    wall_s = elapsed_s + pause_count * 20.0

    # 60 秒步数桶
    stride = _stride(sex)
    buckets = []
    i0 = 0
    t0 = start_ms
    while i0 <= n:
        i1 = i0
        while i1 <= n and samples[i1]["t_ms"] - start_ms < (len(buckets) + 1) * 60000:
            i1 += 1
        seg_d = (samples[min(i1, n)]["cumulative_m"] - samples[i0]["cumulative_m"])
        buckets.append({"start": t0 + len(buckets) * 60000,
                        "end": t0 + (len(buckets) + 1) * 60000,
                        "steps": max(0, int(seg_d / stride)),
                        "distance_m": round(seg_d, 1)})
        i0 = i1
        if i1 > n:
            break

    # 人脸打卡点
    faces = []
    def _coord_at(frac):
        idx = min(n, max(0, int(frac * n)))
        p = pointdata[idx]
        return "%.7f,%.7f" % (p["o"], p["a"])

    if params.get("start_face"):
        faces.append({"type": 1, "timestamp": start_ms + 2000, "coordinates": _coord_at(0.0)})
    for f in (params.get("middle_faces") or []):
        frac = float(f)
        if 0.0 < frac < 1.0:
            faces.append({"type": 2, "timestamp": start_ms + int(frac * elapsed_s * 1000),
                          "coordinates": _coord_at(frac)})
    if params.get("end_face"):
        faces.append({"type": 3, "timestamp": start_ms + int(elapsed_s * 1000),
                      "coordinates": _coord_at(1.0)})

    end_ms = start_ms + int(elapsed_s * 1000)
    submit = {
        "userId": "AUTORUN-USER",
        "runType": int(run_type),
        "formatSportRange": "%.2f" % target_km,
        "sportRange": round(distance_m, 1),
        "startTime": start_ms,
        "endTime": end_ms,
        "addTime": end_ms + int(wall_s * 1000),
        "gitudeLatitude": pointdata,
        "stepFrequency": round(1000.0 / stride / max(1.0, pace) * 60.0, 1),
        "stride": round(stride, 3),
        "avgSpeed": round(distance_m / max(1.0, elapsed_s), 3),
        "limitSpeed": 3.0,
        "deviceModel": "AutorunDevice",
        "appVersion": "1.0.0",
        "steps": sum(b["steps"] for b in buckets),
    }

    validity = {
        "qualified": distance_m >= target_m * 0.95,
        "distance_m": round(distance_m, 1),
        "target_m": round(target_m, 1),
        "point_count": len(samples),
        "elapsed_s": int(elapsed_s),
    }

    return {
        "samples": samples,
        "pointdata": pointdata,
        "metrics": {
            "distance_m": round(distance_m, 1),
            "point_count": len(samples),
            "elapsed_s": int(elapsed_s),
            "wall_s": int(wall_s),
            "start_lng": samples[0]["lng"],
            "start_lat": samples[0]["lat"],
            "pace_s_per_km": pace,
        },
        "buckets": buckets,
        "faces": faces,
        "submit": submit,
        "validity": validity,
        "loop_mode": loop_mode,
    }


def truncate(gen, cut_ms):
    """中途停止：把轨迹截到 cut_ms（轨迹时间轴绝对毫秒）之前，重算。"""
    samples = [s for s in gen["samples"] if s["t_ms"] <= cut_ms]
    if len(samples) < 2:
        return None
    # 重新截断 pointdata / faces / submit
    pointdata = [p for p in gen["pointdata"] if p["t"] <= cut_ms]
    faces = [f for f in gen["faces"] if f["timestamp"] <= cut_ms]
    distance_m = samples[-1]["cumulative_m"]
    start_ms = samples[0]["t_ms"]
    end_ms = samples[-1]["t_ms"]
    submit = dict(gen["submit"])
    submit["gitudeLatitude"] = pointdata
    submit["sportRange"] = round(distance_m, 1)
    submit["startTime"] = start_ms
    submit["endTime"] = end_ms
    submit["addTime"] = end_ms
    submit["formatSportRange"] = "%.2f" % (distance_m / 1000.0)
    metrics = dict(gen["metrics"])
    metrics["distance_m"] = round(distance_m, 1)
    metrics["point_count"] = len(samples)
    metrics["elapsed_s"] = int((end_ms - start_ms) / 1000)
    return {
        "samples": samples,
        "pointdata": pointdata,
        "metrics": metrics,
        "buckets": gen.get("buckets", []),
        "faces": faces,
        "submit": submit,
        "validity": {"qualified": True, "distance_m": round(distance_m, 1),
                     "target_m": gen["validity"].get("target_m"),
                     "point_count": len(samples), "elapsed_s": metrics["elapsed_s"]},
        "loop_mode": gen.get("loop_mode"),
    }
