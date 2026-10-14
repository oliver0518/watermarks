# -*- coding: utf-8 -*-
"""
本地视频去水印工具 - Flask 后端
技术栈: Flask + OpenCV(inpainting) + FFmpeg
完全本地处理，不上传任何数据。
"""
import os
import sys
import uuid
import subprocess
import tempfile
import shutil
import json
import glob
import logging
import time

import cv2
import numpy as np
from flask import (
    Flask, request, jsonify, render_template, send_from_directory, send_file, abort
)

# ---------- 配置 ----------

app = Flask(__name__)
# 限制上传大小：1 GiB。Flask 会在超大请求时直接抛 413，避免内存被打爆。
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

# 日志先初始化，下面的 BASE 重定向块要用 log.info
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    # PyInstaller frozen 时也写一份到 ~/Library/Logs/WatermarkRemover.log，
    # 方便用户在 .app 闪退时排查（Gatekeeper 拦下后 stderr 看不到）。
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.expanduser("~/Library/Logs/WatermarkRemover.log"),
            mode="a",
        ) if sys.platform == "darwin" else logging.StreamHandler(),
    ],
)
log = logging.getLogger("watermark-remover")

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
OUTPUT_DIR = os.path.join(BASE, "output")
LOG_DIR = os.path.join(BASE, "logs")
for d in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)


# PyInstaller 打包后，把 uploads/output/logs 重定向到用户可写目录
# —— .app 安装到 /Applications 是系统保护的，普通用户写不进去。
if getattr(sys, "frozen", False):
    if sys.platform == "darwin":
        user_base = os.path.expanduser("~/Library/Application Support/WatermarkRemover")
    elif sys.platform == "win32":
        user_base = os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")),
            "WatermarkRemover",
        )
    else:
        user_base = os.path.expanduser("~/.local/share/watermark-remover")
    user_base = os.path.abspath(user_base)
    BASE = user_base
    UPLOAD_DIR = os.path.join(BASE, "uploads")
    OUTPUT_DIR = os.path.join(BASE, "output")
    LOG_DIR = os.path.join(BASE, "logs")
    for d in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    log.info("data dir -> %s", BASE)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

THUMB_DIR = os.path.join(BASE, "thumbnails")
os.makedirs(THUMB_DIR, exist_ok=True)


def extract_thumbnail(src, sid, width=240):
    """从视频第一秒抽一帧生成 jpg 缩略图，返回路径或 None。"""
    try:
        thumb_path = os.path.join(THUMB_DIR, sid + ".jpg")
        if os.path.exists(thumb_path):
            return thumb_path
        cmd = [
            FFMPEG, "-y", "-ss", "0", "-i", src,
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            "-q:v", "5",
            thumb_path,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode == 0 and os.path.exists(thumb_path):
            return thumb_path
        return None
    except Exception as e:
        log.warning("extract_thumbnail failed: %s", e)
        return None


def output_name_for(original_name):
    """把 'video.mp4' 变成 'video_去水印.mp4'。"""
    stem, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".mp4"
    return f"{stem}_去水印{ext}"


# ---------- 历史记录 ----------
import threading as _threading
HISTORY_LOCK = _threading.Lock()
HISTORY_FILE = os.path.join(BASE, "history.json")
HISTORY_MAX = 30  # 最多保留多少条


def _load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("load history failed: %s", e)
        return []


def _save_history(items):
    try:
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HISTORY_FILE)
    except Exception as e:
        log.warning("save history failed: %s", e)


def add_history(record):
    """处理成功时记录一条历史。"""
    with HISTORY_LOCK:
        items = _load_history()
        items.insert(0, record)
        # 超过上限时清理最旧的文件
        if len(items) > HISTORY_MAX:
            for old in items[HISTORY_MAX:]:
                for key in ("srcPath", "outputPath", "thumbPath"):
                    p = old.get(key)
                    if p and os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            items = items[:HISTORY_MAX]
        _save_history(items)


