# -*- coding: utf-8 -*-
"""run.py —— AuToRun 统一启动器（原创）。

  python run.py            # 默认起网页工作台
  python run.py web        # 起网页工作台（地图画线 + 全流程，内置本地 mock）
  python run.py cli        # 命令行菜单：授权 / 跑步 / 爬路径 / 统计
  python run.py self-test  # 自起本地 mock 跑一遍全流程（自测）

CLI 与网页共用同一套引擎：trackgen（轨迹） + pipeline（流程） + client（协议） + mock_srv（模拟）。
"""
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(HERE, "autorun_session.json")

# 把 mock / 日志目录固定到仓库内（避免落到 D:\30-logs）
_LOGDIR = os.path.join(HERE, "30-logs")
os.makedirs(_LOGDIR, exist_ok=True)
os.environ.setdefault("MOCK_LOGDIR", _LOGDIR)


def cmd_web():
    sys.path.insert(0, HERE)
    import webapp
    webapp.start()
    return 0


def cmd_self_test():
    sys.path.insert(0, HERE)
    import pipeline
    old_argv = sys.argv
    sys.argv = [old_argv[0]]  # 清掉 "self-test"，避免透传给 pipeline 的 argparse
    try:
        return pipeline.main()
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------- CLI
def _load_session():
    if os.path.exists(SESSION_FILE):
        try:
            return __import__("json").load(open(SESSION_FILE, encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_session(sess):
    try:
        __import__("json").dump(sess, open(SESSION_FILE, "w", encoding="utf-8"),
                                ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _oval_track(lat=23.0500, lng=113.4200, radius_m=140.0, n=60):
    rlat = radius_m / 111320.0
    rlng = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return [[lng + rlng * math.cos(2 * math.pi * i / n),
             lat + rlat * math.sin(2 * math.pi * i / n)] for i in range(n + 1)]


def cmd_cli():
    sys.path.insert(0, HERE)
    import pipeline as P
    import client as C

    session = _load_session()
    while True:
        print("\n==== AuToRun 命令行 ====")
        print("1  启动网页工作台")
        print("2  授权账号（登录 + 拉配置，保存会话）")
        print("3  开始跑步（用保存的会话）")
        print("4  爬取历史路径（抽 GPS 轨迹，存 routes_*.json）")
        print("5  查询有效次数 / 累计里程")
        print("0  退出")
        try:
            c = input("请选择 (0-5): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if c == "0":
            break

        if c == "1":
            cmd_web()
            continue

        if c == "2":
            try:
                base = input("API base（留空=本地 mock）[mock]: ").strip() or "http://127.0.0.1:18080"
                school = input("学校代码 [autorun]: ").strip() or "autorun"
                user = input("账号 [student]: ").strip() or "student"
                pwd = input("密码 [pass]: ").strip() or "pass"
                run_type = int(input("跑步类型 1晨跑/2阳光跑/3自由跑 [2]: ").strip() or 2)
            except (EOFError, KeyboardInterrupt, ValueError):
                continue
            try:
                out = P.stage_login(base=base, school_code=school, username=user,
                                   password=pwd, run_type=run_type)
            except Exception as e:  # noqa: BLE001
                print("登录异常:", repr(e))
                continue
            print("登录:", "OK" if out.get("ok") else "FAIL")
            for s in out.get("steps", []):
                print("  [%s] %s — %s" % ("OK" if s["ok"] else "FAIL", s["name"], s.get("detail", "")))
            sess = out.get("session")
            if out.get("ok") and sess:
                if _save_session(sess):
                    print("会话已保存")
                    session = sess
            continue

        if c == "3":
            if not session:
                print("请先选 2 授权账号")
                continue
            try:
                km = float(input("目标公里 [2.0]: ").strip() or 2.0)
                pace = int(input("配速 秒/公里 [330]: ").strip() or 330)
                faces = (input("开人脸 1/0 [1]: ").strip() or "1") == "1"
            except (EOFError, KeyboardInterrupt, ValueError):
                continue
            params = {
                "points": _oval_track(),
                "target_km": km, "pace_s_per_km": pace, "sample_interval_s": 1.0,
                "speed_jitter": 0.08, "loop_mode": "repeat",
                "run_type": int(session.get("run_type", 2)),
                "crs": "gcj02", "start_face": faces, "end_face": faces,
                "middle_faces": [0.3, 0.7] if faces else [], "sex": "male", "pause_count": 0,
            }
            try:
                out = P.stage_run(base=session.get("base", "http://127.0.0.1:18080"),
                                  session=session, params=params, faces=faces)
            except Exception as e:  # noqa: BLE001
                print("跑步异常:", repr(e))
                continue
            print("跑步:", "OK" if out.get("ok") else "FAIL")
            for s in out.get("steps", []):
                print("  [%s] %s — %s" % ("OK" if s["ok"] else "FAIL", s["name"], s.get("detail", "")))
            continue

        if c == "4":
            if not session:
                print("请先选 2 授权账号")
                continue
            try:
                client = C.Client(session.get("base", "http://127.0.0.1:18080"),
                                  school_code=session.get("school_code") or "autorun")
                client.token = session.get("token")
                lst = client.list_records() or {}
                recs = lst.get("records") or []
                print("读到 %d 条历史记录，开始抽轨迹……" % len(recs))
                routes = []
                for r0 in recs:
                    rid = (r0 or {}).get("id")
                    if not rid:
                        continue
                    dd = client.get_record(rid) or {}
                    pts = dd.get("gitudeLatitude") or []
                    track = [[p.get("o"), p.get("a")] for p in pts if "o" in p and "a" in p]
                    if track:
                        routes.append({"record_id": rid, "track": track})
                out_p = os.path.join(HERE, "routes_%s.json" % (session.get("school_code") or "school"))
                __import__("json").dump(routes, open(out_p, "w", encoding="utf-8"),
                                        ensure_ascii=False, indent=2)
                print("已存 %d 条可复用路径 -> %s" % (len(routes), out_p))
            except Exception as e:  # noqa: BLE001
                print("爬取异常:", repr(e))
            continue

        if c == "5":
            if not session:
                print("请先选 2 授权账号")
                continue
            try:
                client = C.Client(session.get("base", "http://127.0.0.1:18080"),
                                  school_code=session.get("school_code") or "autorun")
                client.token = session.get("token")
                s = client.sum() or {}
                print("有效次数 / 累计里程:")
                for k in ("sumCount", "sumDistance", "sumMetre", "validCount"):
                    if k in s:
                        print("  %s = %s" % (k, s[k]))
                if not s:
                    print("  （空）")
            except Exception as e:  # noqa: BLE001
                print("统计异常:", repr(e))
            continue

        print("无效选择")
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "cli":
        return cmd_cli()
    if argv and argv[0] == "self-test":
        return cmd_self_test()
    return cmd_web()


if __name__ == "__main__":
    sys.exit(main())
