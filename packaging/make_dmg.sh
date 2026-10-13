#!/bin/bash
# 把 .app 打包成 .dmg（含 Applications 快捷方式 + 桌面 symlink）
set -e

APP_SRC="${1:-packaging/dist/WatermarkRemover.app}"
DMG_NAME="${2:-WatermarkRemover-1.0.1-macOS.dmg}"
STAGE="$(mktemp -d)"

# 仅作 ad-hoc 签名（不要 hardened runtime，会触发更严 Gatekeeper）
if ! codesign -dv "$APP_SRC" 2>/dev/null | grep -q "adhoc"; then
  echo "[1/3] ad-hoc codesign"
  codesign --force --deep --sign - "$APP_SRC"
fi

echo "[2/3] stage $APP_SRC -> $STAGE"
cp -R "$APP_SRC" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
# 桌面快捷方式（symlink）：拖到桌面/Dock/任何位置双击都能启动
ln -s "/Applications/WatermarkRemover.app" "$STAGE/快捷方式：Watermark Remover"

echo "[3/3] build dmg -> $DMG_NAME"
hdiutil create \
  -volname "Watermark Remover 1.0.1" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$DMG_NAME"

rm -rf "$STAGE"
echo "done: $(stat -f%z "$DMG_NAME") bytes"