PY ?= python3
VENV := .venv

.PHONY: prepare serve stop dev clean check

prepare:
	@bash scripts/prepare.sh

serve:
	@bash scripts/dev.sh

stop:
	@bash scripts/stop.sh

# 前台运行（带错误日志实时输出，方便调试）
dev:
	@$(VENV)/bin/python app.py

clean:
	@find uploads output logs -mindepth 1 -maxdepth 1 \
		! -name '.gitkeep' -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned runtime artifacts"

check:
	@$(VENV)/bin/python -c "import cv2, numpy, flask; print('deps ok')"