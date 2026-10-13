# Windows 自动启动

让 watermark-remover 在 Windows 登录时自动启动，无需手动运行 PowerShell 脚本。

## 方式一：任务计划程序（推荐）

1. 按 `Win + S`，搜索并启动 **任务计划程序**（Task Scheduler）
2. 右侧点击 **创建任务**（不是 "创建基本任务"）
3. **常规**选项卡：
   - 名称：`Watermark Remover`
   - 勾选 "不管用户是否登录都要运行"
4. **触发器**选项卡：
   - 新建 → 登录时 → 特定用户 → 当前用户
5. **操作**选项卡：
   - 新建 → 启动程序
   - 程序或脚本：`powershell.exe`
   - 添加参数：`-NoProfile -ExecutionPolicy Bypass -File "C:\path\to\watermark-remover\scripts\dev.ps1"`
   - 起始于：`C:\path\to\watermark-remover`
6. **条件**选项卡：
   - 取消勾选 "只有在使用交流电源时才启动"
7. **设置**选项卡：
   - 勾选 "如果任务失败，按以下频率重新启动"
   - 间隔 1 分钟，最多 3 次尝试
8. 点击确定

完成后重启电脑，服务将在后台自动启动。

## 方式二：启动文件夹快捷方式

1. 按 `Win + R`，输入 `shell:startup`，回车
2. 在打开的文件夹中创建 `watermark-remover.bat`：

```bat
@echo off
cd /d "C:\path\to\watermark-remover"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\dev.ps1"
```

## 方式三：NSSM（生产环境）

如果需要更专业的服务管理（崩溃自动重启、开机自启、统一日志），使用 [NSSM](https://nssm.cc/)：

```powershell
# 安装服务
nssm install WatermarkRemover "C:\path\to\watermark-remover\.venv\Scripts\python.exe" "app.py"
nssm set WatermarkRemover AppDirectory "C:\path\to\watermark-remover"
nssm set WatermarkRemover AppStdout "C:\path\to\watermark-remover\logs\service.log"
nssm set WatermarkRemover AppStderr "C:\path\to\watermark-remover\logs\service.log"
nssm set WatermarkRemover Start SERVICE_AUTO_START

# 启动
nssm start WatermarkRemover

# 停止 / 删除
nssm stop WatermarkRemover
nssm remove WatermarkRemover confirm
```

## 自定义端口

任务计划程序方式中，编辑任务操作的"添加参数"为：

```
-NoProfile -ExecutionPolicy Bypass -Command "$env:DEPLOY_RUN_PORT='9000'; & 'C:\path\to\watermark-remover\scripts\dev.ps1'"
```

## 验证

```powershell
# 检查服务进程
Get-Process -Name python | Where-Object { $_.Path -like "*watermark-remover*" }

# 查看日志
Get-Content C:\path\to\watermark-remover\logs\server.log -Tail 20

# 测试连通性
Test-NetConnection -ComputerName 127.0.0.1 -Port 8300
```

浏览器访问 `http://127.0.0.1:8300` 应能看到去水印工具界面。