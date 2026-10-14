# Watermark Remover

> 本地视频反水印工具 · Flask + OpenCV + FFmpeg

完全本地运行的视频水印去除工具。视频不上传任何服务器。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](#系统要求)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#快速开始)

## 特性

| 层    | 目标                                       | 实现                              |
| ----- | ------------------------------------------ | --------------------------------- |
| 视频帧 | 任意位置静态水印（角标、滚动条、字幕等）   | OpenCV inpainting（Telea / NS）   |
| 编码  | H.264 输出                                 | FFmpeg pipe                       |
| 音轨  | 保留原始音轨（AAC 重编码）                 | FFmpeg remux                      |
| 界面  | Web 拖拽 + 框选                            | 原生 HTML / CSS / JS              |

## 系统要求

- Python 3.10+
- FFmpeg 与 ffprobe（需要在 PATH 中）
  - macOS：`brew install ffmpeg`
  - Windows：`choco install ffmpeg` 或从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载并加入 PATH
  - Linux：`sudo apt install ffmpeg` 或对应发行版包管理器

## 快速开始

### macOS / Linux

```bash
make prepare    # 创建 .venv 并安装依赖
make serve      # 后台启动服务（默认端口 8300）
make stop       # 停止服务
```

或直接用脚本：

```bash
bash scripts/prepare.sh
bash scripts/dev.sh
bash scripts/stop.sh
```

### Windows（PowerShell）

```powershell
.\scripts\prepare.ps1
.\scripts\dev.ps1
.\scripts\stop.ps1
```

详见 [docs/windows-autostart.md](docs/windows-autostart.md) 在 Windows 登录时自动启动。

### 不通过脚本直接运行

```bash
# 创建虚拟环境
python3 -m venv .venv

# 安装依赖
# macOS / Linux
.venv/bin/python -m pip install -r requirements.txt
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动
# macOS / Linux
.venv/bin/python app.py
# Windows
.venv\Scripts\python.exe app.py
```

## Quick use

### Web 界面

1. 拖拽视频文件到页面（或点击选择本地视频）
2. 在视频画面上拖动鼠标框选要去除的水印区域
3. 选择算法（Telea 默认 / Navier-Stokes）与修复半径（1-8）
4. 等待处理完成，预览或下载结果

### curl

```bash
# 1. 上传
curl -X POST http://127.0.0.1:8300/api/upload \
  -F "video=@/path/to/video.mp4"
# {"id":"abc...","src":"/uploads/abc....mp4","info":{...}}

# 2. 处理（box 为归一化坐标 0-1）
curl -X POST http://127.0.0.1:8300/api/process \
  -H "Content-Type: application/json" \
  -d '{
    "id": "abc...",
    "box": {"x": 0.7, "y": 0.05, "w": 0.25, "h": 0.08},
    "method": "telea",
    "radius": 3
  }'
# {"success":true,"url":"/output/abc..._result.mp4","info":{...}}

# 3. 下载
curl -O -J http://127.0.0.1:8300/output/abc..._result.mp4
```

### Python 客户端

```python
import requests

with open("input.mp4", "rb") as f:
    r = requests.post("http://127.0.0.1:8300/api/upload",
                      files={"video": f}, timeout=600)
    vid = r.json()["id"]

r = requests.post("http://127.0.0.1:8300/api/process", json={
    "id": vid,
    "box": {"x": 0.7, "y": 0.05, "w": 0.25, "h": 0.08},
    "method": "telea",
    "radius": 3,
}, timeout=7200)
out_url = r.json()["url"]
print("result:", out_url)
```

## How it works

逐帧对上传视频做 OpenCV inpainting：

1. 用户上传视频 → 服务端保存到 `uploads/`
2. FFmpeg 提取首帧（或指定时间点的帧）作为预览
3. 用户在网页上拖动鼠标框选水印区域，归一化为 `{x, y, w, h}`
4. 服务端逐帧读取，用 OpenCV `cv2.inpaint` 修复框内像素
5. 修复后的帧通过 stdin pipe 送入 FFmpeg，编码为 H.264
6. 合并原音轨（`mux_audio`），生成最终 mp4 写入 `output/`

修复算法选择：

- **Telea**（默认）—— 沿等照度线方向快速传播，边界处理自然，适合大多数静态水印
- **Navier-Stokes** —— 基于流体动力学方程，边缘过渡更平滑，适合过渡区域

修复半径默认 3，建议范围 1-8。半径越大修复扩散范围越广，但可能模糊原画面细节。

## API

| Method | Path                 | Body / Params                                        | Returns                                                  |
| ------ | -------------------- | ----------------------------------------------------- | -------------------------------------------------------- |
| GET    | `/`                  | —                                                     | 主页 HTML                                                |
| POST   | `/api/upload`        | `multipart/form-data`，字段 `video=<file>`            | `{id, src, info: {width, height, fps, duration, ...}}`   |
| GET    | `/api/preview-frame` | `?id=<vid>&time=<秒>`                                 | JPEG 图像                                                |
| POST   | `/api/process`       | `{id, box: {x,y,w,h}, method, radius}`                | `{success, url, info}`                                   |
| GET    | `/output/<name>`     | —                                                     | 文件下载（`attachment`）                                 |

上传上限 **1 GiB**（Flask `MAX_CONTENT_LENGTH`）。处理超时默认 **2 小时**，单个 ffmpeg 子进程超时 **1 小时**。

## 限制

- **静态水印** —— 仅对位置固定的水印有效；动态水印（位置/内容变化）需要逐帧标记，效果下降
- **inpainting 扩散** —— 修复原理是周边像素扩散，复杂图案水印可能留轻微痕迹
- **处理时长** —— 与视频时长和分辨率正相关：1 分钟 1080p 视频通常 30 秒到数分钟
- **监听范围** —— 默认 `127.0.0.1`，不暴露到外网；如需远程访问自行加反向代理并配置鉴权

## 自定义端口

启动前设置环境变量 `DEPLOY_RUN_PORT`：

```bash
# macOS / Linux
DEPLOY_RUN_PORT=9000 make serve

# Windows PowerShell
$env:DEPLOY_RUN_PORT = "9000"; .\scripts\dev.ps1
```

或在 shell 中：

```bash
export DEPLOY_RUN_PORT=9000
bash scripts/dev.sh
```

## 项目结构

```
watermark-remover/
├── app.py                  # Flask 后端
├── requirements.txt
├── Makefile
├── .env.example
├── README.md
├── LICENSE
├── docs/
│   └── windows-autostart.md
├── scripts/
│   ├── prepare.sh / prepare.ps1    # 创建 venv + pip install
│   ├── dev.sh     / dev.ps1        # 后台启动
│   └── stop.sh    / stop.ps1       # 按 PID 文件停止
├── static/
│   ├── app.js              # 前端交互
│   └── main.css            # 样式
└── templates/
    └── index.html          # 主页
```

`uploads/`、`output/`、`logs/` 由运行时自动创建，已在 `.gitignore` 中排除。

## Development

```bash
make prepare    # 准备 venv
make dev        # 前台运行（实时日志输出）
make clean      # 清运行时产物（uploads/output/logs，保留 .gitkeep）
make check      # 校验依赖可正常 import
```

清理运行环境：

```bash
make clean      # 清 uploads / output / logs
rm -rf .venv    # 删 venv（重装时使用）
```

## License

MIT — see [LICENSE](LICENSE).
## 🍎 macOS 首次启动

如果从 **下载的 DMG** 把 .app 拖到 Applications 后**双击闪退**，是 macOS Gatekeeper 在拦（developer 未签名）。解决：

```bash
# 方案 A：右键打开（首次）
# 在 Finder → 找到 .app → 右键 → 打开 → 「打开」

# 方案 B：清除隔离属性
xattr -dr com.apple.quarantine /Applications/WatermarkRemover.app
```

关闭窗口 = 隐藏到 Dock（不退出）。再点 Dock 图标会自动重新显示窗口。