def remove_history(record_id):
    with HISTORY_LOCK:
        items = _load_history()
        kept = []
        removed = None
        for it in items:
            if it.get("id") == record_id and removed is None:
                removed = it
            else:
                kept.append(it)
        if removed is not None:
            _save_history(kept)
            for key in ("srcPath", "outputPath", "thumbPath"):
                p = removed.get(key)
                if p and os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        return removed is not None


def _bundled_binary(name):
    """如果运行在 PyInstaller 打包的 .app/_exe 内，从 _MEIPASS 取出内嵌二进制。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = os.path.join(base, name)
        if os.path.isfile(candidate):
            # macOS/Linux 需要可执行权限；Windows 上 .exe 通常已有
            try:
                os.chmod(candidate, 0o755)
            except OSError:
                pass
            return candidate
    return None


# 优先使用打包时内嵌的 ffmpeg/ffprobe，未内嵌时回退到系统 PATH
FFMPEG = _bundled_binary("ffmpeg") or FFMPEG
FFPROBE = _bundled_binary("ffprobe") or FFPROBE

ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv"}

# 通过文件头几个字节快速判别，防止改后缀绕过
MAGIC_PREFIXES = (
    b"\x00\x00\x00\x18ftypmp42",
    b"\x00\x00\x00\x20ftypisom",
    b"\x00\x00\x00\x1cftypisom",
    b"\x00\x00\x00\x14ftypqt",
    b"\x1a\x45\xdf\xa3",   # mkv / webm
    b"RIFF",              # avi / webm
)

# 子进程超时：避免 ffmpeg 在坏文件上卡死把服务挂住
FFMPEG_TIMEOUT = 3600     # 单个 ffmpeg 子进程最长等待 1 小时
INPAINT_TIMEOUT = 7200   # 整个 inpaint 流程 2 小时上限


# ---------- 工具函数 ----------

def safe_move(src, dst):
    """原子移动：先 rename 到目标，失败时回退。"""
    try:
        os.replace(src, dst)
    except OSError:
        shutil.copyfile(src, dst)
        os.remove(src)


def detect_kind(path):
    """通过文件头 magic bytes 判别格式；失败返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    for magic in MAGIC_PREFIXES:
        if head.startswith(magic):
            return magic.decode(errors="ignore")
    return None


def allowed_file(name):
    return os.path.splitext(name)[1].lower() in ALLOWED_EXT


def video_info(path):
    """用 ffprobe 获取视频时长、宽高、fps、有无音频。"""
    cmd = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-show_entries", "format=duration",
        "-of", "json", path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    info = {"width": 0, "height": 0, "fps": 0.0, "duration": 0.0, "has_audio": False}
    try:
        data = json.loads(r.stdout)
    except Exception:
        return info
    v = (data.get("streams") or [{}])[0]
    if v:
        info["width"] = int(v.get("width") or 0)
        info["height"] = int(v.get("height") or 0)
        fr = v.get("r_frame_rate", "0/1")
        try:
            n, d = fr.split("/")
            info["fps"] = round(float(n) / float(d), 2) if float(d) else 0.0
        except Exception:
            info["fps"] = 0.0
    info["duration"] = float((data.get("format") or {}).get("duration") or 0)
    # 检测音频
    ar = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30)
    info["has_audio"] = bool(ar.stdout.strip())
    return info


# ---------- 路由 ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/uploads/<name>")
def uploaded(name):
    name = os.path.basename(name)
    full = os.path.join(UPLOAD_DIR, name)
    if not os.path.exists(full):
        abort(404)
    return send_from_directory(UPLOAD_DIR, name)


