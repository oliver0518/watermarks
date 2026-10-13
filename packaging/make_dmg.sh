#!/bin/bash
# 把 .app 打包成 .dmg（含 Applications 快捷方式）
set -e

APP_SRC="${1:-packaging/dist/WatermarkRemover.app}"
DMG_NAME="${2:-WatermarkRemover-1.0.0-macOS.dmg}"
STAGE="$(mktemp -d)"

echo "[1/2] stage $APP_SRC -> $STAGE"
cp -R "$APP_SRC" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "[2/2] build dmg -> $DMG_NAME"
hdiutil create \
  -volname "Watermark Remover 1.0.0" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$DMG_NAME"

rm -rf "$STAGE"
echo "done: $(stat -f%z "$DMG_NAME") bytes"