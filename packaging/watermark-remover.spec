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
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# OpenCV 包含 .so/.dylib 和 data 目录，必须 collect_all 全部带上
cv2_datas, cv2_binaries, cv2_hiddenimports = collect_all("cv2")
np_datas, np_binaries, np_hiddenimports = collect_all("numpy")

a = Analysis(
    ["../app.py"],
    pathex=[],
    binaries=[("../ffmpeg", "."), ("../ffprobe", ".")] + cv2_binaries + np_binaries,
    datas=[
        ("../templates", "templates"),
        ("../static", "static"),
    ] + cv2_datas + np_datas,
    hiddenimports=["flask", "werkzeug"] + cv2_hiddenimports + np_hiddenimports,
    hookspath=[],
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
        icon=None,
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