@app.route("/api/upload", methods=["POST"])
def upload():
    """支持单文件或多文件上传（一次请求）。
    - 单文件时返回顶层 id/src/info（向后兼容旧前端）
    - 多文件时返回 items: [...] 列表
    """
    files = request.files.getlist("video")
    if not files:
        return jsonify({"error": "未收到文件"}), 400

    items = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            items.append({"filename": f.filename, "error": "不支持的视频格式"})
            continue
        sid = uuid.uuid4().hex
        ext = os.path.splitext(f.filename)[1].lower()
        src = os.path.join(UPLOAD_DIR, sid + ext)
        try:
            f.save(src)
            kind = detect_kind(src)
            if kind is None:
                os.remove(src)
                items.append({"filename": f.filename, "error": "文件内容与扩展名不符"})
                continue
            info = video_info(src)
            if info["width"] <= 0 or info["height"] <= 0:
                os.remove(src)
                items.append({"filename": f.filename, "error": "无法解析该视频"})
                continue
            log.info("upload sid=%s %dx%d %.2fs %s", sid, info["width"], info["height"],
                     info["duration"], f.filename)
            items.append({
                "id": sid,
                "filename": f.filename,
                "src": f"/uploads/{sid}{ext}",
                "info": info,
                "thumbUrl": f"/api/thumb/{sid}",
            })
            # 把原始文件名存到 src 旁的 meta 文件，process 时读取
            try:
                with open(src + ".meta", "w", encoding="utf-8") as mf:
                    json.dump({"originalName": f.filename}, mf, ensure_ascii=False)
            except OSError:
                pass
            # 同步抽第一帧做缩略图（失败不影响上传）
            try:
                extract_thumbnail(src, sid)
            except Exception as e:
                log.warning("thumbnail extract error: %s", e)
        except Exception as e:
            log.exception("upload %s failed: %s", f.filename, e)
            items.append({"filename": f.filename, "error": str(e)})

    # 单文件：保留旧 schema 以便旧前端兼容
    if len(items) == 1:
        only = items[0]
        if "id" in only:
            return jsonify({
                "id": only["id"],
                "filename": only["filename"],
                "src": only["src"],
                "info": only["info"],
            })
        return jsonify({"error": only.get("error", "上传失败")}), 400

    # 多文件：返回 items 列表
    return jsonify({"items": items})


@app.route("/api/preview-frame", methods=["GET"])
def preview_frame():
    """提取指定时间点的帧，用于前端定位水印。time 单位秒。"""
    vid = request.args.get("id")
    t = float(request.args.get("time", "0"))
    if not vid:
        return jsonify({"error": "缺少 id"}), 400
    matches = glob.glob(os.path.join(UPLOAD_DIR, vid) + ".*")
    if not matches:
        return jsonify({"error": "文件不存在"}), 404
    src = matches[0]
    frame_path = os.path.join(UPLOAD_DIR, vid + "_frame.jpg")
    cmd = [FFMPEG, "-y", "-ss", str(max(0.0, t)), "-i", src,
           "-frames:v", "1", "-q:v", "3", frame_path]
    r = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
    if r.returncode != 0 or not os.path.exists(frame_path):
        return jsonify({"error": "帧提取失败"}), 500
    return send_file(frame_path, mimetype="image/jpeg")


# ------- 去水印核心处理 -------

