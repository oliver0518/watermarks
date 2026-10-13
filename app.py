# -*- coding: utf-8 -*-
"""
本地视频去水印工具 - Flask 后端
技术栈: Flask + OpenCV(inpainting) + FFmpeg
完全本地处理，不上传任何数据。
"""
import os
import uuid
import subprocess
import tempfile
import shutil
import json
import glob
import logging

import cv2
import numpy as np
from flask import (
    Flask, request, jsonify, render_template, send_from_directory, send_file, abort
)

# ---------- 配置 ----------

app = Flask(__name__)
# 限制上传大小：1 GiB。Flask 会在超大请求时直接抛 413，避免内存被打爆。
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
OUTPUT_DIR = os.path.join(BASE, "output")
LOG_DIR = os.path.join(BASE, "logs")
for d in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
    os.makedirs(d, exist_ok=True)

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("watermark-remover")


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
    f = request.files.get("video")
    if not f:
        return jsonify({"error": "未收到文件"}), 400
    if not allowed_file(f.filename):
        return jsonify({"error": "不支持的视频格式"}), 400
    sid = uuid.uuid4().hex
    ext = os.path.splitext(f.filename)[1].lower()
    src = os.path.join(UPLOAD_DIR, sid + ext)
    f.save(src)

    # magic bytes 校验
    kind = detect_kind(src)
    if kind is None:
        os.remove(src)
        return jsonify({"error": "文件内容与扩展名不符，可能不是有效视频"}), 400

    info = video_info(src)
    if info["width"] <= 0 or info["height"] <= 0:
        os.remove(src)
        return jsonify({"error": "无法解析该视频"}), 400
    log.info("upload sid=%s %dx%d %.2fs", sid, info["width"], info["height"], info["duration"])
    return jsonify({
        "id": sid,
        "src": f"/uploads/{sid}{ext}",
        "info": info,
    })


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
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频文件")
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

    matches = glob.glob(os.path.join(UPLOAD_DIR, vid) + ".*")
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
        public_out = os.path.join(OUTPUT_DIR, vid + "_result.mp4")
        safe_move(final, public_out)
        shutil.rmtree(tmpdir, ignore_errors=True)
        log.info("processed sid=%s -> %s", vid, public_out)
        return jsonify({
            "success": True,
            "url": f"/output/{os.path.basename(public_out)}",
            "info": {"width": finfo["width"], "height": finfo["height"],
                     "fps": finfo["fps"]}
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


# ---------- 入口 ----------

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "上传文件过大（上限 1 GiB）"}), 413


if __name__ == "__main__":
    port = int(os.environ.get("DEPLOY_RUN_PORT", "8300"))
    log.info("starting watermark-remover on http://127.0.0.1:%d", port)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)