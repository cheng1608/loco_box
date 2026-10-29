# 自动验证

`workflows/ci.yml` 在推送（含标签）、Pull Request 和手动运行时验证当前 Windows 桌面架构：

- Python 3.9 安装 `requirements.txt`，运行后端单元测试及真实子进程退出测试。
- Node.js 22 使用 `npm ci` 安装锁定的前端依赖，进行 Vue 类型检查和生产构建，再运行 Chromium 启动与断线恢复测试。
- Rust stable 运行桌面后端身份检查测试，然后通过 `npm run desktop:build` 构建 Tauri 可执行文件。

Python 和桌面任务并行执行。pip、npm 和 Cargo 缓存减少后续构建耗时；浏览器测试失败时保留诊断文件 7 天。

当前工作流只做验证，不创建 GitHub Release，也不上传桌面程序作为用户安装包。`app.exe` 已包含前端资源，但后端仍来自本仓库，并需要仓库内 `.venv`。直接运行源码构建产物时，可设置 `LOCO_BOX_ROOT` 为仓库绝对路径；本地日常使用请运行根目录 `start.bat`。真正的独立发行包还需要 Python 后端 sidecar 和对应的打包、安装验证。

旧版 `release.yml` 使用已删除的 `main.py` 和 CustomTkinter 进行 PyInstaller 打包，已由此工作流替换。