def inpaint_video(src, out, box, method="telea", radius=3):
    """
    逐帧对水印区域做 inpainting 修复，输出 H.264 编码。
    box: (x, y, w, h) 像素坐标
    method: telea / ns
    """
    # macOS 上 cv2.VideoCapture 偶发一次性失败（多 ffmpeg 子进程 fd 竞争 / 文件 lock），
    # 重试一次可绕过大多数 transient 错误
    cap = None
    for attempt in range(3):
        cap = cv2.VideoCapture(src)
        if cap.isOpened():
            break
        cap.release()
        time.sleep(0.4 * (attempt + 1))
    else:
        raise RuntimeError(f"无法打开视频文件：{src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if w <= 0 or h <= 0:
        cap.release()
        raise RuntimeError("视频尺寸无效")

    x, y, bw, bh = box
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    bw = max(1, min(bw, w - x))
    bh = max(1, min(bh, h - y))

    # 构建水印区域 mask（考虑到 inpainting 需要一点边缘过渡，略微外扩）
    pad = radius * 2
    mx0 = max(0, x - pad)
    my0 = max(0, y - pad)
    mx1 = min(w, x + bw + pad)
    my1 = min(h, y + bh + pad)

    method_flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS

    # 启动 FFmpeg 进程，通过 pipe 接收原始帧数据，输出 H.264 编码
    ffmpeg_cmd = [
        FFMPEG, "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-crf", "23",
        out
    ]
    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    count = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[my0:my1, mx0:mx1] = 255
            res = cv2.inpaint(frame, mask, radius, method_flag)
            try:
                proc.stdin.write(res.tobytes())
            except BrokenPipeError:
                raise RuntimeError("FFmpeg 子进程提前退出（编码失败）")
            count += 1
            if count % 60 == 0:
                # 每 60 帧 poll 一次，避免主进程在 stdin 阻塞时无法响应超时
                if proc.poll() is not None:
                    raise RuntimeError(f"FFmpeg 提前退出（returncode={proc.returncode}）")
        log.info("inpainted %d frames", count)
    finally:
        cap.release()
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except Exception:
                pass

    try:
        proc.wait(timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise RuntimeError(f"FFmpeg 编码超时（>{FFMPEG_TIMEOUT} 秒）")
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 编码失败（returncode={proc.returncode}）")


def mux_audio(src, video_without_audio, out_final):
    """把原视频的音轨合并到处理后的视频上。"""
    r = subprocess.run([
        FFMPEG, "-y", "-i", video_without_audio, "-i", src,
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy",
        "-c:a", "aac",
        "-shortest", out_final
    ], capture_output=True, timeout=FFMPEG_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError("音频合失败：" + r.stderr.decode(errors="ignore")[:200])


@app.route("/api/process", methods=["POST"])
def process():
    data = request.get_json(silent=True) or {}
    vid = data.get("id")
    box = data.get("box")   # {x,y,w,h} 归一化 0-1
    method = data.get("method", "telea")
    radius = int(data.get("radius", 3))
    if not vid or not box:
        return jsonify({"error": "参数不完整"}), 400

    matches = [m for m in glob.glob(os.path.join(UPLOAD_DIR, vid) + ".*")
               if not m.endswith(".meta")]
    if not matches:
        return jsonify({"error": "源文件不存在"}), 404
    src = matches[0]

    info = video_info(src)
    W, H = info["width"], info["height"]
    # 归一化区域 -> 像素
    x = int(box["x"] * W)
    y = int(box["y"] * H)
    bw = int(box["w"] * W)
    bh = int(box["h"] * H)
    px_box = (x, y, bw, bh)

    tmpdir = tempfile.mkdtemp(dir=OUTPUT_DIR)
    no_audio = os.path.join(tmpdir, "noaudio.mp4")
    final = os.path.join(tmpdir, "result.mp4")

    try:
        inpaint_video(src, no_audio, px_box, method=method, radius=radius)
        if info["has_audio"]:
            mux_audio(src, no_audio, final)
        else:
            shutil.copyfile(no_audio, final)

        # 校验输出可读且尺寸合理
        finfo = video_info(final)
        if finfo["width"] <= 0 or finfo["height"] <= 0:
            raise RuntimeError("输出视频无效")

        # 移动到顶层 output 便于下载
        # 文件名 = "<sid>_<原名去水印>.mp4"，用 sid 前缀避免同名冲突
        # 优先从 src 旁的 meta 文件读 originalName（用户在 upload 时的原文件名）
        original_name = None
        meta_path = src + ".meta"
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as mf:
                    original_name = (json.load(mf) or {}).get("originalName")
            except Exception:
                pass
        if not original_name:
            # fallback：现有 history record
            existing = _find_history_item(vid)
            if existing and existing.get("originalName"):
                original_name = existing["originalName"]
        if not original_name:
            original_name = os.path.basename(src)
        out_basename = output_name_for(original_name)
        public_out = os.path.join(OUTPUT_DIR, f"{vid}__{out_basename}")
        safe_move(final, public_out)
        shutil.rmtree(tmpdir, ignore_errors=True)
        # 写/更新历史
        try:
            thumb_path = os.path.join(THUMB_DIR, vid + ".jpg")
            add_history({
                "id": vid,
                "originalName": original_name,
                "outputName": out_basename,
                "processedAt": int(time.time()),
                "width": finfo["width"],
                "height": finfo["height"],
                "duration": info.get("duration", 0.0),
                "size": os.path.getsize(public_out),
                "srcPath": src,
                "outputPath": public_out,
                "thumbPath": thumb_path if os.path.isfile(thumb_path) else None,
            })
        except Exception as e:
            log.warning("add_history failed: %s", e)
        log.info("processed sid=%s -> %s", vid, public_out)
        return jsonify({
            "success": True,
            "url": f"/output/{os.path.basename(public_out)}",
            "info": {"width": finfo["width"], "height": finfo["height"],
                     "fps": finfo["fps"], "size": os.path.getsize(public_out)}
        })
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        log.exception("process failed sid=%s: %s", vid, e)
        return jsonify({"error": f"处理失败: {e}"}), 500


@app.route("/output/<name>")
def output(name):
    name = os.path.basename(name)
    return send_from_directory(OUTPUT_DIR, name, as_attachment=True,
                               download_name=name)


# ---------- 历史 API ----------
def _find_history_item(rid):
    for it in _load_history():
        if it.get("id") == rid:
            return it
    return None


@app.route("/api/history", methods=["GET"])
def api_history_list():
    items = _load_history()
    out = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "originalName": it.get("originalName", "video.mp4"),
            "outputName": it.get("outputName") or output_name_for(it.get("originalName", "video.mp4")),
            "processedAt": it.get("processedAt"),
            "width": it.get("width", 0),
            "height": it.get("height", 0),
            "duration": it.get("duration", 0.0),
            "size": it.get("size", 0),
            "thumbUrl": f"/api/thumb/{it.get('id')}",
            "downloadUrl": f"/api/history/{it.get('id')}/download",
        })
    return jsonify(out)


@app.route("/api/history/<rid>/download")
def api_history_download(rid):
    it = _find_history_item(rid)
    if not it:
        abort(404)
    p = it.get("outputPath")
    if not p or not os.path.isfile(p):
        abort(404)
    return send_file(
        p,
        as_attachment=True,
        download_name=output_name_for(it.get("originalName", os.path.basename(p))),
    )


@app.route("/api/history/<rid>/view")
def api_history_view(rid):
    """inline 流式返回 mp4，让 WebKit <video> 标签直接播放（不下载）。"""
    it = _find_history_item(rid)
    if not it:
        abort(404)
    p = it.get("outputPath")
    if not p or not os.path.isfile(p):
        abort(404)
    return send_file(p, mimetype="video/mp4", conditional=True)


@app.route("/api/thumb/<sid>")
def api_thumb(sid):
    """返回上传视频的第一帧 jpg 缩略图。"""
    # 安全：只允许字母数字
    if not sid.isalnum():
        abort(404)
    p = os.path.join(THUMB_DIR, sid + ".jpg")
    if not os.path.isfile(p):
        # 源可能还在但缩略图还没生成（抽帧失败）— 尝试现在抽
        # 找 uploads 里匹配 sid.* 的源文件
        for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"):
            src = os.path.join(UPLOAD_DIR, sid + ext)
            if os.path.isfile(src):
                extract_thumbnail(src, sid)
                break
    if not os.path.isfile(p):
        # 1x1 透明 png fallback
        from flask import Response
        return Response(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
            mimetype="image/png",
        )
    return send_file(p, mimetype="image/jpeg", max_age=3600)


@app.route("/api/history/<rid>", methods=["DELETE"])
def api_history_delete(rid):
    ok = remove_history(rid)
    if not ok:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({"ok": True})


# ---------- 入口 ----------

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "上传文件过大（上限 1 GiB）"}), 413


