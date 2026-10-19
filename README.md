# AuToRun · 体适能 / 阳光跑 统一工具（CLI + 网页合一）
# AuToRun · Fitness / Sunshine-Run Unified Tool (CLI + Web in one)

体适能 / 阳光跑统一工具（CLI + 网页合一）。
A unified (CLI + web) tool for fitness / "Sunshine Run" / campus-run style apps, made by YesDeat.

一个本地运行的跑步记录工作台（体适能「阳光跑 / 校园跑 / 晨跑」类 App 适用）。在你的电脑上起一个本地服务 + 网页工作台：载入跑道 → 生成 GPS 轨迹 → 自动人脸打卡 → 上传，并提供命令行菜单（授权 / 跑步 / 爬路径 / 统计）。
A locally-run running-records workbench for fitness / "Sunshine Run" / campus-run apps. It spins up a local server + web workbench: load a track → generate a GPS track → automatic face check-in → upload, plus a CLI menu (authorize / run / scrape routes / statistics).

代码全部为原创实现，未复制任何第三方项目源码，以 MIT License 发布。
All code is an original implementation. No third-party source code is copied. Released under the MIT License.

> ⚠️ **仅供学习与个人研究。** 请遵守你所在学校的规定与相关服务条款，使用风险自负。本工具默认只连本地模拟服务，**不连任何外部服务器**；如需对接真实服务，请自行配置 `base`。
> ⚠️ **For learning and personal research only.** Please comply with your school's rules and the relevant terms of service; use at your own risk. By default this tool only connects to a local mock service and **does not contact any external server**; to target a real service, configure `base` yourself.

## 两种入口 / Two entry points

```bash
python run.py            # 默认起网页工作台（地图画线 + 全流程，内置本地 mock）
python run.py web        # 起网页工作台
python run.py cli        # 命令行菜单
python run.py self-test  # 自起本地 mock 跑一遍全流程（自测）
```
```bash
python run.py            # start the web workbench (default: map drawing + full flow, built-in local mock)
python run.py web        # start the web workbench
python run.py cli        # CLI menu
python run.py self-test  # spin up a local mock and run the full flow once (self-test)
```

CLI 菜单 / CLI menu：
```
1  启动网页工作台 / Start web workbench
2  授权账号（登录 + 拉配置，保存会话） / Authorize account (login + fetch config, save session)
3  开始跑步（用保存的会话） / Start running (uses the saved session)
4  爬取历史路径（从记录里抽 GPS 轨迹，存 routes_*.json） / Scrape historical routes (extract GPS tracks, save routes_*.json)
5  查询有效次数 / 累计里程 / Query valid count / cumulative distance
0  退出 / Exit
```

## 环境要求 / Requirements

- Python 3.11+
- Windows / macOS / Linux
- 仅标准库即可运行核心功能；`pywebview`（桌面窗口）与 `Pillow`（人脸图加噪）为可选增强
- Core features run with the standard library only; `pywebview` (desktop window) and `Pillow` (face-image noise) are optional enhancements

## 安装 / Install

```bash
python -m pip install -r requirements.txt   # 可选依赖：pywebview / Pillow
python -m pip install -r requirements.txt   # optional deps: pywebview / Pillow
```

## 运行 / Run

```bash
python run.py            # 网页工作台（默认，内置本地 mock）
python run.py cli        # 命令行菜单
```
```bash
python run.py            # web workbench (default, built-in local mock)
python run.py cli        # CLI menu
```

## 架构（模块均为原创）/ Architecture (all modules original)

| 模块 Module | 职责 Responsibility |
| --- | --- |
| `geo.py` | 坐标变换 WGS-84 <-> GCJ-02、距离与米/度换算 / Coordinate transforms WGS-84 <-> GCJ-02, distance & meter/degree conversion |
| `trackgen.py` | 轨迹生成：折线重采样、配速抖动、GPS 噪声、60s 步数桶、人脸点、提交表单、合格性 / Track generation: polyline resampling, pace jitter, GPS noise, 60s step buckets, face points, submit form, validity check |
| `client.py` | 协议客户端（仅标准库 urllib），JSON 信封 + Bearer 鉴权，端点可配置 / Protocol client (stdlib `urllib` only), JSON envelope + Bearer auth, configurable endpoints |
| `mock_srv.py` | 本地模拟服务（仅 127.0.0.1），离线闭环，内存存储 + 可选抓包日志 / Local mock service (127.0.0.1 only), offline closed loop, in-memory storage + optional capture log |
| `pipeline.py` | 全流程编排：登录 → 配置 → 开跑 → 人脸 → 上传 → 读回 → 汇总（含实时节奏器） / Full-flow orchestration: login → config → start → face → upload → readback → summary (with realtime pacer) |
| `webapp.py` | 网页工作台后端（标准库 http.server）+ 内置 mock / Web workbench backend (`http.server`) + built-in mock |
| `static/` | 网页前端：Leaflet 地图画线 + 参数 + 生成 + 提交（原生 JS） / Web frontend: Leaflet map drawing + params + generate + submit (vanilla JS) |
| `run.py` | 统一启动器：web / cli / self-test / Unified launcher: web / cli / self-test |

## 许可证 / License

MIT（见 `LICENSE`），版权归 **YesDeat**。
MIT (see `LICENSE`), copyright **YesDeat**.
