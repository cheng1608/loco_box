# 自动验证

`workflows/ci.yml` 在推送（含标签）、Pull Request 和手动运行时验证当前 Windows 桌面架构：

- Python 3.9 安装并检查 `requirements.txt` 中的依赖，运行后端生命周期、Arduino 协议、自动演奏和精灵查看回归测试。
- Node.js 24 使用 `npm ci` 安装锁定的前端依赖，进行 Vue 类型检查和生产构建，再用 Chromium 验证启动恢复、悬浮窗、自动演奏和精灵查看。
- Rust stable 运行桌面后端身份检查测试，然后通过 `npm run desktop:build` 构建 Tauri 可执行文件。
- Arduino 任务在 Linux 验证固件状态机，使用 Arduino CLI 1.4.1、AVR core 1.8.8 和 Mouse 1.0.1 编译 Micro / Leonardo 的九键与六键固件。

Python、桌面和固件任务并行执行。pip、npm 和 Cargo 缓存减少后续构建耗时。浏览器测试失败时保留诊断文件 7 天。精灵查看用合成报文和测试资源验证，无需安装 Npcap、导入游戏资源或运行游戏。固件测试无需连接实体开发板。

当前工作流只做验证，不创建 GitHub Release，也不上传桌面程序作为用户安装包。`app.exe` 已包含前端资源，但后端仍来自本仓库，并需要仓库内 `.venv`。直接运行源码构建产物时，可设置 `LOCO_BOX_ROOT` 为仓库绝对路径；本地日常使用请运行根目录 `start.bat`。真正的独立发行包还需要 Python 后端 sidecar 和对应的打包、安装验证。

旧版 `release.yml` 使用已删除的 `main.py` 和 CustomTkinter 进行 PyInstaller 打包，已由此工作流替换。
