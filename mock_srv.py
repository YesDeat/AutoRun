# -*- coding: utf-8 -*-
"""mock_srv.py —— 本地模拟服务（原创）。

与本仓库 client.py 共用一套 JSON 信封（{"code","data","msg"}）。
默认只监听 127.0.0.1，用于离线自测 / 学习「提交 → 读回」闭环。
运行：python -m mock_srv  （或 run.py self-test 会自动起一个随机端口的实例）
"""
import base64
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 1x1 最小 JPEG，作为「未传人脸照」时的占位（mock 只验字段，不比内容）
_FAKE_JPEG = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    b"HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    b"AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")

_LOCK = threading.Lock()
_RECORDS = []
_LOGDIR = os.environ.get("MOCK_LOGDIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "30-logs")
_CAPTURE = os.path.join(_LOGDIR, "autorun_mock_capture.jsonl")


def _log(method, path, body):
    try:
        os.makedirs(_LOGDIR, exist_ok=True)
        with open(_CAPTURE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(time.time() * 1000), "m": method, "p": path,
                                "len": len(body or "")}, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _env(code, data=None, msg=""):
    return json.dumps({"code": code, "data": data, "msg": msg}, ensure_ascii=False).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "AuToRun-Mock/1.0"

    def log_message(self, *args):  # 静默默认访问日志
        pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        _log(self.command, self.path, raw)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send(_env(0))

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/exercise/records":
            with _LOCK:
                recs = [{"id": r["id"], "formatSportRange": r.get("formatSportRange"),
                         "startTime": r.get("startTime"), "identify": r.get("identify")}
                        for r in _RECORDS]
            self._send(_env(0, {"records": recs, "total": len(recs)}))
            return
        if path == "/api/exercise/summary":
            with _LOCK:
                cnt = len(_RECORDS)
                dist = sum(float(r.get("sportRange") or 0) for r in _RECORDS)
            self._send(_env(0, {"sumCount": cnt, "sumDistance": round(dist / 1000.0, 2),
                                "sumMetre": round(dist, 1), "validCount": cnt}))
            return
        if path.startswith("/api/exercise/record/"):
            rid = path.rsplit("/", 1)[-1]
            with _LOCK:
                rec = next((r for r in _RECORDS if str(r.get("id")) == rid), None)
            self._send(_env(0, rec) if rec else _env(404, None, "not found"), 200 if rec else 404)
            return
        if path == "/api/account/info":
            self._send(_env(0, {"basUserId": "uid-autorun-1", "id": "uid-autorun-1"}))
            return
        if path.startswith("/api/account/faces"):
            self._send(_env(0, {"list": [{"id": "f1"}]}))
            return
        self._send(_env(404, None, "unknown path"), 404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()
        if path == "/api/auth/token":
            self._send(_env(0, {"token": "AUTORUN-MOCK-TOKEN",
                                "userId": "uid-autorun-1"}))
            return
        if path == "/api/exercise/setting":
            self._send(_env(0, {
                "identify": "autorun-identify-0001",
                "totalRange": 2000.0,
                "startQualifiedTime": 0,
                "limitSpeed": 3.0,
                "isStartFace": 1, "isEndFace": 1, "isMidwayFace": 1,
                "middleFaces": [{"fraction": 0.3}, {"fraction": 0.7}],
                "geofence": [],
            }))
            return
        if path == "/api/exercise/startTime":
            self._send(_env(0, {"startTime": int(time.time() * 1000)}))
            return
        if path == "/api/exercise/face":
            # 校验坐标字段格式即可
            coord = body.get("coordinates") or ""
            ok = "," in coord
            self._send(_env(0 if ok else 400, {"ok": ok}, "" if ok else "bad coordinates"),
                      200 if ok else 400)
            return
        if path == "/api/exercise/record":
            rid = "rec-%d" % int(time.time() * 1000)
            rec = dict(body)
            rec["id"] = rid
            with _LOCK:
                _RECORDS.append(rec)
            self._send(_env(0, {"id": rid}))
            return
        if path == "/api/account/faceImage":
            self._send(_env(0, {"image": base64.b64encode(_FAKE_JPEG).decode("ascii")}))
            return
        self._send(_env(404, None, "unknown path"), 404)


def make_server(host="127.0.0.1", port=0):
    return ThreadingHTTPServer((host, port), _Handler)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = make_server(a.host, a.port)
    print("[AuToRun mock] 监听 http://%s:%d" % (a.host, srv.server_address[1]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