if __name__ == "__main__":
    import threading
    import time
    import webbrowser

    port = int(os.environ.get("DEPLOY_RUN_PORT", "8300"))
    host = "127.0.0.1"

    log.info("starting watermark-remover on http://%s:%d (frozen=%s)",
             host, port, getattr(sys, "frozen", False))

    if getattr(sys, "frozen", False):
        # 打包态：起后台 Flask + 用系统 WebKit 弹原生窗口（pywebview）
        # 必须 main thread 跑 webview，后台线程跑 HTTP server
        from werkzeug.serving import make_server

        server = make_server(host, port, app, threaded=True)
        server_thread = threading.Thread(
            target=server.serve_forever, name="flask-server", daemon=True
        )
        server_thread.start()

        try:
            import webview  # pywebview：跨平台 native window
        except Exception as exc:
            log.error("import pywebview failed (%s) — fall back to webbrowser", exc)
            webbrowser.open(f"http://{host}:{port}")
            server.serve_forever()
        else:
            # ---- pywebview Api（暴露给 JS 调，弹原生 NSSavePanel） ----
            class Api:
                def save_as(self, result_id):
                    """弹原生 NSSavePanel，让用户选目录保存。"""
                    out_path = os.path.join(OUTPUT_DIR, result_id + "_result.mp4")
                    if not os.path.isfile(out_path):
                        return None
                    # 默认文件名
                    history_item = _find_history_item(result_id)
                    default = "去水印_" + (history_item["originalName"]
                                            if history_item else "video.mp4")
                    try:
                        result = window.create_file_dialog(
                            webview.SAVE_DIALOG,
                            save_filename=default,
                            file_types=("视频 (*.mp4)", "所有文件 (*)"),
                        )
                    except Exception as e:
                        log.warning("create_file_dialog failed: %s", e)
                        return None
                    # result 可能是 tuple/list[str] 或 str
                    target = None
                    if isinstance(result, (tuple, list)) and result:
                        target = result[0]
                    elif isinstance(result, str):
                        target = result
                    if not target:
                        return None  # 用户取消
                    try:
                        shutil.copy2(out_path, target)
                        return {"path": target, "name": os.path.basename(target)}
                    except Exception as e:
                        log.error("save_as copy failed: %s", e)
                        return {"error": str(e)}

                def quit_app(self):
                    """真正退出应用（用户从菜单/Dock 选 Quit 时调用）。"""
                    log.info("user requested quit")
                    try:
                        server.shutdown()
                    except Exception:
                        pass
                    try:
                        webview.destroy_window(window)
                    except Exception:
                        pass
                    import objc
                    objc.objc_super
                    from AppKit import NSApp
                    NSApp.terminate(None)

                def save_all(self, ids):
                    """批量下载：弹原生目录选择，把多个历史项的输出文件复制到该目录。"""
                    if not ids:
                        return None
                    # 弹原生目录选择
                    try:
                        result = window.create_file_dialog(
                            webview.FOLDER_DIALOG,
                            directory=os.path.expanduser("~/Downloads"),
                        )
                    except Exception as e:
                        log.warning("create_file_dialog FOLDER failed: %s", e)
                        return None
                    target_dir = None
                    if isinstance(result, (tuple, list)) and result:
                        target_dir = result[0]
                    elif isinstance(result, str):
                        target_dir = result
                    if not target_dir:
                        return None
                    # 复制文件
                    saved, failed = [], []
                    for rid in ids:
                        it = _find_history_item(rid)
                        if not it:
                            failed.append(rid)
                            continue
                        src = it.get("outputPath")
                        if not src or not os.path.isfile(src):
                            failed.append(rid)
                            continue
                        out_name = it.get("outputName") or output_name_for(
                            it.get("originalName", os.path.basename(src))
                        )
                        dst = os.path.join(target_dir, out_name)
                        # 同名自动加 _N 后缀
                        if os.path.exists(dst):
                            stem, ext = os.path.splitext(out_name)
                            for k in range(1, 1000):
                                cand = os.path.join(target_dir, f"{stem}_{k}{ext}")
                                if not os.path.exists(cand):
                                    dst = cand
                                    break
                        try:
                            shutil.copy2(src, dst)
                            saved.append(os.path.basename(dst))
                        except Exception as e:
                            log.warning("save_all copy %s failed: %s", rid, e)
                            failed.append(rid)
                    return {
                        "dir": target_dir,
                        "count": len(saved),
                        "saved": saved,
                        "failed": failed,
                    }

            window = webview.create_window(
                title="秋白去水印",
                url=f"http://{host}:{port}",
                width=960,
                height=760,
                resizable=True,
                min_size=(640, 520),
                text_select=True,
                js_api=Api(),  # 注入到 window.pywebview.api（必须用 js_api 参数）
            )

            api_instance = window._js_api  # pywebview 内部存了一份
            # 诊断：列出 js_api 暴露的方法，确认 save_as 在
            api_methods = [m for m in dir(api_instance) if not m.startswith('_') and callable(getattr(api_instance, m))]
            log.info("js_api injected, methods: %s, save_as: %s",
                     api_methods, callable(getattr(api_instance, "save_as", None)))

            # 关窗 = 隐藏（不退出进程）
            def on_closing():
                log.info("window closing intercepted — hide instead of destroy")
                window.hide()
                return False  # 取消关闭，仅隐藏

            try:
                window.events.closing += on_closing
            except Exception as e:
                log.warning("set closing handler failed: %s", e)

            # macOS: 让 app 不因最后一个 window 关闭而退出 + Dock 点击重新显示窗口
            if sys.platform == "darwin":
                try:
                    # 1) 阻止 NSApp 在所有 window 关闭时退出
                    try:
                        import webview.platforms.cocoa as cocoa_platform
                        _AppDelegate = getattr(cocoa_platform, "AppDelegate", None) \
                                       or getattr(cocoa_platform, "_AppDelegate", None)
                    except Exception:
                        _AppDelegate = None
                    if _AppDelegate is not None:
                        # 用 PyObjC 的 class extension 替换 method
                        try:
                            def _keep_alive(self, _sender):
                                return False
                            import objc
                            objc.classAddMethod(
                                _AppDelegate,
                                b"applicationShouldTerminateAfterLastWindowClosed:",
                                _keep_alive,
                            )
                            log.info("AppDelegate patched: keep alive after window close")
                        except Exception as e:
                            log.warning("patch AppDelegate (keep alive) failed: %s", e)

                        # 2) Dock 点击重新显示窗口 —— 必须用 applicationShouldHandleReopen:hasVisibleWindows:
                        #    否则之前用的 NSApplicationDidBecomeActiveNotification 在 app 没退出的情况下不会触发
                        try:
                            def _reopen_has_windows(self, _sender, _flag):
                                try:
                                    window.show()
                                    NSApp.activateIgnoringOtherApps_(True)
                                except Exception as exc:
                                    log.warning("reopen show failed: %s", exc)
                                return True
                            import objc as _objc
                            _objc.classAddMethod(
                                _AppDelegate,
                                b"applicationShouldHandleReopen:hasVisibleWindows:",
                                _reopen_has_windows,
                            )
                            log.info("AppDelegate patched: Dock click reopens window")
                        except Exception as e:
                            log.warning("patch AppDelegate (reopen) failed: %s", e)

                    # 兜底：监听 NSApplicationDidBecomeActiveNotification（用户切换前台时同步）
                    try:
                        from Foundation import (
                            NSNotificationCenter,
                            NSApplicationDidBecomeActiveNotification,
                        )
                        from AppKit import NSApp

                        def _on_active(_notification):
                            try:
                                if window.hidden:
                                    window.show()
                                    NSApp.activateIgnoringOtherApps_(True)
                            except Exception:
                                pass

                        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
                            NSApplicationDidBecomeActiveNotification,
                            None,
                            None,
                            _on_active,
                        )
                    except Exception as e:
                        log.warning("became-active observer failed: %s", e)

                except Exception as e:
                    log.warning("macOS Dock handler setup failed: %s", e)


            # 启动 webview 事件循环（阻塞直到 NSApp 退出）
            webview.start()
            log.info("NSApp exited, shutting down")
            try:
                server.shutdown()
            except Exception:
                pass
            log.info("watermark-remover exiting")
    else:
        # 开发态：起 Flask + 用默认浏览器自动打开
        def _open_browser():
            time.sleep(1.5)
            try:
                webbrowser.open(f"http://{host}:{port}")
            except Exception:
                pass

        threading.Thread(target=_open_browser, daemon=True).start()
        log.info("starting watermark-remover on http://%s:%d", host, port)
        app.run(host=host, port=port, debug=False, threaded=True)