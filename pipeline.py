# -*- coding: utf-8 -*-
"""pipeline.py —— 全流程编排（原创）。

把一条轨迹走完客户端全部步骤：登录 → 配置 → 开跑时刻 → 人脸 → 上传 → 读回 → 汇总。
每步回执收集进 Steps，便于 CLI / 网页逐条展示。realtime=True 时按真实用时跑（人脸到点发、
跑到点才上传）；stop() 返回真则按已跑段截断上传。
"""
import argparse
import base64
import json
import math
import os
import threading
import time

import client as C
import trackgen as T

DEFAULT_BASE = "http://127.0.0.1:18080"
DEFAULT_SCHOOL = "autorun"
DEFAULT_USER = "student"
DEFAULT_PASS = "pass"
DEFAULT_DEVICE_ID = "autorun-device"

FAKE_FACE_JPEG = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    b"HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    b"AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Steps:
    def __init__(self, on_add=None):
        self.items = []
        self.on_add = on_add

    def add(self, name, ok, detail="", **extra):
        it = {"name": name, "ok": bool(ok), "detail": detail,
              "ms": int(time.time() * 1000)}
        it.update(extra)
        self.items.append(it)
        if self.on_add:
            try:
                self.on_add(dict(it))
            except Exception:  # noqa: BLE001
                pass
        return it

    def names(self):
        return [s["name"] for s in self.items]


def _fail(out, st, name, e, kind="login"):
    st.add(name, False, str(e))
    out["ok"] = False
    out["error"] = str(e)
    out["steps"] = [dict(s) for s in st.items]
    return out


class Cancelled(Exception):
    pass


