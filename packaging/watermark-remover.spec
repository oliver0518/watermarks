# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Watermark Remover (macOS / Linux / Windows).

Generates a single-folder or .app build that bundles:
- Python interpreter
- Flask + OpenCV + numpy dependencies
- ffmpeg / ffprobe binaries (PyInstaller --add-binary)
- templates / static assets

Usage:
    pyinstaller packaging/watermark-remover.spec
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# PyInstaller 跑 spec 时会注入 SPECPATH（spec 文件所在目录）。
# 我们把 spec 放在 packaging/，所以 project_root 在 SPECPATH 的父目录。
project_root = Path(SPECPATH).resolve().parent

# 跨平台 ffmpeg/ffprobe 路径：Windows 上是 .exe，macOS/Linux 是无后缀
_exe_suffix = ".exe" if sys.platform == "win32" else ""
ffmpeg_src = str(project_root / f"ffmpeg{_exe_suffix}")
ffprobe_src = str(project_root / f"ffprobe{_exe_suffix}")

# OpenCV 包含 .so/.dylib 和 data 目录，必须 collect_all 全部带上
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")
np_datas, np_binaries, np_hiddenimports = collect_all("numpy")
# pywebview：依赖动态选择的后端（macOS=cocoa, Linux=gtk, Windows=win32）
# collect_all 收 datas/binaries，collect_submodules 强制拉所有 platform 子模块
pwv_datas, pwv_binaries, pwv_hiddenimports = collect_all("webview")
pwv_platforms_hidden = collect_submodules("webview.platforms")

# PyInstaller contrib hooks（含 hook-webview.py）
import _pyinstaller_hooks_contrib
_pyinstaller_hooks_contrib_dir = os.path.dirname(_pyinstaller_hooks_contrib.__file__)
_contrib_hookspath = [os.path.join(_pyinstaller_hooks_contrib_dir, "stdhooks")]
# pywebview 自带的 hook（在包内的 __pyinstaller/）
_webview_hookspath = os.path.join(
    os.path.dirname(__import__("webview").__file__), "__pyinstaller"
)

a = Analysis(
    [str(project_root / "app.py")],
    pathex=[],
    binaries=[
        (ffmpeg_src, "."), (ffprobe_src, "."),
    ] + cv2_binaries + np_binaries + pwv_binaries,
    datas=[
        (str(project_root / "templates"), "templates"),
        (str(project_root / "static"), "static"),
    ] + cv2_datas + np_datas + pwv_datas,
    hiddenimports=[
        "flask", "werkzeug",
        # pywebview 必须显式列出的子模块（含动态加载的后端）
        "webview", "webview.guilib", "webview.http", "webview.menu", "webview.window",
        "webview.screen", "webview.util", "webview.errors", "webview.localization",
        "clr_loader", "pythonnet",
        "proxy_tools",
    ] + cv2_hiddenimports + np_hiddenimports + pwv_hiddenimports + list(pwv_platforms_hidden),
    hookspath=_contrib_hookspath + [_webview_hookspath],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WatermarkRemover",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                # macOS 上 .app 双击时不弹终端
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=("icon.ico" if sys.platform == "win32" else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="WatermarkRemover",
)

# macOS: BUNDLE 把单文件夹产物包成 .app
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="WatermarkRemover.app",
        icon="icon.icns",
        bundle_identifier="cc.oliver.watermark-remover",
        info_plist={
            "CFBundleName": "Watermark Remover",
            "CFBundleDisplayName": "Watermark Remover",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.video",
            "LSMinimumSystemVersion": "11.0",
        },
    )