# -*- coding: utf-8 -*-
"""webapp.py —— 网页工作台后端（原创，仅标准库 http.server）。

功能：
  - 提供本地网页（地图画线 + 参数 + 生成 + 提交 + 步骤回执）；
  - 内置一个本地 mock（127.0.0.1:18080），默认离线闭环，不连外网；
  - /api/* 暴露 generate / submit / config / stage.login / stage.run。

运行：python run.py web   （run.py 会调用本模块 start()）
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pipeline as P
import trackgen as T

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
MOCK_BASE = "http://127.0.0.1:18080"
_mock_thread = None


def ensure_mock():
    """懒启动内置 mock（仅本地、离线）。"""
    global _mock_thread
    if _mock_thread is None:
        import mock_srv as M
        srv = M.make_server("127.0.0.1", 18080)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        _mock_thread = t


def _json(payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"}, body


def generate_track(params):
    gen = T.generate(params)
    line = [[p["o"], p["a"]] for p in gen["pointdata"]]
    return {
        "ok": True,
        "metrics": gen["metrics"],
        "validity": gen["validity"],
        "faces": gen["faces"],
        "line": line,
        "points": gen["pointdata"],
        "buckets": gen["buckets"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AuToRun-Web/1.0"

    def log_message(self, *args):
        pass

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self._send(204, {"Access-Control-Allow-Origin": "*",
                         "Access-Control-Allow-Headers": "*",
                         "Access-Control-Allow-Methods": "GET,POST,OPTIONS"}, b"")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file("index.html")
            return
        if path == "/api/config":
            self._send(*_json({"ok": True, "default_base": MOCK_BASE,
                               "crs": ["gcj02", "wgs84"],
                               "run_types": {"1": "晨跑", "2": "阳光跑", "3": "自由跑"},
                               "devices": ["AutorunDevice"]}))
            return
        if path.startswith("/static/"):
            self._serve_file(path[len("/static/"):])
            return
        self._send(*_json({"ok": False, "msg": "not found"}, 404))

    def _serve_file(self, name):
        fp = os.path.normpath(os.path.join(STATIC, name))
        if not fp.startswith(STATIC) or not os.path.isfile(fp):
            self._send(404, {"Content-Type": "text/plain"}, b"not found")
            return
        ctype = "text/html" if name.endswith(".html") else (
            "application/javascript" if name.endswith(".js") else "text/plain")
        with open(fp, "rb") as f:
            self._send(200, {"Content-Type": ctype + "; charset=utf-8"}, f.read())

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/generate":
            try:
                self._send(*_json(generate_track(body.get("params") or {})))
            except Exception as e:  # noqa: BLE001
                self._send(*_json({"ok": False, "msg": str(e)}, 400))
            return
        if path == "/api/submit":
            ensure_mock()
            base = body.get("base") or MOCK_BASE
            params = body.get("params") or {}
            faces = body.get("faces", True)
            run_type = int(body.get("run_type") or 1)
            try:
                r = P.run_pipeline(base=base, params=params, faces=faces, run_type=run_type)
            except Exception as e:  # noqa: BLE001
                self._send(*_json({"ok": False, "msg": str(e)}, 400))
                return
            self._send(*_json({"ok": r.get("ok"), "steps": r.get("steps"),
                               "recordId": r.get("recordId"), "sum": r.get("sum")}))
            return
        if path == "/api/stage/login":
            ensure_mock()
            base = body.get("base") or MOCK_BASE
            try:
                r = P.stage_login(base=base, school_code=body.get("school_code", "autorun"),
                                  username=body.get("username", "student"),
                                  password=body.get("password", "pass"),
                                  run_type=int(body.get("run_type") or 1))
            except Exception as e:  # noqa: BLE001
                self._send(*_json({"ok": False, "msg": str(e)}, 400))
                return
            self._send(*_json({"ok": r.get("ok"), "session": r.get("session"), "info": r.get("info"),
                               "steps": r.get("steps")}))
            return
        if path == "/api/stage/run":
            ensure_mock()
            base = body.get("base") or MOCK_BASE
            try:
                r = P.stage_run(base=base, session=body.get("session"),
                                params=body.get("params"), faces=body.get("faces", True),
                                run_type=int(body.get("run_type") or 1))
            except Exception as e:  # noqa: BLE001
                self._send(*_json({"ok": False, "msg": str(e)}, 400))
                return
            self._send(*_json({"ok": r.get("ok"), "steps": r.get("steps"),
                               "recordId": r.get("recordId"), "sum": r.get("sum")}))
            return
        self._send(*_json({"ok": False, "msg": "not found"}, 404))


def make_server(host="127.0.0.1", port=8770):
    return ThreadingHTTPServer((host, port), Handler)


def start(host="127.0.0.1", port=8770, with_window=True):
    ensure_mock()
    srv = make_server(host, port)
    url = "http://%s:%d" % (host, srv.server_address[1])
    print("[AuToRun web] 工作台: %s" % url)
    print("[AuToRun web] 内置 mock: %s（仅本地，离线）" % MOCK_BASE)
    if with_window:
        try:
            import webview  # pywebview 可选
            webview.create_window("AuToRun 工作台", url, width=1100, height=760)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            webview.start()
            return
        except Exception:  # noqa: BLE001
            print("[AuToRun web] 未装 pywebview，改用系统浏览器打开")
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    start()