class Pacer:
    """实时上传节奏器：把轨迹时间轴映射到墙钟，按时报进度。"""
    TICK_S = 0.2

    def __init__(self, *, start_ms=0, speed=1.0, progress=None, cancel=None, stop=None,
                 samples=None, total_m=0.0):
        self.start_ms = int(start_ms or 0)
        self.speed = max(1e-3, float(speed or 1.0))
        self.progress = progress
        self.cancel = cancel or (lambda: False)
        self.stop = stop or (lambda: False)
        self.stopped = False
        self.cut_ms = None
        self.total_m = float(total_m or 0.0)
        self.t0 = int(time.time() * 1000)
        self.total_ms = 0
        self.track = [(int(s.get("t_ms") or 0), float(s["lat"]), float(s["lng"]),
                       float(s.get("cumulative_m") or 0.0), float(s.get("speed_mps") or 0.0))
                      for s in (samples or [])]

    def begin(self, total_ms):
        self.total_ms = max(0, int(total_ms or 0))
        self.t0 = int(time.time() * 1000)
        self._emit("")

    def done_ms(self):
        d = int((int(time.time() * 1000) - self.t0) * self.speed)
        return min(d, int(self.cut_ms) - int(self.start_ms)) if self.cut_ms else d

    def _freeze(self):
        if self.stopped:
            return True
        if self.stop():
            self.stopped = True
            self.cut_ms = int(self.start_ms) + int((int(time.time() * 1000) - self.t0) * self.speed)
            return True
        return False

    def wait_until(self, offset_ms, label=""):
        target = self.t0 + int(max(0, int(offset_ms or 0)) / self.speed)
        while True:
            if self.cancel():
                raise Cancelled()
            if self._freeze():
                return
            remain = target - int(time.time() * 1000)
            if remain <= 0:
                break
            time.sleep(min(self.TICK_S, remain / 1000.0))
            self._emit(label)
        self._emit(label)

    def pos_at(self, done_ms):
        if not self.track:
            return None
        t = self.start_ms + int(done_ms or 0)
        lo, hi = 0, len(self.track) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.track[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        _, lat, lng, cum, spd = self.track[lo]
        return {"lat": lat, "lng": lng, "cum_m": cum, "total_m": self.total_m, "speed_mps": spd}

    def snap(self, label=""):
        d = self.done_ms()
        return {"done_ms": d, "total_ms": self.total_ms, "phase": label,
                "speed": self.speed, "stopped": self.stopped, "pos": self.pos_at(d)}

    def _emit(self, label):
        if self.progress:
            try:
                self.progress(self.snap(label))
            except Exception:  # noqa: BLE001
                pass


def _face_image_for(c, face_image=None, face_image_b64=None, bas_user_id=None):
    if face_image or face_image_b64:
        return (face_image or base64.b64decode(face_image_b64)), "你提供的人脸照"
    if bas_user_id:
        try:
            got = c.fetch_face_image(bas_user_id)
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return c.add_pixel_noise(got), "服务器已注册底片（加噪）"
    return FAKE_FACE_JPEG, "占位图（未提供人脸照）"


def run_pipeline(*, base=DEFAULT_BASE, school_code=DEFAULT_SCHOOL, username=DEFAULT_USER,
                 password=DEFAULT_PASS, params=None, gen=None, faces=True, run_type=1,
                 face_image=None, face_image_b64=None, device_id=DEFAULT_DEVICE_ID,
                 steps=None, session=None, realtime=False, speed=1.0, progress=None,
                 cancel=None, stop=None, timeout=20.0):
    st = steps or Steps()
    c = C.Client(base, school_code=school_code, timeout=timeout, device={"model": "AutorunDevice"},
                 app_version="1.0.0")
    out = {"chain": "autorun", "base": base, "steps": st, "school_code": school_code,
           "realtime": bool(realtime)}

    sess = session or {}
    if sess.get("token") and sess.get("identify"):
        c.token = sess["token"]
        identify = sess.get("identify")
        bean = sess.get("setting") or {}
        st.add("登录（复用 token）", True, "token=%s…" % (c.token or "")[:12])
        st.add("配置（复用 setting）", True, "identify=%s" % identify)
    else:
        try:
            c.login(username or DEFAULT_USER, password if password is not None else DEFAULT_PASS)
            st.add("登录 /api/auth/token", True, "拿到 Bearer token")
        except Exception as e:  # noqa: BLE001
            return _fail(out, st, "登录 /api/auth/token", e)
        try:
            bean = c.setting(run_type)
            identify = bean.get("identify")
            st.add("配置 /api/exercise/setting", bool(identify),
                   "identify=%s；目标 %.2f km / 限速 %s" % (
                       identify, float(bean.get("totalRange") or 0) / 1000.0, bean.get("limitSpeed")))
        except Exception as e:  # noqa: BLE001
            return _fail(out, st, "配置 /api/exercise/setting", e)

    try:
        start_ms = c.start_time(identify) or int(time.time() * 1000)
        st.add("开跑时刻 /api/exercise/startTime", start_ms > 0, "startTime=%d" % start_ms)
    except Exception as e:  # noqa: BLE001
        st.add("开跑时刻 /api/exercise/startTime", False, str(e))
        start_ms = int(time.time() * 1000)

    if gen is None:
        try:
            gen = T.generate(params or {}, start_ms=start_ms, run_type=run_type)
            m = gen["metrics"]
            st.add("生成轨迹", True, "%.1f m / %d 点 / 用时 %d s" % (
                m["distance_m"], m["point_count"], m["elapsed_s"]))
        except Exception as e:  # noqa: BLE001
            st.add("生成轨迹", False, str(e))
            out["ok"] = False
            out["steps"] = [dict(s) for s in st.items]
            return out
    out["gen"] = {k: gen.get(k) for k in ("metrics", "validity", "loop_mode")}

    _m = gen.get("metrics") or {}
    plan_ms = int(round(float(_m.get("elapsed_s") or 0) * 1000.0))
    pacer = None
    if realtime:
        pacer = Pacer(start_ms=start_ms, speed=speed, progress=progress, cancel=cancel, stop=stop,
                      samples=gen.get("samples"), total_m=float(_m.get("distance_m") or 0.0))
        pacer.begin(plan_ms)
        st.add("实时上传（按真实用时）", True, "×%.2f：计划 %d s" % (pacer.speed, plan_ms // 1000))

    img, _src = _face_image_for(c, face_image=face_image, face_image_b64=face_image_b64,
                               bas_user_id=sess.get("bas_user_id"))
    face_ok = 0
    if faces:
        for f in gen.get("faces") or []:
            if pacer:
                pacer.wait_until(int(f.get("timestamp") or 0) - int(start_ms or 0),
                                 "人脸 faceType=%s" % f.get("type"))
                if pacer.cut_ms is not None and int(f.get("timestamp") or 0) > int(pacer.cut_ms):
                    continue
            try:
                j = c.face(img, f.get("coordinates") or "", identify, run_type=run_type,
                           face_type=int(f.get("type") or 1))
                if j.get("code") == 0:
                    face_ok += 1
                st.add("人脸打卡 faceType=%s" % f.get("type"), j.get("code") == 0,
                       "坐标 %s（%s）" % (f.get("coordinates"), _src))
            except Exception as e:  # noqa: BLE001
                st.add("人脸打卡 faceType=%s" % f.get("type"), False, str(e))
    else:
        st.add("人脸打卡", True, "已关闭（faces=False）")

    if pacer:
        pacer.wait_until(max(plan_ms, int(round(float(_m.get("wall_s") or 0) * 1000.0))), "上传")

    cut_gen = None
    if pacer and pacer.stopped:
        cut_gen = T.truncate(gen, pacer.cut_ms)
        if cut_gen is None:
            out["stopped"] = True
            out["ok"] = False
            out["steps"] = [dict(s) for s in st.items]
            return out
        gen = cut_gen

    try:
        data, rid = c.add_record(gen, setting=bean, run_type=run_type)
        st.add("上传 /api/exercise/record", rid is not None, "recordId=%s" % rid)
        out["recordId"] = rid
    except Exception as e:  # noqa: BLE001
        st.add("上传 /api/exercise/record", False, str(e))
        out["ok"] = False
        out["steps"] = [dict(s) for s in st.items]
        return out

    try:
        rows = c.list_records() or {}
        n = len(rows.get("records") or [])
        st.add("读回 /api/exercise/records", n >= 1, "读到 %d 条（闭环）" % n)
        out["readback"] = {"count": n}
    except Exception as e:  # noqa: BLE001
        st.add("读回 /api/exercise/records", False, str(e))
    try:
        s = c.sum()
        st.add("汇总 /api/exercise/summary", True, json.dumps(s, ensure_ascii=False)[:120])
        out["sum"] = s
    except Exception as e:  # noqa: BLE001
        st.add("汇总 /api/exercise/summary", False, str(e))

    out["ok"] = all(x["ok"] for x in st.items)
    out["faces_ok"] = face_ok
    out["steps"] = [dict(s) for s in st.items]
    return out


# ---------------------------------------------------------------- 分步（向导）
def stage_login(*, base=DEFAULT_BASE, school_code=DEFAULT_SCHOOL, username=DEFAULT_USER,
                password=DEFAULT_PASS, run_type=1, device_id=DEFAULT_DEVICE_ID, timeout=20.0):
    c = C.Client(base, school_code=school_code, timeout=timeout, device={"model": "AutorunDevice"})
    st = Steps()
    out = {"chain": "autorun", "base": base, "steps": st, "session": {}, "info": {}, "run_type": run_type}
    try:
        c.login(username or DEFAULT_USER, password if password is not None else DEFAULT_PASS)
        st.add("登录 /api/auth/token", True, "拿到 Bearer token")
    except Exception as e:  # noqa: BLE001
        return _fail(out, st, "登录 /api/auth/token", e)
    try:
        bean = c.setting(run_type)
        st.add("配置 /api/exercise/setting", bool(bean.get("identify")),
               "identify=%s；目标 %.2f km" % (bean.get("identify"),
                                             float(bean.get("totalRange") or 0) / 1000.0))
    except Exception as e:  # noqa: BLE001
        st.add("配置 /api/exercise/setting", False, str(e))
        bean = {}
    try:
        uid = (c.user_info() or {}).get("basUserId")
    except Exception:  # noqa: BLE001
        uid = None
    out["session"] = {"chain": "autorun", "base": base, "token": c.token,
                      "identify": bean.get("identify"), "setting": bean, "bas_user_id": uid,
                      "school_code": school_code, "run_type": run_type}
    out["info"] = {"school_code": school_code, "username": username,
                   "identify": bean.get("identify"),
                   "total_km": float(bean.get("totalRange") or 0) / 1000.0,
                   "is_start_face": bean.get("isStartFace"),
                   "is_end_face": bean.get("isEndFace"),
                   "middle_faces": bean.get("middleFaces"),
                   "bas_user_id": uid}
    out["ok"] = all(x["ok"] for x in st.items)
    out["steps"] = [dict(s) for s in st.items]
    return out


def stage_run(*, base=DEFAULT_BASE, session=None, params=None, gen=None, faces=True, run_type=1,
              school_code=DEFAULT_SCHOOL, username=DEFAULT_USER, password=DEFAULT_PASS,
              device_id=DEFAULT_DEVICE_ID, timeout=20.0, realtime=False, speed=1.0,
              progress=None, cancel=None, stop=None):
    st = Steps(on_add=progress)
    r = run_pipeline(base=base, school_code=school_code, username=username, password=password,
                     params=params, gen=gen, faces=faces, run_type=run_type, session=session,
                     steps=st, timeout=timeout, realtime=realtime, speed=speed,
                     progress=progress, cancel=cancel, stop=stop)
    r["steps"] = [dict(s) for s in st.items]
    r["session_reused"] = bool(session)
    return r


# ---------------------------------------------------------------- 自测
def _oval(lat=23.0500, lng=113.4200, radius_m=140.0, n=60):
    rlat = radius_m / 111320.0
    rlng = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return [[lng + rlng * math.cos(2 * math.pi * i / n),
             lat + rlat * math.sin(2 * math.pi * i / n)] for i in range(n + 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    ap.add_argument("--km", type=float, default=2.0)
    a = ap.parse_args()

    srv = None
    base = a.base
    if not base:
        import mock_srv as M
        srv = M.make_server("127.0.0.1", 0)
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("[mock] 自起于 %s" % base)

    params = {"points": _oval(), "target_km": a.km, "pace_s_per_km": 330,
              "sample_interval_s": 1.0, "speed_jitter": 0.08, "loop_mode": "repeat",
              "run_type": 1, "crs": "gcj02", "start_face": True, "end_face": True,
              "middle_faces": [0.3, 0.7], "sex": "male", "pause_count": 0}
    try:
        r = run_pipeline(base=base, params=params, faces=True)
        for s in r["steps"]:
            print("  [%s] %s  — %s" % ("OK  " if s["ok"] else "FAIL", s["name"], s["detail"]))
        print("\n==== 全流程：%d 步 / %d FAIL ====" % (
            len(r["steps"]), sum(1 for s in r["steps"] if not s["ok"])))
    finally:
        if srv:
            srv.shutdown()
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
