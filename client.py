# -*- coding: utf-8 -*-
"""client.py —— 协议客户端（原创，仅用标准库）。

与 mock_srv.py 共用一套自洽的 JSON 信封（{"code","data","msg"}）。
base / 路径均可配置：将来若要对接真实服务，只需把 base 与端点路径换成对应的即可。
统一用 Bearer token 鉴权。
"""
import base64
import json
import urllib.request
import urllib.error


class ClientError(Exception):
    def __init__(self, msg, payload=None):
        super().__init__(msg)
        self.payload = payload


class Client:
    def __init__(self, base, school_code="autorun", timeout=20.0, device=None, app_version=None):
        self.base = base.rstrip("/")
        self.school_code = school_code
        self.timeout = timeout
        self.token = None
        self.device = device or {}
        self.app_version = app_version or "1.0.0"

    # ---- 底层
    def _req(self, method, path, body=None, raw=False):
        url = self.base + path
        data = None
        headers = {"User-Agent": "AuToRun/1.0", "X-School": self.school_code}
        if self.token:
            headers["Authorization"] = "Bearer %s" % self.token
        if body is not None:
            if raw:
                data = body
                headers["Content-Type"] = "application/octet-stream"
            else:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                if raw:
                    return r.read()
                payload = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "ignore")
            try:
                payload = json.loads(txt)
            except Exception:
                payload = {"code": e.code, "msg": txt}
            raise ClientError("HTTP %s" % e.code, payload)
        except Exception as e:  # noqa: BLE001
            raise ClientError(str(e))
        if isinstance(payload, dict) and payload.get("code") not in (0, None, "0"):
            raise ClientError(payload.get("msg") or "code=%s" % payload.get("code"), payload)
        return payload

    def _post(self, path, body=None):
        return self._req("POST", path, body)

    def _get(self, path):
        return self._req("GET", path)

    # ---- 业务
    def login(self, username, password):
        r = self._post("/api/auth/token", {"username": username, "password": password})
        self.token = (r.get("data") or {}).get("token")
        if not self.token:
            raise ClientError("登录未返回 token", r)
        return self.token

    def setting(self, run_type):
        r = self._post("/api/exercise/setting", {"runType": int(run_type)})
        return r.get("data") or {}

    def start_time(self, identify):
        r = self._post("/api/exercise/startTime", {"identify": identify})
        return int((r.get("data") or {}).get("startTime") or 0)

    def face(self, image_bytes, coordinates, identify, run_type, face_type):
        r = self._post("/api/exercise/face", {
            "identify": identify, "runType": int(run_type), "faceType": int(face_type),
            "coordinates": coordinates,
            "image": base64.b64encode(image_bytes or b"").decode("ascii"),
        })
        return r

    def add_record(self, gen, setting=None, run_type=1):
        submit = dict(gen.get("submit") or {})
        submit["runType"] = int(run_type)
        if setting:
            submit["identify"] = setting.get("identify")
        r = self._post("/api/exercise/record", submit)
        rid = (r.get("data") or {}).get("id")
        return r, rid

    def list_records(self):
        r = self._get("/api/exercise/records")
        return r.get("data") or {}

    def sum(self):
        r = self._get("/api/exercise/summary")
        return r.get("data") or {}

    def get_record(self, rid):
        r = self._get("/api/exercise/record/%s" % rid)
        return r.get("data") or {}

    def user_info(self):
        r = self._get("/api/account/info")
        return r.get("data") or {}

    def fetch_face_image(self, uid):
        try:
            r = self._post("/api/account/faceImage", {"uid": uid})
            b64 = (r.get("data") or {}).get("image")
            return base64.b64decode(b64) if b64 else None
        except Exception:  # noqa: BLE001
            return None

    def list_bas_user_image_face(self, uid):
        try:
            r = self._get("/api/account/faces?uid=%s" % uid)
            return (r.get("data") or {}).get("list") or []
        except Exception:  # noqa: BLE001
            return []

    def add_pixel_noise(self, img):
        # 无 Pillow 时原样返回；有则加噪。保持可选依赖。
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(img)).convert("RGB")
            px = im.load()
            for _ in range(50):
                x = random.randint(0, im.width - 1)
                y = random.randint(0, im.height - 1)
                r_, g, b = px[x, y]
                px[x, y] = (min(255, r_ + 8), min(255, g + 8), min(255, b + 8))
            out = io.BytesIO()
            im.save(out, format="JPEG")
            return out.getvalue()
        except Exception:  # noqa: BLE001
            return img


import random  # noqa: E402  (add_pixel_noise 用)
