#!/bin/bash
# 把 .app 打包成 .dmg（含 Applications 快捷方式）
set -e

APP_SRC="${1:-packaging/dist/WatermarkRemover.app}"
DMG_NAME="${2:-WatermarkRemover-1.0.1-macOS.dmg}"
STAGE="$(mktemp -d)"

# 如果 .app 未签或签名为空，自动加 hardened runtime + ad-hoc 签名
if ! codesign -dv "$APP_SRC" 2>/dev/null | grep -q "adhoc"; then
  echo "[1/3] ad-hoc codesign + hardened runtime"
  codesign --force --deep --sign - --options runtime "$APP_SRC"
fi

echo "[2/3] stage $APP_SRC -> $STAGE"
cp -R "$APP_SRC" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

echo "[3/3] build dmg -> $DMG_NAME"
hdiutil create \
  -volname "Watermark Remover 1.0.1" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$DMG_NAME"

rm -rf "$STAGE"
echo "done: $(stat -f%z "$DMG_NAME") bytes"