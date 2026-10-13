#!/bin/bash
# 把 .app 打包成 .dmg（含 Applications 快捷方式 + Launch.command）
set -e

APP_SRC="${1:-packaging/dist/WatermarkRemover.app}"
DMG_NAME="${2:-WatermarkRemover-1.0.1-macOS.dmg}"
STAGE="$(mktemp -d)"

# 仅作 ad-hoc 签名（不要 hardened runtime，会触发更严 Gatekeeper）
if ! codesign -dv "$APP_SRC" 2>/dev/null | grep -q "adhoc"; then
  echo "[1/4] ad-hoc codesign"
  codesign --force --deep --sign - "$APP_SRC"
fi

echo "[2/4] stage $APP_SRC + Launch.command -> $STAGE"
cp -R "$APP_SRC" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# 把 Launch.command 也包进 DMG，给小白用户一个"双击就能跑"的入口
cat > "$STAGE/启动 Watermark Remover.command" <<'LAUNCH_EOF'
#!/bin/bash
# 双击启动 Watermark Remover，绕开 .app 启动验证
APP="/Applications/WatermarkRemover.app"
if [ ! -d "$APP" ]; then
  APP="$HOME/Applications/WatermarkRemover.app"
fi
if [ ! -d "$APP" ]; then
  osascript -e 'display dialog "找不到 WatermarkRemover.app，请先把它拖到 Applications 文件夹" buttons {"好"} default button 1 with icon caution'
  exit 1
fi
xattr -dr com.apple.quarantine "$APP" 2>/dev/null
BIN="$APP/Contents/MacOS/WatermarkRemover"
if [ ! -x "$BIN" ]; then
  osascript -e 'display dialog "找不到内部程序" buttons {"好"} default button 1 with icon caution'
  exit 1
fi
nohup "$BIN" >/dev/null 2>&1 &
sleep 2
open http://127.0.0.1:8300
echo "已启动。停止：在活动监视器结束 WatermarkRemover 进程，或 Terminal 跑：pkill -f WatermarkRemover"
LAUNCH_EOF
chmod +x "$STAGE/启动 Watermark Remover.command"

echo "[3/4] build dmg -> $DMG_NAME"
hdiutil create \
  -volname "Watermark Remover 1.0.1" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$DMG_NAME"

echo "[4/4] cleanup"
rm -rf "$STAGE"
echo "done: $(stat -f%z "$DMG_NAME") bytes"